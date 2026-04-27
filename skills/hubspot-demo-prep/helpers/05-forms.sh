#!/usr/bin/env bash
# Create forms + submit test fills to drive workflow enrollment.
# Reads build plan .forms[] entries.
#
# Usage: 05-forms.sh <customer-slug>

source "$(dirname "$0")/lib.sh"
load_env

SLUG="${1:-}"
[[ -n "$SLUG" ]] || fail "Usage: 05-forms.sh <slug>"

WORK="$(work_dir "$SLUG")"
PLAN="$WORK/build-plan.json"
MANIFEST="$WORK/manifest.json"
PORTAL=$(sandbox_portal_id)

HAS_FORMS=$(python3 -c "
import json
plan = json.load(open('$PLAN'))
print('yes' if plan.get('forms') else 'no')
")

if [[ "$HAS_FORMS" != "yes" ]]; then
  info "No forms in plan, skipping"
  exit 0
fi

info "Creating forms..."

python3 -c "
import json
forms = json.load(open('$PLAN'))['forms']
for f in forms:
    print(json.dumps(f))
" > "$WORK/forms-list.json"

while read -r form_json; do
  form_name=$(echo "$form_json" | python3 -c "import json, sys; print(json.load(sys.stdin)['name'])")

  # Check if form with this name already exists
  existing=$(hs_curl GET "/marketing/v3/forms?name=$(echo "$form_name" | sed 's/ /%20/g')" "")
  existing_guid=$(echo "$existing" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for f in data.get('results', []):
    if f.get('name') == '''$form_name''':
        print(f['id'])
        break
" 2>/dev/null || echo "")

  if [[ -n "$existing_guid" ]]; then
    FORM_GUID="$existing_guid"
    info "  Reusing existing form: $form_name ($FORM_GUID)"
  else
    body=$(echo "$form_json" | python3 -c "
import json, sys
f = json.load(sys.stdin)
body = {
    'name': f['name'],
    'formType': 'hubspot',
    'createdAt': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
    'archived': False,
    'fieldGroups': [{
        'groupType': 'default_group',
        'richTextType': 'text',
        'fields': [
            {
                'objectTypeId': '0-1',
                'name': field['name'],
                'label': field['label'],
                'required': field.get('required', False),
                'hidden': False,
                'fieldType': field.get('field_type', 'single_line_text')
            } for field in f['fields']
        ]
    }],
    'configuration': {
        'language': 'en',
        'cloneable': True,
        'editable': True,
        'archivable': True,
        'recaptchaEnabled': False,
        'createNewContactForNewEmail': False,
        'allowLinkToResetKnownValues': False
    },
    'displayOptions': {
        'renderRawHtml': False,
        'theme': 'default_style',
        'submitButtonText': f.get('submit_text', 'Submit')
    },
    'legalConsentOptions': {'type': 'none'}
}
print(json.dumps(body))
")
    resp=$(hs_curl POST "/marketing/v3/forms" "$body")
    if [[ "$HS_LAST_STATUS" =~ ^2 ]]; then
      FORM_GUID=$(echo "$resp" | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])")
      ok "  Created form: $form_name ($FORM_GUID)"
    else
      warn "  Form creation failed for $form_name (HTTP $HS_LAST_STATUS): $resp"
      continue
    fi
  fi

  manifest_add "$SLUG" "forms" "$form_name" "$FORM_GUID"

  # Submit test fills
  submit_count=$(echo "$form_json" | python3 -c "
import json, sys
f = json.load(sys.stdin)
print(f.get('test_submissions', 5))
")
  info "  Submitting $submit_count test fills for $form_name..."

  for i in $(seq 1 "$submit_count"); do
    submit_body=$(echo "$form_json" | python3 -c "
import json, sys, random
f = json.load(sys.stdin)
random.seed($i)
fields = []
for field in f['fields']:
    if field['name'] == 'email':
        val = f'demo-lead-$i-{random.randint(1000,9999)}@demo-$SLUG.test'
    elif field['name'] == 'firstname':
        val = random.choice(['Alex', 'Jordan', 'Taylor', 'Morgan', 'Casey', 'Riley'])
    elif field['name'] == 'lastname':
        val = random.choice(['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia'])
    else:
        val = field.get('demo_value', 'sample')
    fields.append({'objectTypeId': '0-1', 'name': field['name'], 'value': val})
print(json.dumps({'fields': fields, 'context': {'pageUri': f'https://example.com/demo-form', 'pageName': f.get('name', 'Demo')}}))
")
    hs_form_submit "$FORM_GUID" "$submit_body" >/dev/null 2>&1 || true
  done
  ok "  Form submissions complete"
done < "$WORK/forms-list.json"

ok "Forms phase complete for $SLUG"
manifest_add "$SLUG" "_meta" "phase_3_forms_done" "true"
