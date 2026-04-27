#!/usr/bin/env bash
# Shared library for hubspot-demo-prep helpers.
# Source this from any helper script: `source "$(dirname "$0")/lib.sh"`

set -eo pipefail
# Initialize commonly-checked vars to satisfy any nounset-strict callers
HS_LAST_STATUS="${HS_LAST_STATUS:-}"

# Color codes for log output
C_RESET=$'\033[0m'
C_DIM=$'\033[2m'
C_RED=$'\033[31m'
C_GREEN=$'\033[32m'
C_YELLOW=$'\033[33m'
C_BLUE=$'\033[34m'
C_BOLD=$'\033[1m'

# ---- Logging ----

log()   { printf '%b\n' "${C_DIM}[$(date +%H:%M:%S)]${C_RESET} $*" >&2; }
info()  { printf '%b\n' "${C_BLUE}info${C_RESET}  $*" >&2; }
ok()    { printf '%b\n' "${C_GREEN}ok${C_RESET}    $*" >&2; }
warn()  { printf '%b\n' "${C_YELLOW}warn${C_RESET}  $*" >&2; }
err()   { printf '%b\n' "${C_RED}err${C_RESET}   $*" >&2; }
fail()  { err "$*"; exit 1; }

# ---- Env / config ----

# Loads the API keys file (every helper sources this)
load_env() {
  local env_file="${HUBSPOT_DEMO_PREP_ENV:-$HOME/.claude/api-keys.env}"
  [[ -f "$env_file" ]] || fail "Missing $env_file. Run the wizard first."
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
}

# Returns the active sandbox token (long-lived Private App token).
# Falls back to short-lived hs CLI access token if Private App not set up.
sandbox_token() {
  if [[ -n "${HUBSPOT_DEMOPREP_SANDBOX_TOKEN:-}" ]]; then
    echo "$HUBSPOT_DEMOPREP_SANDBOX_TOKEN"
  elif [[ -n "${HUBSPOT_DEMOPREP_SANDBOX_PAK:-}" ]]; then
    # Use hs CLI to get a fresh access token
    awk -v pid="${HUBSPOT_DEMOPREP_SANDBOX_PORTAL_ID:-}" '
      /accountId: '"${HUBSPOT_DEMOPREP_SANDBOX_PORTAL_ID:-}"'/,/auth:/ {
        if ($1 == "personalAccessKey:") next
      }
      /accessToken:/{getline; print $1; exit}
    ' "$HOME/.hscli/config.yml"
  else
    fail "No sandbox token available. Run the wizard."
  fi
}

# Returns the sandbox portal ID
sandbox_portal_id() {
  echo "${HUBSPOT_DEMOPREP_SANDBOX_PORTAL_ID:-}"
}

# Skill home (for resolving paths)
skill_home() { echo "$HOME/.claude/skills/hubspot-demo-prep"; }
state_dir()  { mkdir -p "$(skill_home)/state" && echo "$(skill_home)/state"; }
work_dir()   { local slug="$1"; mkdir -p "/tmp/demo-prep-$slug" && echo "/tmp/demo-prep-$slug"; }

# ---- HTTP helpers ----

# hs_curl <method> <path> [<json_body>]
# Hits HubSpot API with auto-auth. Returns response body. Sets HS_LAST_STATUS.
hs_curl() {
  local method="$1" path="$2" body="${3:-}"
  local token
  token=$(sandbox_token)
  local url="https://api.hubapi.com$path"
  local tmp_status tmp_body
  tmp_status=$(mktemp)
  tmp_body=$(mktemp)

  if [[ -z "$body" ]]; then
    /usr/bin/curl -sS -X "$method" \
      -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" \
      -o "$tmp_body" \
      -w '%{http_code}' \
      "$url" > "$tmp_status"
  else
    /usr/bin/curl -sS -X "$method" \
      -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" \
      --data "$body" \
      -o "$tmp_body" \
      -w '%{http_code}' \
      "$url" > "$tmp_status"
  fi

  HS_LAST_STATUS=$(cat "$tmp_status")
  # Persist status to a file so subshell callers (resp=$(hs_curl ...)) can read it
  echo "$HS_LAST_STATUS" > /tmp/hs_last_status
  cat "$tmp_body"
  rm -f "$tmp_status" "$tmp_body"
}

# Read status of the most recent hs_curl call (works across subshells)
hs_status() {
  cat /tmp/hs_last_status 2>/dev/null || echo ""
}

# Form submission helper (unauthenticated endpoint)
hs_form_submit() {
  local form_guid="$1" body="$2"
  local portal
  portal=$(sandbox_portal_id)
  /usr/bin/curl -sS -X POST \
    -H "Content-Type: application/json" \
    --data "$body" \
    "https://api.hubapi.com/submissions/v3/integration/submit/$portal/$form_guid"
}

# ---- JSON helpers ----

# Extract a field from JSON via jq. Falls back to grep if jq not available.
json_field() {
  local json="$1" field="$2"
  if command -v jq >/dev/null; then
    echo "$json" | jq -r "$field"
  else
    # Very basic fallback for `.id` style queries
    local key
    key=$(echo "$field" | sed 's/^\.//; s/[\\.\\[\\]"]//g')
    echo "$json" | /usr/bin/grep -o "\"$key\":\"[^\"]*\"" | head -1 | cut -d'"' -f4
  fi
}

# ---- Time helpers ----

# Epoch milliseconds for N days ago
backdate_ms() {
  local days="$1"
  python3 -c "import time; print(int((time.time() - $days*86400) * 1000))"
}

# ISO-8601 for N days ago
backdate_iso() {
  local days="$1"
  python3 -c "
import datetime
print((datetime.datetime.utcnow() - datetime.timedelta(days=$days)).strftime('%Y-%m-%dT%H:%M:%SZ'))
"
}

# ---- Tagging convention ----

# Every demo asset carries demo_customer property = slug
# Cleanup script searches by this property
demo_tag() { echo "${1:-unknown-customer}"; }
demo_email_domain() { echo "demo-${1:-unknown-customer}.test"; }

# ---- Manifest helpers ----

# Append a created object to the manifest for the current run
# Args: <slug> <category> <key> <value>
manifest_add() {
  local slug="$1" category="$2" key="$3" value="$4"
  local file
  file="$(work_dir "$slug")/manifest.json"
  if [[ ! -f "$file" ]]; then
    echo '{}' > "$file"
  fi
  python3 - "$file" "$category" "$key" "$value" <<'PYEOF'
import json, sys
path, category, key, value = sys.argv[1:]
with open(path) as f:
    data = json.load(f)
data.setdefault(category, {})[key] = value
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
PYEOF
}

manifest_get() {
  local slug="$1" path="$2"
  local file
  file="$(work_dir "$slug")/manifest.json"
  [[ -f "$file" ]] || { echo ""; return; }
  python3 -c "import json; print(json.load(open('$file'))$path)"
}
