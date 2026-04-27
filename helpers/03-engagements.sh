#!/usr/bin/env bash
# Generate backdated activity (notes, tasks, calls, meetings, emails) on demo contacts.
# Reads /tmp/demo-prep-<slug>/manifest.json for contact IDs.
# Reads /tmp/demo-prep-<slug>/build-plan.json for activity prompts (already-generated copy).
#
# Usage: 03-engagements.sh <customer-slug>

source "$(dirname "$0")/lib.sh"
load_env

SLUG="${1:-}"
[[ -n "$SLUG" ]] || fail "Usage: 03-engagements.sh <slug>"

WORK="$(work_dir "$SLUG")"
PLAN="$WORK/build-plan.json"
MANIFEST="$WORK/manifest.json"

info "Generating backdated activity for $SLUG"

# Get contact IDs from manifest
CONTACT_IDS=$(python3 -c "
import json
m = json.load(open('$MANIFEST'))
print(' '.join(m.get('contacts', {}).values()))
")
[[ -n "$CONTACT_IDS" ]] || fail "No contacts in manifest. Run 02-seed-crm.sh first."

# Backdate range from plan
DAYS_BACK=$(python3 -c "
import json
plan = json.load(open('$PLAN'))
print(plan.get('activity', {}).get('backdate_days', 120))
" 2>/dev/null || echo "120")

ACTIVITY_LEVEL=$(python3 -c "
import json
plan = json.load(open('$PLAN'))
print(plan.get('activity', {}).get('level', 'full'))
" 2>/dev/null || echo "full")

# Map level to per-contact engagement counts
case "$ACTIVITY_LEVEL" in
  light)  N_NOTES=1; N_TASKS=1; N_CALLS=1; N_MEETINGS=0; N_EMAILS=2 ;;
  medium) N_NOTES=3; N_TASKS=2; N_CALLS=2; N_MEETINGS=1; N_EMAILS=4 ;;
  full)   N_NOTES=5; N_TASKS=3; N_CALLS=3; N_MEETINGS=2; N_EMAILS=8 ;;
  *)      N_NOTES=3; N_TASKS=2; N_CALLS=2; N_MEETINGS=1; N_EMAILS=4 ;;
esac

# Generate engagement bodies. Use plan-supplied prompts if available, else fallback templates.
PLAN_NOTES=$(python3 -c "
import json
plan = json.load(open('$PLAN'))
notes = plan.get('activity_content', {}).get('notes', [])
print(json.dumps(notes))
" 2>/dev/null || echo "[]")

# Fallback note templates by phase of buyer journey
read -r -d '' DEFAULT_NOTES <<'EOF' || true
Initial inbound from website contact form. Asked about pricing and capabilities.
Followed up via email — they're evaluating us against two other vendors.
Discovery call — pain points: manual processes, lost leads, no visibility into pipeline.
Sent over the proposal. Decision maker on PTO this week.
Got the green light from procurement. Working through MSA red lines.
EOF

# Generate engagements per contact
for cid in $CONTACT_IDS; do
  info "  contact $cid: generating $((N_NOTES+N_TASKS+N_CALLS+N_MEETINGS+N_EMAILS)) engagements"

  # ---- Notes ----
  for i in $(seq 1 "$N_NOTES"); do
    days_ago=$((RANDOM % DAYS_BACK + 1))
    ts_ms=$(backdate_ms "$days_ago")
    note_body=$(python3 -c "
import json
notes = json.loads('''$PLAN_NOTES''')
default = '''$DEFAULT_NOTES'''.strip().split('\n')
import random
random.seed($cid + $i)
src = notes if notes else default
print(random.choice(src) if src else 'Touchpoint with prospect.')
")
    note_json=$(python3 -c "
import json
body = {
    'properties': {'hs_note_body': '''$note_body''', 'hs_timestamp': $ts_ms},
    'associations': [{'to': {'id': '$cid'}, 'types': [{'associationCategory': 'HUBSPOT_DEFINED', 'associationTypeId': 202}]}]
}
print(json.dumps(body))
")
    hs_curl POST "/crm/v3/objects/notes" "$note_json" >/dev/null
  done

  # ---- Tasks ----
  for i in $(seq 1 "$N_TASKS"); do
    days_ago=$((RANDOM % DAYS_BACK + 1))
    ts_ms=$(backdate_ms "$days_ago")
    task_subjects=("Follow up on pricing question" "Send case studies" "Schedule technical deep-dive" "Review contract" "Draft proposal" "Call to confirm next steps")
    subj="${task_subjects[$((RANDOM % ${#task_subjects[@]}))]}"
    task_json=$(python3 -c "
import json
body = {
    'properties': {
        'hs_task_subject': '$subj',
        'hs_task_status': 'COMPLETED',
        'hs_task_priority': 'MEDIUM',
        'hs_timestamp': $ts_ms
    },
    'associations': [{'to': {'id': '$cid'}, 'types': [{'associationCategory': 'HUBSPOT_DEFINED', 'associationTypeId': 204}]}]
}
print(json.dumps(body))
")
    hs_curl POST "/crm/v3/objects/tasks" "$task_json" >/dev/null
  done

  # ---- Calls ----
  for i in $(seq 1 "$N_CALLS"); do
    days_ago=$((RANDOM % DAYS_BACK + 1))
    ts_ms=$(backdate_ms "$days_ago")
    call_titles=("Discovery call" "Demo follow-up" "Pricing discussion" "Technical questions" "Decision call")
    title="${call_titles[$((RANDOM % ${#call_titles[@]}))]}"
    call_json=$(python3 -c "
import json
body = {
    'properties': {
        'hs_call_title': '$title',
        'hs_call_body': 'Productive conversation. Next steps confirmed.',
        'hs_call_duration': $((RANDOM % 1800000 + 600000)),
        'hs_call_direction': 'OUTBOUND',
        'hs_call_status': 'COMPLETED',
        'hs_timestamp': $ts_ms
    },
    'associations': [{'to': {'id': '$cid'}, 'types': [{'associationCategory': 'HUBSPOT_DEFINED', 'associationTypeId': 194}]}]
}
print(json.dumps(body))
")
    hs_curl POST "/crm/v3/objects/calls" "$call_json" >/dev/null
  done

  # ---- Meetings ----
  for i in $(seq 1 "$N_MEETINGS"); do
    days_ago=$((RANDOM % DAYS_BACK + 1))
    start_ms=$(backdate_ms "$days_ago")
    end_ms=$((start_ms + 1800000))
    meeting_titles=("Demo session" "Onboarding kickoff" "QBR" "Solutioning workshop")
    title="${meeting_titles[$((RANDOM % ${#meeting_titles[@]}))]}"
    meeting_json=$(python3 -c "
import json
body = {
    'properties': {
        'hs_meeting_title': '$title',
        'hs_meeting_body': '30-minute working session.',
        'hs_meeting_start_time': $start_ms,
        'hs_meeting_end_time': $end_ms,
        'hs_meeting_outcome': 'COMPLETED',
        'hs_timestamp': $start_ms
    },
    'associations': [{'to': {'id': '$cid'}, 'types': [{'associationCategory': 'HUBSPOT_DEFINED', 'associationTypeId': 200}]}]
}
print(json.dumps(body))
")
    hs_curl POST "/crm/v3/objects/meetings" "$meeting_json" >/dev/null
  done

  # ---- Emails (engagement records) ----
  for i in $(seq 1 "$N_EMAILS"); do
    days_ago=$((RANDOM % DAYS_BACK + 1))
    ts_ms=$(backdate_ms "$days_ago")
    email_subjects=("Re: Following up" "Quick question on the proposal" "Demo recap + next steps" "Pricing breakdown attached" "Touching base" "Implementation timeline" "Updated SOW")
    subj="${email_subjects[$((RANDOM % ${#email_subjects[@]}))]}"
    direction=$([ $((RANDOM % 2)) -eq 0 ] && echo "INCOMING_EMAIL" || echo "EMAIL")
    email_json=$(python3 -c "
import json
body = {
    'properties': {
        'hs_email_subject': '$subj',
        'hs_email_text': 'Email thread between rep and contact.',
        'hs_email_direction': '$direction',
        'hs_email_status': 'SENT',
        'hs_timestamp': $ts_ms
    },
    'associations': [{'to': {'id': '$cid'}, 'types': [{'associationCategory': 'HUBSPOT_DEFINED', 'associationTypeId': 198}]}]
}
print(json.dumps(body))
")
    hs_curl POST "/crm/v3/objects/emails" "$email_json" >/dev/null
  done
done

ok "Activity timeline generated"
manifest_add "$SLUG" "_meta" "phase_3_engagements_done" "true"
manifest_add "$SLUG" "activity" "level" "$ACTIVITY_LEVEL"
manifest_add "$SLUG" "activity" "backdate_days" "$DAYS_BACK"
