#!/usr/bin/env bash
# Seed CRM: company, contacts, deal pipeline, deals, ticket pipeline, tickets.
# Reads /tmp/demo-prep-<slug>/build-plan.json (built by Claude in Phase 2).
# Writes /tmp/demo-prep-<slug>/manifest.json with all created IDs + URLs.
#
# Usage: 02-seed-crm.sh <customer-slug>

source "$(dirname "$0")/lib.sh"
load_env

SLUG="${1:-}"
[[ -n "$SLUG" ]] || fail "Usage: 02-seed-crm.sh <slug>"

WORK="$(work_dir "$SLUG")"
PLAN="$WORK/build-plan.json"
MANIFEST="$WORK/manifest.json"
PORTAL=$(sandbox_portal_id)

[[ -f "$PLAN" ]] || fail "Missing build plan at $PLAN. Run Phase 2 synthesis first."

info "Seeding CRM for $SLUG (sandbox $PORTAL)"

# ---- Step 1: ensure demo_customer property exists on all relevant object types ----

ensure_property() {
  local object_path="$1"
  # Map object_path → correct HubSpot groupName (no underscore between word and "information")
  local group
  case "$object_path" in
    contacts)   group="contactinformation" ;;
    companies)  group="companyinformation" ;;
    deals)      group="dealinformation" ;;
    tickets)    group="ticketinformation" ;;
    *)          group="" ;;
  esac
  local body
  body=$(cat <<JSON
{
  "name": "demo_customer",
  "label": "Demo Customer Slug",
  "type": "string",
  "fieldType": "text",
  "groupName": "$group",
  "description": "Tags demo data created by hubspot-demo-prep skill. Used for cleanup."
}
JSON
)
  local resp
  resp=$(hs_curl POST "/crm/v3/properties/$object_path" "$body")
  if [[ "$HS_LAST_STATUS" =~ ^(2|409) ]]; then
    ok "  property demo_customer ready on $object_path"
  else
    warn "  property creation failed for $object_path (HTTP $HS_LAST_STATUS): $resp"
  fi
}

ensure_property "contacts"
ensure_property "companies"
ensure_property "deals"
ensure_property "tickets"

# ---- Step 2: create the company ----

COMPANY_NAME=$(python3 -c "import json; print(json.load(open('$PLAN'))['company']['name'])")
COMPANY_DOMAIN=$(python3 -c "import json; print(json.load(open('$PLAN'))['company']['domain'])")
COMPANY_INDUSTRY=$(python3 -c "import json; print(json.load(open('$PLAN'))['company'].get('industry', 'OTHER'))")
COMPANY_DESC=$(python3 -c "import json; print(json.load(open('$PLAN'))['company'].get('description', ''))")

company_body=$(python3 -c "
import json
body = {
  'properties': {
    'name': '''$COMPANY_NAME''',
    'domain': '''$COMPANY_DOMAIN''',
    'industry': '''$COMPANY_INDUSTRY''',
    'description': '''$COMPANY_DESC''',
    'demo_customer': '''$SLUG'''
  }
}
print(json.dumps(body))
")

resp=$(hs_curl POST "/crm/v3/objects/companies" "$company_body")
COMPANY_ID=$(echo "$resp" | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])")
ok "Company: $COMPANY_NAME (id=$COMPANY_ID)"
manifest_add "$SLUG" "company" "id" "$COMPANY_ID"
manifest_add "$SLUG" "company" "name" "$COMPANY_NAME"
manifest_add "$SLUG" "company" "url" "https://app.hubspot.com/contacts/$PORTAL/record/0-2/$COMPANY_ID"

# ---- Step 3: create contacts ----

info "Creating contacts..."
python3 -c "
import json
contacts = json.load(open('$PLAN'))['contacts']
print(json.dumps([{
    'properties': {
        'email': c['email'],
        'firstname': c['firstname'],
        'lastname': c['lastname'],
        'jobtitle': c.get('jobtitle', ''),
        'phone': c.get('phone', ''),
        'demo_customer': '$SLUG',
        'lifecyclestage': c.get('lifecyclestage', 'lead')
    }
} for c in contacts]))
" > "$WORK/contacts-batch.json"

contacts_body=$(python3 -c "
import json
inputs = json.load(open('$WORK/contacts-batch.json'))
print(json.dumps({'inputs': inputs}))
")

resp=$(hs_curl POST "/crm/v3/objects/contacts/batch/upsert" "$contacts_body")
if [[ "$HS_LAST_STATUS" != "200" && "$HS_LAST_STATUS" != "201" ]]; then
  # Fall back to individual create
  warn "Batch upsert failed (HTTP $HS_LAST_STATUS), falling back to per-contact create"
  resp='{"results":[]}'
  python3 -c "
import json
contacts = json.load(open('$WORK/contacts-batch.json'))
for i, c in enumerate(contacts):
    print(json.dumps(c))
" | while read -r contact_json; do
    r=$(hs_curl POST "/crm/v3/objects/contacts" "$contact_json")
    if [[ "$HS_LAST_STATUS" =~ ^2 ]]; then
      cid=$(echo "$r" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
      cemail=$(echo "$contact_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['properties']['email'])")
      manifest_add "$SLUG" "contacts" "$cemail" "$cid"
      ok "  contact $cemail (id=$cid)"
    fi
  done
else
  echo "$resp" | python3 -c "
import json, sys, subprocess
data = json.load(sys.stdin)
for r in data.get('results', []):
    cid = r['id']
    cemail = r['properties'].get('email', 'unknown')
    print(f'{cemail}|{cid}')
" | while IFS='|' read -r email cid; do
    manifest_add "$SLUG" "contacts" "$email" "$cid"
    echo "  contact $email (id=$cid)"
  done
  ok "Contacts batch upserted"
fi

# ---- Step 4: associate contacts to company ----

info "Associating contacts to company..."
python3 -c "
import json
m = json.load(open('$MANIFEST'))
contacts = m.get('contacts', {})
print(' '.join(contacts.values()))
" | tr ' ' '\n' | while read -r cid; do
  [[ -z "$cid" ]] && continue
  hs_curl PUT "/crm/v3/objects/contacts/$cid/associations/companies/$COMPANY_ID/1" "" >/dev/null
done
ok "Contact-company associations done"

# ---- Step 5: deal pipeline + stages + deals ----

PIPELINE_NAME=$(python3 -c "import json; print(json.load(open('$PLAN'))['deal_pipeline']['name'])")

# Check if pipeline already exists
existing=$(hs_curl GET "/crm/v3/pipelines/deals" "")
existing_id=$(echo "$existing" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for p in data.get('results', []):
    if p.get('label') == '''$PIPELINE_NAME''':
        print(p['id'])
        break
")

if [[ -n "$existing_id" ]]; then
  PIPELINE_ID="$existing_id"
  info "Reusing existing pipeline: $PIPELINE_NAME ($PIPELINE_ID)"
else
  pipeline_body=$(python3 -c "
import json
plan = json.load(open('$PLAN'))['deal_pipeline']
body = {
    'label': plan['name'],
    'displayOrder': 99,
    'stages': [
        {'label': s['label'], 'displayOrder': i, 'metadata': {'probability': str(s['probability'])}}
        for i, s in enumerate(plan['stages'])
    ]
}
print(json.dumps(body))
")
  resp=$(hs_curl POST "/crm/v3/pipelines/deals" "$pipeline_body")
  PIPELINE_ID=$(echo "$resp" | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])")
  ok "Created deal pipeline: $PIPELINE_NAME ($PIPELINE_ID)"
fi

# Map stage label → stage id
STAGE_MAP=$(hs_curl GET "/crm/v3/pipelines/deals/$PIPELINE_ID" "" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(json.dumps({s['label']: s['id'] for s in data.get('stages', [])}))
")
echo "$STAGE_MAP" > "$WORK/stage-map.json"

manifest_add "$SLUG" "pipeline" "id" "$PIPELINE_ID"
manifest_add "$SLUG" "pipeline" "name" "$PIPELINE_NAME"
manifest_add "$SLUG" "pipeline" "url" "https://app.hubspot.com/sales/$PORTAL/deals/board/view/all/?pipeline=$PIPELINE_ID"

# Create deals
info "Creating deals..."
python3 -c "
import json
plan = json.load(open('$PLAN'))['deals']
stages = json.load(open('$WORK/stage-map.json'))
m = json.load(open('$MANIFEST'))
contact_ids = list(m.get('contacts', {}).values())
inputs = []
for i, d in enumerate(plan):
    stage_id = stages.get(d['stage'])
    if not stage_id:
        continue
    primary_contact = contact_ids[i % len(contact_ids)] if contact_ids else None
    inputs.append({
        'properties': {
            'dealname': d['name'],
            'amount': str(d.get('amount', 5000)),
            'pipeline': '$PIPELINE_ID',
            'dealstage': stage_id,
            'closedate': d.get('closedate', ''),
            'demo_customer': '$SLUG'
        },
        '_contact_id': primary_contact
    })
print(json.dumps(inputs))
" > "$WORK/deals-input.json"

python3 -c "
import json
data = json.load(open('$WORK/deals-input.json'))
print(json.dumps({'inputs': [{'properties': d['properties']} for d in data]}))
" > "$WORK/deals-batch.json"

resp=$(hs_curl POST "/crm/v3/objects/deals/batch/create" "$(cat "$WORK/deals-batch.json")")
echo "$resp" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for r in data.get('results', []):
    print(f'{r[\"properties\"][\"dealname\"]}|{r[\"id\"]}')
" | while IFS='|' read -r dname did; do
  manifest_add "$SLUG" "deals" "$dname" "$did"
  ok "  deal $dname (id=$did)"
  # Associate to company + first contact
  hs_curl PUT "/crm/v3/objects/deals/$did/associations/companies/$COMPANY_ID/5" "" >/dev/null
done

# Associate first contact to first deal for richer demo timeline
FIRST_DEAL_ID=$(python3 -c "
import json
m = json.load(open('$MANIFEST'))
deals = list(m.get('deals', {}).values())
print(deals[0] if deals else '')
")
FIRST_CONTACT_ID=$(python3 -c "
import json
m = json.load(open('$MANIFEST'))
contacts = list(m.get('contacts', {}).values())
print(contacts[0] if contacts else '')
")
if [[ -n "$FIRST_DEAL_ID" && -n "$FIRST_CONTACT_ID" ]]; then
  hs_curl PUT "/crm/v3/objects/deals/$FIRST_DEAL_ID/associations/contacts/$FIRST_CONTACT_ID/3" "" >/dev/null
fi

# ---- Step 6: tickets (if any) ----

TICKET_COUNT=$(python3 -c "
import json
plan = json.load(open('$PLAN'))
print(len(plan.get('tickets', [])))
")

if [[ "$TICKET_COUNT" -gt 0 ]]; then
  info "Creating $TICKET_COUNT tickets..."

  # Get default ticket pipeline (every portal has one)
  ticket_pipeline=$(hs_curl GET "/crm/v3/pipelines/tickets" "" | python3 -c "
import json, sys
data = json.load(sys.stdin)
default = data.get('results', [{}])[0]
print(json.dumps({
    'id': default.get('id', ''),
    'first_stage': default.get('stages', [{}])[0].get('id', '')
}))
")
  TICKET_PIPELINE_ID=$(echo "$ticket_pipeline" | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])")
  TICKET_FIRST_STAGE=$(echo "$ticket_pipeline" | python3 -c "import json, sys; print(json.load(sys.stdin)['first_stage'])")

  python3 -c "
import json
plan = json.load(open('$PLAN'))['tickets']
inputs = [{
    'properties': {
        'subject': t['subject'],
        'content': t.get('content', ''),
        'hs_pipeline': '$TICKET_PIPELINE_ID',
        'hs_pipeline_stage': '$TICKET_FIRST_STAGE',
        'hs_ticket_priority': t.get('priority', 'MEDIUM'),
        'demo_customer': '$SLUG'
    }
} for t in plan]
print(json.dumps({'inputs': inputs}))
" > "$WORK/tickets-batch.json"

  resp=$(hs_curl POST "/crm/v3/objects/tickets/batch/create" "$(cat "$WORK/tickets-batch.json")")
  echo "$resp" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for r in data.get('results', []):
    print(f'{r[\"properties\"][\"subject\"]}|{r[\"id\"]}')
" | while IFS='|' read -r tsubj tid; do
    manifest_add "$SLUG" "tickets" "$tsubj" "$tid"
    ok "  ticket $tsubj (id=$tid)"
    hs_curl PUT "/crm/v3/objects/tickets/$tid/associations/companies/$COMPANY_ID/26" "" >/dev/null
  done
fi

ok "CRM seed complete for $SLUG"
manifest_add "$SLUG" "_meta" "phase_3_seed_crm_done" "true"
