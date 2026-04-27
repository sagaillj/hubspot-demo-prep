#!/usr/bin/env bash
# Setup wizard. Detects what's missing and walks user through setup.
# On subsequent runs, does a 5-second smoke test of all connections.
#
# Usage: 00-wizard.sh [--reset]

source "$(dirname "$0")/lib.sh"

STATE_DIR="$(state_dir)"
CONFIG="$STATE_DIR/config.json"

if [[ "${1:-}" == "--reset" ]]; then
  rm -f "$CONFIG"
  warn "Wizard state reset. Will re-run full setup."
fi

echo ""
echo "============================================="
echo "  HubSpot Demo Prep — Setup Wizard"
echo "============================================="
echo ""

# ---- Smoke test mode (subsequent runs) ----
if [[ -f "$CONFIG" ]]; then
  info "Existing config found at $CONFIG. Running smoke tests..."
  load_env

  PARENT=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('parent_hub_id', ''))")
  SANDBOX=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('sandbox_hub_id', ''))")

  fails=0

  # Test 1: HubSpot API token
  if [[ -n "${HUBSPOT_DEMOPREP_SANDBOX_TOKEN:-${HUBSPOT_DEMOPREP_SANDBOX_PAK:-}}" ]]; then
    resp_status=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" \
      -H "Authorization: Bearer $(sandbox_token)" \
      "https://api.hubapi.com/crm/v3/schemas")
    if [[ "$resp_status" == "200" ]]; then
      ok "  HubSpot API + Enterprise tier"
    else
      err "  HubSpot API failed (HTTP $resp_status)"; fails=$((fails+1))
    fi
  else
    err "  No sandbox token in env"; fails=$((fails+1))
  fi

  # Test 2: hs CLI
  if hs accounts list 2>&1 | grep -q "$SANDBOX"; then
    ok "  hs CLI authed to sandbox"
  else
    warn "  hs CLI may not be authed to sandbox $SANDBOX"
  fi

  # Test 3: Optional tools
  command -v ~/.claude/bin/firecrawl >/dev/null && ok "  Firecrawl available" || warn "  Firecrawl not available (optional)"
  command -v ~/.claude/bin/perplexity >/dev/null && ok "  Perplexity available" || warn "  Perplexity not available (optional)"
  npx playwright --version >/dev/null 2>&1 && ok "  Playwright available" || warn "  Playwright not available (optional)"

  if [[ $fails -gt 0 ]]; then
    err "Smoke test failed. Re-run wizard with --reset to redo setup."
    exit 1
  fi

  ok "All smoke tests passed. Skill is ready."
  echo ""
  python3 -c "
import json
c = json.load(open('$CONFIG'))
print('  Parent portal:', c.get('parent_hub_id'))
print('  Sandbox portal:', c.get('sandbox_hub_id'))
print('  Activity level:', c.get('activity_level', 'full'))
print('  Drive folder:', c.get('drive_folder_id', '(root)'))
print()
print('Edit', '$CONFIG', 'to change defaults.')
"
  exit 0
fi

# ---- First-run wizard ----
info "First-time setup. This takes ~5 minutes."
echo ""

# Ensure api-keys.env exists
mkdir -p "$(dirname "$HOME/.claude/api-keys.env")"
touch "$HOME/.claude/api-keys.env"
chmod 600 "$HOME/.claude/api-keys.env"

# Step 1: Hub ID
echo "Step 1 of 7: HubSpot Account"
echo "----------------------------"
echo "What's the Hub ID of the HubSpot Enterprise portal you'd like to use?"
echo "Find it at app.hubspot.com → top-right portal switcher → Account ID"
echo ""
read -rp "Parent Hub ID: " PARENT_HUB_ID
[[ -n "$PARENT_HUB_ID" ]] || fail "Hub ID required"
[[ "$PARENT_HUB_ID" =~ ^[0-9]+$ ]] || fail "Hub ID should be numeric"
echo ""

# Step 2: Setup mode
echo "Step 2 of 7: Setup Mode"
echo "-----------------------"
echo "  A) Drive Chrome and click through HubSpot for you (Playwright)"
echo "  B) Hand you direct links to click yourself (faster if logged in)"
echo "  C) Mix — links for fast steps, Playwright for slow ones"
echo ""
read -rp "Choice [A/B/C, default C]: " WIZARD_MODE
WIZARD_MODE="${WIZARD_MODE:-C}"
echo ""

# Step 3: Private App token
echo "Step 3 of 7: Private App access token"
echo "-------------------------------------"
echo "Open: https://app.hubspot.com/private-apps/$PARENT_HUB_ID"
echo "1. Click 'Create private app'"
echo "2. Name: 'Demo Prep Skill'"
echo "3. On Scopes tab, paste this list (one at a time in the search box):"
grep -E 'paste this list into the search box' "$(skill_home)/references/setup-procedure.md" | grep -oE '`[^`]+`' | tr -d '`'
echo "4. Click 'Create app', then copy the access token (starts with 'pat-na1-...')"
echo ""
read -rsp "Paste access token: " PARENT_TOKEN
echo ""
[[ -n "$PARENT_TOKEN" ]] || fail "Token required"

# Save it
SLUG="$(echo "$PARENT_HUB_ID" | head -c 12)"
TOKEN_VAR="HUBSPOT_${PARENT_HUB_ID}_TOKEN"
if grep -q "^${TOKEN_VAR}=" ~/.claude/api-keys.env; then
  /usr/bin/sed -i.bak "s|^${TOKEN_VAR}=.*|${TOKEN_VAR}=${PARENT_TOKEN}|" ~/.claude/api-keys.env && rm ~/.claude/api-keys.env.bak
else
  echo "${TOKEN_VAR}=${PARENT_TOKEN}" >> ~/.claude/api-keys.env
fi

# Verify Enterprise tier
status=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $PARENT_TOKEN" \
  "https://api.hubapi.com/crm/v3/schemas")
if [[ "$status" != "200" ]]; then
  err "Enterprise tier check failed (HTTP $status)"
  err "This skill requires HubSpot Enterprise on at least one hub. Halting."
  exit 1
fi
ok "Enterprise tier confirmed"
echo ""

# Step 4: Personal Access Key
echo "Step 4 of 7: Personal Access Key (for hs CLI)"
echo "---------------------------------------------"
echo "Open: https://app.hubspot.com/personal-access-key/$PARENT_HUB_ID"
echo "Click 'Generate personal access key' or 'Show personal access key', then copy it."
echo ""
read -rsp "Paste PAK: " PARENT_PAK
echo ""
[[ -n "$PARENT_PAK" ]] || fail "PAK required"

PAK_VAR="HUBSPOT_${PARENT_HUB_ID}_PAK"
if grep -q "^${PAK_VAR}=" ~/.claude/api-keys.env; then
  /usr/bin/sed -i.bak "s|^${PAK_VAR}=.*|${PAK_VAR}=${PARENT_PAK}|" ~/.claude/api-keys.env && rm ~/.claude/api-keys.env.bak
else
  echo "${PAK_VAR}=${PARENT_PAK}" >> ~/.claude/api-keys.env
fi

# Add to hs CLI (handle the chicken-and-egg: omit --account, then patch name)
info "Adding parent portal to hs CLI..."
account_name="parent_${PARENT_HUB_ID}"
echo "$account_name" | hs account auth --pak="$PARENT_PAK" >/dev/null 2>&1 || true
# Patch in case interactive prompt was skipped
python3 - <<PYEOF
import yaml, sys
path = '$HOME/.hscli/config.yml'
with open(path) as f:
    config = yaml.safe_load(f)
for a in config.get('accounts', []):
    if a.get('accountId') == int('$PARENT_HUB_ID') and 'name' not in a:
        a['name'] = '$account_name'
        with open(path, 'w') as fw:
            yaml.safe_dump(config, fw)
        print('patched name')
        break
PYEOF
ok "hs CLI authed to parent portal"
echo ""

# Step 5: Sandbox creation
echo "Step 5 of 7: Standard Sandbox"
echo "-----------------------------"
read -rp "Spin up a Standard Sandbox? (Y/n): " SANDBOX_YN
SANDBOX_YN="${SANDBOX_YN:-Y}"

if [[ "$SANDBOX_YN" =~ ^[Yy] ]]; then
  read -rp "Sandbox name [DemoPrep]: " SANDBOX_NAME
  SANDBOX_NAME="${SANDBOX_NAME:-DemoPrep}"

  info "Creating sandbox..."
  output=$(hs sandbox create --name="$SANDBOX_NAME" --type=standard --account="$PARENT_HUB_ID" --force 2>&1)
  echo "$output"
  SANDBOX_HUB_ID=$(echo "$output" | grep -oE 'portalId [0-9]+' | grep -oE '[0-9]+')

  if [[ -n "$SANDBOX_HUB_ID" ]]; then
    ok "Sandbox created: Hub ID $SANDBOX_HUB_ID"
    echo "HUBSPOT_DEMOPREP_SANDBOX_PORTAL_ID=$SANDBOX_HUB_ID" >> ~/.claude/api-keys.env

    # Get the auto-generated PAK from hs config
    SANDBOX_PAK=$(awk -v pid="$SANDBOX_HUB_ID" '
      /accountId: '"$SANDBOX_HUB_ID"'/,/auth:/ {
        if ($1 == "personalAccessKey:") {getline; print $1; exit}
      }
    ' ~/.hscli/config.yml)
    [[ -n "$SANDBOX_PAK" ]] && echo "HUBSPOT_DEMOPREP_SANDBOX_PAK=$SANDBOX_PAK" >> ~/.claude/api-keys.env

    hs accounts use "$SANDBOX_HUB_ID" >/dev/null
    ok "Default hs account set to sandbox"

    warn "For long-lived API access, you should create a Private App INSIDE the sandbox:"
    warn "  https://app.hubspot.com/private-apps/$SANDBOX_HUB_ID"
    warn "  Use the same scope list as Step 3."
    warn "  Then save its token as HUBSPOT_DEMOPREP_SANDBOX_TOKEN in ~/.claude/api-keys.env"
    warn "  (Without it, the skill uses a short-lived hs CLI token that expires every hour.)"
  else
    err "Sandbox creation failed"
  fi
else
  warn "Skipping sandbox. Skill will write to production portal $PARENT_HUB_ID"
  warn "Cleanup will rely on demo_customer tagging to identify and remove demo data."
  SANDBOX_HUB_ID="$PARENT_HUB_ID"
fi
echo ""

# Step 6: Optional dependencies
echo "Step 6 of 7: Optional research tools"
echo "------------------------------------"
for tool in firecrawl perplexity; do
  if command -v ~/.claude/bin/$tool >/dev/null; then
    ok "  $tool: already installed"
  else
    warn "  $tool: not installed (optional)"
  fi
done
if npx playwright --version >/dev/null 2>&1; then
  ok "  Playwright: available"
else
  warn "  Playwright: not available (optional, used for screenshots)"
fi
echo ""

# Step 7: Persist config
echo "Step 7 of 7: Saving config..."
python3 -c "
import json
config = {
    'parent_hub_id': '$PARENT_HUB_ID',
    'sandbox_hub_id': '$SANDBOX_HUB_ID',
    'parent_token_var': 'HUBSPOT_${PARENT_HUB_ID}_TOKEN',
    'sandbox_pak_var': 'HUBSPOT_DEMOPREP_SANDBOX_PAK',
    'sandbox_token_var': 'HUBSPOT_DEMOPREP_SANDBOX_TOKEN',
    'wizard_mode': '$WIZARD_MODE',
    'activity_level': 'full',
    'activity_backdate_days': 120,
    'fire_custom_events': True,
    'cleanup_prompt_on_run': False
}
import os
os.makedirs('$STATE_DIR', exist_ok=True)
json.dump(config, open('$CONFIG', 'w'), indent=2)
"
ok "Config saved to $CONFIG"
echo ""
echo "============================================="
echo "  Setup complete!"
echo "============================================="
echo ""
echo "  Sandbox: $SANDBOX_HUB_ID"
echo "  Default activity level: full (notes/calls/tasks/meetings/emails/forms/page views, backdated 120 days)"
echo "  Custom events: define + fire on contacts (default on)"
echo "  Edit $CONFIG to change defaults."
echo ""
echo "Run a demo prep with:"
echo "  Skill(skill: 'hubspot-demo-prep')"
echo "or via terminal:"
echo "  bash ~/.claude/skills/hubspot-demo-prep/helpers/run.sh <company-url-or-name>"
