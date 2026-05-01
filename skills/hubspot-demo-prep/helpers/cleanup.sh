#!/usr/bin/env bash
# Wipe every demo asset tagged with the given customer slug.
# Usage: cleanup.sh --slug=<customer-slug> [--dry-run]
#
# Sample HubSpot contacts (Maria Johnson, Brian Halligan) are preserved.
# Custom object schemas / event definitions / property definitions are kept
# (they're shared infrastructure; only INSTANCES tagged with the slug get wiped).

source "$(dirname "$0")/lib.sh"
load_env

SLUG=""
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --slug=*) SLUG="${arg#*=}" ;;
    --dry-run) DRY_RUN=true ;;
    *) fail "Unknown arg: $arg. Usage: cleanup.sh --slug=<slug> [--dry-run]" ;;
  esac
done

[[ -n "$SLUG" ]] || fail "Pass --slug=<customer-slug>"

info "Cleaning up demo assets tagged demo_customer=$SLUG (dry-run=$DRY_RUN)"

# The Python builder owns the full v0.4 manifest-aware cleanup path (quotes,
# invoices, line items, leads, campaign, custom object records/schema, calc
# property/group). Keep the shell path below for dry-run visibility; real
# cleanup delegates so this helper does not lag the builder contract again.
if [[ "$DRY_RUN" != "true" ]]; then
  python3 "$(dirname "$0")/../builder.py" cleanup "$SLUG"
  ok "Cleanup pass complete for slug=$SLUG"
  echo ""
  warn "Not deleted automatically:"
  warn "  - v0.4 reports/dashboards (HubSpot has no public delete API; remove from Reports UI if created)"
  warn "  - Custom event definitions and shared demo properties (sandbox-wide)"
  warn "  - Workflows / forms / marketing emails / landing pages that are UI-only or shared"
  warn "  - Sample HubSpot contacts (Maria Johnson, Brian Halligan) — by design"
  exit 0
fi

# Search for tagged objects across all standard CRM types
find_and_delete() {
  local object_path="$1" object_label="$2"
  local search_body
  search_body=$(cat <<JSON
{
  "filterGroups": [{
    "filters": [{"propertyName": "demo_customer", "operator": "EQ", "value": "$SLUG"}]
  }],
  "limit": 100
}
JSON
)
  local resp
  resp=$(hs_curl POST "/crm/v3/objects/$object_path/search" "$search_body")
  # v0.3.1 fix: HS_LAST_STATUS doesn't propagate from $(...) subshell to parent.
  # lib.sh writes the status to /tmp/hs_last_status; read it back here.
  local last_status
  last_status=$(cat /tmp/hs_last_status 2>/dev/null || echo "")
  if [[ "$last_status" != "200" ]]; then
    warn "Search failed for $object_label (HTTP $last_status); skipping. Note: demo_customer property may not exist for this object type yet."
    return
  fi

  local count
  count=$(echo "$resp" | python3 -c "import json, sys; print(len(json.load(sys.stdin).get('results', [])))" 2>/dev/null || echo 0)
  if [[ "$count" == "0" ]]; then
    info "  $object_label: 0 found"
    return
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    info "  $object_label: would delete $count"
    return
  fi

  echo "$resp" | python3 -c "
import json, sys
for r in json.load(sys.stdin).get('results', []):
    print(r['id'])
" | while read -r id; do
    [[ -z "$id" ]] && continue
    hs_curl DELETE "/crm/v3/objects/$object_path/$id" >/dev/null
    # Same subshell-propagation issue as above.
    local del_status
    del_status=$(cat /tmp/hs_last_status 2>/dev/null || echo "")
    if [[ "$del_status" =~ ^2 ]]; then
      ok "    deleted $object_label $id"
    else
      warn "    failed to delete $object_label $id (HTTP $del_status)"
    fi
  done
}

find_and_delete "contacts" "contacts"
find_and_delete "companies" "companies"
find_and_delete "deals" "deals"
find_and_delete "tickets" "tickets"
find_and_delete "notes" "notes"
find_and_delete "tasks" "tasks"
find_and_delete "calls" "calls"
find_and_delete "meetings" "meetings"
find_and_delete "emails" "engagement-emails"

ok "Cleanup pass complete for slug=$SLUG"
echo ""
warn "Not deleted (kept for re-use across runs):"
warn "  - Custom object schemas (sandbox-wide)"
warn "  - Custom event definitions (sandbox-wide)"
warn "  - Custom property definitions like demo_lead_score (sandbox-wide)"
warn "  - Workflows / forms / marketing emails / landing pages (delete via UI if needed)"
warn "  - Sample HubSpot contacts (Maria Johnson, Brian Halligan) — by design"
