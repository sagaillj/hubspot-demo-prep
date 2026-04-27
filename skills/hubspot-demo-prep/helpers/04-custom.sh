#!/usr/bin/env bash
# Create custom objects + custom events when build plan calls for them.
# Reads /tmp/demo-prep-<slug>/build-plan.json — uses .custom_object and .custom_events keys.
#
# Usage: 04-custom.sh <customer-slug>

source "$(dirname "$0")/lib.sh"
load_env

SLUG="${1:-}"
[[ -n "$SLUG" ]] || fail "Usage: 04-custom.sh <slug>"

WORK="$(work_dir "$SLUG")"
PLAN="$WORK/build-plan.json"
MANIFEST="$WORK/manifest.json"
PORTAL=$(sandbox_portal_id)

# ---- Custom object ----

HAS_CUSTOM_OBJECT=$(python3 -c "
import json
plan = json.load(open('$PLAN'))
print('yes' if plan.get('custom_object') else 'no')
")

if [[ "$HAS_CUSTOM_OBJECT" == "yes" ]]; then
  CO_NAME=$(python3 -c "import json; print(json.load(open('$PLAN'))['custom_object']['name'])")
  info "Creating custom object: $CO_NAME"

  # Check if schema already exists (sandboxes persist across runs)
  existing=$(hs_curl GET "/crm/v3/schemas" "")
  existing_id=$(echo "$existing" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for s in data.get('results', []):
    if s.get('name') == '''$CO_NAME''':
        print(s['objectTypeId'])
        break
")

  if [[ -n "$existing_id" ]]; then
    OBJECT_TYPE_ID="$existing_id"
    info "  Reusing existing schema (objectTypeId=$OBJECT_TYPE_ID)"
  else
    schema_body=$(python3 -c "
import json
co = json.load(open('$PLAN'))['custom_object']
body = {
    'name': co['name'],
    'labels': co['labels'],
    'primaryDisplayProperty': co['primary_display'],
    'secondaryDisplayProperties': co.get('secondary_display', []),
    'requiredProperties': co.get('required', [co['primary_display']]),
    'searchableProperties': co.get('searchable', [co['primary_display']]),
    'properties': co['properties'],
    'associatedObjects': co.get('associated_objects', ['CONTACT', 'COMPANY', 'DEAL'])
}
print(json.dumps(body))
")
    resp=$(hs_curl POST "/crm/v3/schemas" "$schema_body")
    if [[ "$HS_LAST_STATUS" =~ ^2 ]]; then
      OBJECT_TYPE_ID=$(echo "$resp" | python3 -c "import json, sys; print(json.load(sys.stdin)['objectTypeId'])")
      ok "Created custom object schema (objectTypeId=$OBJECT_TYPE_ID)"
    else
      warn "Custom object creation failed (HTTP $HS_LAST_STATUS): $resp"
      OBJECT_TYPE_ID=""
    fi
  fi

  if [[ -n "$OBJECT_TYPE_ID" ]]; then
    # Add demo_customer property
    prop_body=$(cat <<JSON
{"name":"demo_customer","label":"Demo Customer Slug","type":"string","fieldType":"text"}
JSON
)
    hs_curl POST "/crm/v3/properties/$OBJECT_TYPE_ID" "$prop_body" >/dev/null

    # Create records
    records=$(python3 -c "
import json
co = json.load(open('$PLAN'))['custom_object']
recs = co.get('records', [])
inputs = []
for r in recs:
    props = dict(r)
    props['demo_customer'] = '$SLUG'
    inputs.append({'properties': props})
print(json.dumps({'inputs': inputs}))
")
    resp=$(hs_curl POST "/crm/v3/objects/$OBJECT_TYPE_ID/batch/create" "$records")
    if [[ "$HS_LAST_STATUS" =~ ^2 ]]; then
      record_count=$(echo "$resp" | python3 -c "import json, sys; print(len(json.load(sys.stdin).get('results', [])))")
      ok "  Created $record_count $CO_NAME records"
    else
      warn "  Record creation failed (HTTP $HS_LAST_STATUS): $resp"
    fi

    manifest_add "$SLUG" "custom_object" "name" "$CO_NAME"
    manifest_add "$SLUG" "custom_object" "object_type_id" "$OBJECT_TYPE_ID"
    manifest_add "$SLUG" "custom_object" "url" "https://app.hubspot.com/contacts/$PORTAL/objects/$OBJECT_TYPE_ID"
  fi
fi

# ---- Custom events ----

HAS_CUSTOM_EVENTS=$(python3 -c "
import json
plan = json.load(open('$PLAN'))
print('yes' if plan.get('custom_events') else 'no')
")

if [[ "$HAS_CUSTOM_EVENTS" == "yes" ]]; then
  info "Creating custom events..."

  python3 -c "
import json
events = json.load(open('$PLAN'))['custom_events']
print(json.dumps(events))
" > "$WORK/events-list.json"

  python3 -c "
import json
events = json.load(open('$WORK/events-list.json'))
for e in events:
    print(json.dumps(e))
" | while read -r event_json; do
    event_name=$(echo "$event_json" | python3 -c "import json, sys; print(json.load(sys.stdin)['name'])")

    # Create definition
    def_body=$(echo "$event_json" | python3 -c "
import json, sys
e = json.load(sys.stdin)
body = {
    'label': e.get('label', e['name']),
    'name': e['name'],
    'description': e.get('description', ''),
    'primaryObject': e.get('primary_object', 'CONTACT'),
    'propertyDefinitions': e.get('properties', [])
}
print(json.dumps(body))
")
    resp=$(hs_curl POST "/events/v3/event-definitions" "$def_body")
    if [[ "$HS_LAST_STATUS" =~ ^2 ]]; then
      full_name=$(echo "$resp" | python3 -c "import json, sys; print(json.load(sys.stdin).get('fullyQualifiedName', json.load(sys.stdin).get('name', '')))" 2>/dev/null || echo "")
      [[ -z "$full_name" ]] && full_name=$(echo "$resp" | python3 -c "import json, sys; d=json.load(sys.stdin); print(d.get('fullyQualifiedName') or d.get('name', ''))")
      ok "  Event definition: $event_name → $full_name"
      manifest_add "$SLUG" "custom_events" "$event_name" "$full_name"
    elif [[ "$HS_LAST_STATUS" == "409" ]]; then
      info "  Event $event_name already exists (reusing)"
      # Get fully qualified name for the existing one
      existing=$(hs_curl GET "/events/v3/event-definitions/$event_name" "")
      full_name=$(echo "$existing" | python3 -c "import json, sys; d=json.load(sys.stdin); print(d.get('fullyQualifiedName') or d.get('name', ''))")
      manifest_add "$SLUG" "custom_events" "$event_name" "$full_name"
    else
      warn "  Event definition $event_name failed (HTTP $HS_LAST_STATUS): $resp"
    fi
  done

  # Fire events on contacts
  info "Firing custom events on demo contacts..."
  python3 -c "
import json
m = json.load(open('$MANIFEST'))
contacts = m.get('contacts', {})
events = m.get('custom_events', {})
print(json.dumps({'contacts': contacts, 'events': events}))
" > "$WORK/event-fire-data.json"

  python3 -c "
import json, random, time
data = json.load(open('$WORK/event-fire-data.json'))
contacts = data['contacts']
events = data['events']
plan_events = json.load(open('$PLAN'))['custom_events']
fires_per_contact = 5
random.seed(42)

for email, cid in contacts.items():
    for fire_i in range(fires_per_contact):
        for evt in plan_events:
            evt_name = evt['name']
            full_name = events.get(evt_name, evt_name)
            days_back = random.randint(1, 120)
            sample_props = {p['name']: p.get('demo_value', 'sample') for p in evt.get('properties', [])}
            send_body = {
                'eventName': full_name,
                'email': email,
                'properties': sample_props,
                'occurredAt': __import__('datetime').datetime.utcnow().isoformat() + 'Z'
            }
            print(json.dumps(send_body))
" | while read -r send_json; do
    hs_curl POST "/events/v3/send" "$send_json" >/dev/null 2>&1 || true
  done
  ok "  Fired custom events"
fi

ok "Custom objects/events phase complete for $SLUG"
manifest_add "$SLUG" "_meta" "phase_3_custom_done" "true"
