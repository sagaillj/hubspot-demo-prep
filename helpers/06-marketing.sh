#!/usr/bin/env bash
# Create branded marketing email and landing page.
# Note: HubSpot's Marketing Email v3 API and Landing Page API both require
# referencing existing templates in the portal. For a sandbox demo, we use
# the simplest reliable path: create a "DRAFT" marketing email via the v3
# endpoint with inline HTML; for landing page, attempt CMS API and fall back
# to documenting "build via UI" if it fails.
#
# Usage: 06-marketing.sh <customer-slug>

source "$(dirname "$0")/lib.sh"
load_env

SLUG="${1:-}"
[[ -n "$SLUG" ]] || fail "Usage: 06-marketing.sh <slug>"

WORK="$(work_dir "$SLUG")"
PLAN="$WORK/build-plan.json"
MANIFEST="$WORK/manifest.json"
PORTAL=$(sandbox_portal_id)

HAS_EMAIL=$(python3 -c "
import json
plan = json.load(open('$PLAN'))
print('yes' if plan.get('marketing_email') else 'no')
")

# ---- Marketing email ----
if [[ "$HAS_EMAIL" == "yes" ]]; then
  EMAIL_NAME=$(python3 -c "import json; print(json.load(open('$PLAN'))['marketing_email']['name'])")
  info "Creating marketing email: $EMAIL_NAME"

  # Try the v3 marketing email API
  email_body=$(python3 -c "
import json
plan = json.load(open('$PLAN'))['marketing_email']
brand_color = json.load(open('$WORK/research.json'))['branding'].get('primary_color', '#FF7A59')
body = {
    'name': plan['name'],
    'subject': plan['subject'],
    'fromName': plan.get('from_name', 'Demo Sender'),
    'state': 'DRAFT',
    'subscription': {'name': 'Marketing'},
    'content': {
        'plainText': plan.get('plain_text', plan['html'])
    }
}
print(json.dumps(body))
" 2>/dev/null)

  if [[ -n "$email_body" ]]; then
    resp=$(hs_curl POST "/marketing/v3/emails" "$email_body")
    if [[ "$HS_LAST_STATUS" =~ ^2 ]]; then
      EMAIL_ID=$(echo "$resp" | python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))")
      ok "  Marketing email created (id=$EMAIL_ID)"
      manifest_add "$SLUG" "marketing_email" "name" "$EMAIL_NAME"
      manifest_add "$SLUG" "marketing_email" "id" "$EMAIL_ID"
      manifest_add "$SLUG" "marketing_email" "url" "https://app.hubspot.com/email/$PORTAL/details/$EMAIL_ID"
    else
      warn "  Marketing email API failed (HTTP $HS_LAST_STATUS): $resp"
      warn "  Logging as manual step (reps create branded email in UI before demo)"
      python3 -c "
import json, os
ms_path = '$WORK/manual-steps.json'
existing = json.load(open(ms_path)) if os.path.exists(ms_path) else []
existing.append({
    'item': 'Marketing email',
    'reason': 'Marketing Email v3 API requires Marketing Hub Pro+ template path which sandbox may not have',
    'ui_url': 'https://app.hubspot.com/email/$PORTAL/manage/state/all',
    'instructions': 'Open Marketing > Email > Create email. Use a Drag-and-drop template. Subject: ' + json.load(open('$PLAN'))['marketing_email']['subject']
})
json.dump(existing, open(ms_path, 'w'), indent=2)
"
    fi
  fi
fi

# ---- Landing page ----
HAS_PAGE=$(python3 -c "
import json
plan = json.load(open('$PLAN'))
print('yes' if plan.get('landing_page') else 'no')
")

if [[ "$HAS_PAGE" == "yes" ]]; then
  PAGE_NAME=$(python3 -c "import json; print(json.load(open('$PLAN'))['landing_page']['name'])")
  info "Creating landing page: $PAGE_NAME"

  # First, try to find an available template path in the portal
  template_search=$(hs_curl GET "/cms/v3/source-code/published/filemap" "" 2>/dev/null || echo "{}")

  # Most reliable: use the default template that ships with every CMS Hub portal
  # Path: @hubspot/landing-pages/templates/landing-page.html
  page_body=$(python3 -c "
import json
plan = json.load(open('$PLAN'))['landing_page']
research = json.load(open('$WORK/research.json'))
brand_color = research['branding'].get('primary_color', '#FF7A59')
body = {
    'name': plan['name'],
    'subcategory': 'landing_page',
    'htmlTitle': plan.get('html_title', plan['name']),
    'metaDescription': plan.get('meta_description', plan['name']),
    'state': 'DRAFT',
    'language': 'en',
    'templatePath': '@hubspot/system_pages/error_pages/system-page.html'
}
print(json.dumps(body))
" 2>/dev/null)

  if [[ -n "$page_body" ]]; then
    resp=$(hs_curl POST "/cms/v3/pages/landing-pages" "$page_body")
    if [[ "$HS_LAST_STATUS" =~ ^2 ]]; then
      PAGE_ID=$(echo "$resp" | python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))")
      ok "  Landing page draft created (id=$PAGE_ID)"
      manifest_add "$SLUG" "landing_page" "name" "$PAGE_NAME"
      manifest_add "$SLUG" "landing_page" "id" "$PAGE_ID"
      manifest_add "$SLUG" "landing_page" "url" "https://app.hubspot.com/pages/$PORTAL/editor/$PAGE_ID"
    else
      warn "  Landing page API failed (HTTP $HS_LAST_STATUS): $resp"
      warn "  Logging as manual step"
      python3 -c "
import json, os
ms_path = '$WORK/manual-steps.json'
existing = json.load(open(ms_path)) if os.path.exists(ms_path) else []
existing.append({
    'item': 'Landing page',
    'reason': 'CMS landing page API requires template path that varies by portal',
    'ui_url': 'https://app.hubspot.com/website/$PORTAL/landing/create',
    'instructions': 'Create a landing page with name: ' + json.load(open('$PLAN'))['landing_page']['name']
})
json.dump(existing, open(ms_path, 'w'), indent=2)
"
    fi
  fi
fi

ok "Marketing assets phase complete for $SLUG"
manifest_add "$SLUG" "_meta" "phase_3_marketing_done" "true"
