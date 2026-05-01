#!/usr/bin/env bash
# Refresh HubSpot Playwright storage state for portal 51393541 (or override).
# Opens a headed Chromium, waits for interactive login (incl. 2FA), saves state,
# then closes. Usage: bash helpers/refresh-state.sh [PORTAL_ID]
set -euo pipefail
umask 077

PORTAL_ID="${1:-51393541}"
STATE_DIR="${HOME}/.claude/data/hubspot-demo-prep/state"
STATE_FILE="${STATE_DIR}/portal-${PORTAL_ID}-hubspot.json"

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

echo "Opening headed browser for portal $PORTAL_ID. Log in (handle 2FA)."
echo "Press ENTER in this terminal AFTER you see the HubSpot dashboard load."
echo "State will save to: $STATE_FILE"
echo

export HUBSPOT_DEMOPREP_PORTAL_ID="$PORTAL_ID"
export HUBSPOT_DEMOPREP_STATE_FILE="$STATE_FILE"

python3 - <<'PYEOF'
import asyncio, os, sys
from playwright.async_api import async_playwright

PORTAL = os.environ["HUBSPOT_DEMOPREP_PORTAL_ID"]
STATE_FILE = os.environ["HUBSPOT_DEMOPREP_STATE_FILE"]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(f"https://app.hubspot.com/login?loginPortalId={PORTAL}")
        print(f"\n>>> Log in to portal {PORTAL} (handle 2FA), then press ENTER here.")
        await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
        # Sanity-check: try a portal-scoped URL; abort save on redirect to login.
        await page.goto(f"https://app.hubspot.com/reports/{PORTAL}", wait_until="networkidle")
        if "/login" in page.url:
            print(f"!!! Still on login page ({page.url}). State NOT saved. Re-run.")
            await browser.close()
            sys.exit(1)
        await ctx.storage_state(path=STATE_FILE)
        os.chmod(STATE_FILE, 0o600)
        print(f"\n>>> Saved fresh storage state -> {STATE_FILE}")
        await browser.close()

asyncio.run(main())
PYEOF

if [[ -f "$STATE_FILE" ]]; then
  chmod 600 "$STATE_FILE"
fi

echo "Done. Verify with: ls -lh \"$STATE_FILE\""
