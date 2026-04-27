# HubSpot Demo Prep — Verified Setup Procedure

This is the canonical, validated-end-to-end sequence the wizard follows. Every gotcha encountered during the original build is documented here so subsequent users skip the same trial-and-error. Portal IDs cited below (e.g. `20708362`, `51393541`) are illustrative examples from the original development environment — the wizard reads your own portal IDs from `state/config.json` after the first run; nothing is hardcoded to the original portal.

## Prerequisites — automatically detected, never asked

The wizard probes for these before asking the user anything. Only flags missing items.

| Tool | Probe command | Install path if missing |
|------|---------------|-------------------------|
| `hs` CLI v8+ | `hs --version` | `npm install -g @hubspot/cli` |
| Node + npx | `npx --version` | Bundled with Node |
| Playwright | `npx playwright --version` | `npx playwright install chromium` |
| `~/.claude/api-keys.env` | `ls ~/.claude/api-keys.env` | Wizard creates if missing |
| `~/.claude/bin/firecrawl` (wrapper) | `ls ~/.claude/bin/firecrawl` | Optional, prompt user |
| `~/.claude/bin/perplexity` (wrapper) | `ls ~/.claude/bin/perplexity` | Optional, prompt user |
| Drive MCP | introspect `mcp` tool list for `create_file` | Optional, prompt user |

## Step 1 — Capture parent Hub ID (the only mandatory question)

```
WIZARD: "What's the Hub ID of the HubSpot account you'd like to use?
         (Find it at app.hubspot.com → top-right portal switcher → Account ID)"
```

Save as `${PARENT_HUB_ID}`. All subsequent links use this.

## Step 2 — Mode selection

```
WIZARD: "Setup choice:
  A) Drive Chrome and click through HubSpot for you (slowest, full hands-off)
  B) Hand you direct links to click yourself (fastest if you're logged in)
  C) Mix — links for fast steps, Playwright for the slow ones (default)"
```

Save as `${WIZARD_MODE}`.

## Step 3 — Verify Enterprise tier (programmatic, never asked)

Required input: a Private App access token in `${PARENT_HUB_ID}` (collected in Step 4).

Check: `GET https://api.hubapi.com/crm/v3/schemas` with `Authorization: Bearer <token>`.
- 200 → Enterprise gate confirmed (custom-object schemas API is Enterprise-only)
- 403 / specific error → halt with: "This skill requires HubSpot Enterprise on at least one hub. Detected portal does not have it. Skill cannot proceed."

**Do NOT use `/account-info/v3/details`** — it only returns `accountType` (STANDARD vs SANDBOX), not subscription tier. Verified incorrect approach 2026-04-25.

## Step 4 — Private App access token in parent portal

Used for direct REST API calls (long-lived).

**Direct link:** `https://app.hubspot.com/private-apps/${PARENT_HUB_ID}`

Wizard tells user:
1. Click the link
2. Click "Create private app"
3. Name: "Demo Prep Skill"
4. On the Scopes tab, paste this list into the search box (one at a time): `account-info.security.read`, `behavioral_events.event_definitions.read_write`, `crm.lists.read`, `crm.lists.write`, `crm.objects.companies.read`, `crm.objects.companies.write`, `crm.objects.contacts.read`, `crm.objects.contacts.write`, `crm.objects.custom.read`, `crm.objects.custom.write`, `crm.objects.deals.read`, `crm.objects.deals.write`, `crm.objects.line_items.read`, `crm.objects.line_items.write`, `crm.objects.marketing_events.read`, `crm.objects.marketing_events.write`, `crm.objects.quotes.read`, `crm.objects.quotes.write`, `crm.schemas.custom.read`, `crm.schemas.custom.write`, `crm.schemas.deals.read`, `crm.schemas.deals.write`, `content`, `files`, `forms`, `tickets`, `crm.objects.leads.read`, `crm.objects.leads.write`, `crm.objects.invoices.read`, `crm.objects.invoices.write`, `marketing.campaigns.read`, `marketing.campaigns.write`, `analytics.behavioral_events.send`, `automation`
5. Create app, copy access token (`pat-na1-...`)
6. Paste back to wizard

Wizard saves to `~/.claude/api-keys.env` as `HUBSPOT_${SLUG}_TOKEN`.

If `${WIZARD_MODE}` is A or C, this whole flow can be Playwright-automated end-to-end (navigate, fill name, search-and-check-each scope, click create, capture token).

## Step 5 — Personal Access Key for `hs` CLI auth

Used for `hs sandbox create`, `hs upload`, etc. Different credential from Step 4.

**Direct link:** `https://app.hubspot.com/personal-access-key/${PARENT_HUB_ID}`

Wizard:
1. Click link
2. "View personal access key" or "Generate"
3. Copy the value (looks like `CiRu...` base64-style)
4. Paste back

Wizard saves to `~/.claude/api-keys.env` as `HUBSPOT_${SLUG}_PAK`.

## Step 6 — Add parent portal to `hs` CLI config

**Verified working command** (do NOT pass `--account`; the CLI errors out because the account doesn't exist yet):

```bash
hs account auth --pak="$PAK"
```

This triggers an interactive prompt: "Enter a unique name to reference this account in the CLI". The wizard pipes the desired name into stdin (or sets it via expect-style automation). If the prompt is dismissed, the CLI silently writes the account WITHOUT a `name:` field — the wizard must then patch `~/.hscli/config.yml` to add `name: <slug>` to the new account block.

Verify with `hs accounts list`.

## Step 7 — Create the Standard Sandbox

```bash
hs sandbox create --name=DemoPrep --type=standard --account=${PARENT_HUB_ID} --force
```

The `--force` flag skips confirmation prompts. Output includes the new sandbox Hub ID. The CLI auto-adds the sandbox to `~/.hscli/config.yml` with auth pre-populated — no second auth step needed.

**Capture the sandbox Hub ID** from the output: `Successfully created a standard sandbox <Name> with portalId <SANDBOX_HUB_ID>.`

Save as `${SANDBOX_HUB_ID}` in `~/.claude/api-keys.env`.

## Step 8 — Switch CLI default to sandbox

```bash
hs accounts use ${SANDBOX_HUB_ID}
```

All subsequent `hs` commands default to sandbox. Verify: `hs accounts info` shows sandbox.

## Step 9 — Generate Private App in the SANDBOX (long-lived API token)

The sandbox auto-generates a short-lived (~1 hour) access token via the CLI auth. For direct REST API calls from the skill, generate a long-lived Private App token inside the sandbox.

**Direct link:** `https://app.hubspot.com/private-apps/${SANDBOX_HUB_ID}`

Same scope list as Step 4. Save token as `HUBSPOT_SANDBOX_${SLUG}_TOKEN`.

(Alternative: rely on `hs` CLI's auto-refresh of access tokens by always calling through the CLI rather than direct curl. Trade-off: less convenient for API-heavy scripts.)

## Step 10 — Optional dependencies (each prompts y/n)

- **Firecrawl** for site scraping (logo + brand colors). Wizard checks for `~/.claude/bin/firecrawl` and `FIRECRAWL_API_KEY` in api-keys.env. If missing, links to https://www.firecrawl.dev/account/api-keys.
- **Perplexity** for industry research and stats. Same pattern, key at https://www.perplexity.ai/settings/api.
- **Recraft** (already MCP-installed in this environment). Used for branded marketing image generation.
- **Drive MCP** for Google Doc output. Probe via `mcp__*__create_file`. If missing, link to setup docs.

Wizard asks once, marks each as enabled/disabled in `state/config.json`, and the skill gracefully degrades if any are missing (e.g., Doc output falls back to local markdown if Drive MCP unavailable).

## Step 11 — Confirmation and persist

Print a one-paragraph summary:
```
Sandbox: DemoPrep (Hub ID 51393541)
Parent portal: 300 Tech Solutions (Hub ID 20708362)
API access: Private App token (long-lived) ✓
CLI access: PAK ✓
Optional: Firecrawl ✓ Perplexity ✓ Recraft ✓ Drive MCP ✓
Defaults: full activity, custom events fired, sandbox cleanup prompt every run
Edit `~/.claude/skills/hubspot-demo-prep/state/config.json` to change.
```

Subsequent invocations: smoke-test all of Step 3-10's connections (~5s) before proceeding. If any fail, jump back to the relevant step.

## Verified gotchas worth never repeating

1. `hs account auth --account=<id> --pak=<key>` fails on first add with `HubSpotConfigError: No account with id X exists in config`. The CLI tries to look up the account in usage tracking BEFORE running the auth handler, hitting a chicken-and-egg. Workaround: omit `--account`, let CLI derive from PAK, then patch `name:` field post-auth.
2. `hs auth` (without "accounts" or "account") errors with: "You are using our new global configuration ... use `hs account auth` instead." The aliases are misleading.
3. `/account-info/v3/details` returns `accountType: STANDARD` for a regular production portal — STANDARD here means "not a sandbox/test/developer," NOT "Standard tier." For tier verification use the custom-objects schema endpoint.
4. The Drive MCP `create_file` with `text/plain` does NOT auto-render markdown. Use `text/html` to get formatted Google Docs (or use Docs `batchUpdate` for explicit structure).
5. New sandboxes ship pre-seeded with two HubSpot sample contacts (Maria Johnson, Brian Halligan). The cleanup script should leave these alone (they're HubSpot-defaults, identifiable by their contact source / email domain).
6. Sandbox CLI access tokens expire ~1 hour. The `hs` CLI auto-refreshes on use, but direct curl calls need either a Private App token (long-lived, requires manual generation in the sandbox) or a refresh dance. Skill defaults to Private App token.


## Playwright UI phases

Some HubSpot setup is awkward (or impossible) via REST API. Those flows live
in `playwright_phases.py` and `playwright_phases_extras.py` next to
`builder.py`. They are driven by `Builder.run_playwright_phases()` after the
API build completes and run inside a single `PlaywrightSession` so login
state persists across flows.

### v2-extras flows (added 2026-04-26)

#### `create_starter_dashboard(slug, customer_name)`

Builds a "{CustomerName} Daily Snapshot" dashboard the prospect would actually
look at over morning coffee. Adds 4-6 cards (deal pipeline by stage on the
prospect's custom pipeline, tickets by status last 30 days, contacts created
last 90 days, marketing email opens/clicks, NPS distribution if data exists,
and a `{customer}_{key_action}_event` custom event volume card — for example
`shipperz_quote_requested` for a logistics prospect, `boomer_install_booked`
for a marine audio installer, `acme_trial_started` for a B2B SaaS). The
custom-object name shown elsewhere in this doc (e.g., `shipmentsobject`) is
likewise just one example — the actual object name should reflect the
prospect's domain (`installations`, `service_visits`, `workspaces`, etc.).
Prefers HubSpot's report library where possible. Stores `dashboard_id` and
`dashboard_url` in `manifest.json`. Longest UI flow in the build (~2 minutes).

#### `create_saved_views(slug)`

Creates three private saved views — fast (~30s each):

- **Contacts: Hot Leads** — `demo_lead_score >= 50`, sorted by score desc.
- **Deals: Open Quotes** — prospect's custom pipeline, stage in the
  prospect's equivalent of `(Quote Requested, Quote Sent, Negotiating)`
  (stage names should match the actual sales motion — for a service
  business that may be `(Estimate Sent, Site Visit Booked)`; for B2B SaaS
  `(Demo Done, POC Active, Procurement)`), sorted by amount desc.
- **Tickets: Needs Reply** — `hs_pipeline_stage` in `(New, Waiting on contact)`,
  sorted by createdate asc.

Stores `{key: {id, url, name, object}}` under `manifest['saved_views']`.

### Failure mode

Both flows are wrapped in step-level try/except. Every failure writes a
screenshot to `{work_dir}/screenshots/fail-*.png` and appends a `manual_step`
entry to the manifest with a deep link and instructions, so the user can
finish the step by hand. The build never crashes on a Playwright failure.

### Selectors flagged for live testing

The v2-extras flows were authored without a live HubSpot session. Confirm and
update these selectors during the next test run if any flow logs a
manual_step:

- `Create dashboard` button label (could be `Create new dashboard`)
- `Sales overview` template tile label
- Report-library entry point (`Add report` vs `Add card`)
- Filter panel button label (`Advanced filters` vs `Add filter`)
- `Save view as` button location (HubSpot has shipped multiple variants)
# setup-procedure.md — addendum

Append the following section to
`~/.claude/skills/hubspot-demo-prep/references/setup-procedure.md`.

---

## Step N — Playwright UI phases (one-time interactive login)

Five HubSpot features have no public API and must be driven through the UI:
portal branding, workflows, quote templates, sales sequences, and SEO scans.
We use Python Playwright with a saved storage-state file so login happens
once per portal-per-slug.

### N.1 — Install Python playwright (one-time per machine)

```bash
pip install playwright
playwright install chromium
```

The skill detects the install at runtime; if missing, all 5 UI flows are
logged as `manual_step` in the manifest and the build continues.

### N.2 — First-run interactive login

```bash
python3 ~/.claude/skills/hubspot-demo-prep/builder.py <slug> --playwright --first-run
```

Behavior:
1. The API phases run as usual.
2. Playwright then launches a **headed** Chromium window pointed at
   `https://app.hubspot.com/login`.
3. You sign in interactively (Google OAuth or password — HubSpot has no
   M2M login for the UI).
4. Once Playwright detects you've landed on a portal URL containing the
   sandbox Hub ID (51393541), it saves the session to
   `~/.claude/skills/hubspot-demo-prep/state/<slug>-hubspot.json`.
5. The 5 UI flows then run in the same already-authenticated session.

This file contains session cookies — it's **per-portal-per-slug** and is
gitignored. If the file leaks, it's equivalent to a logged-in HubSpot tab.

### N.3 — Subsequent runs (headless replay)

```bash
python3 ~/.claude/skills/hubspot-demo-prep/builder.py <slug> --playwright
```

Behavior:
- Headless Chromium loads the saved storage state.
- All 5 flows run without user interaction.
- Each flow has a 30-second timeout per click. If a selector fails, the
  flow logs a screenshot to `/tmp/demo-prep-<slug>/playwright/<flow>.png`
  and adds a `manual_step` entry — the build keeps going.
- New IDs (quote template id, sequence id) get persisted to
  `~/.claude/api-keys.env` as
  `HUBSPOT_DEMOPREP_<SLUG>_QUOTE_TEMPLATE_ID` and
  `HUBSPOT_DEMOPREP_<SLUG>_SEQUENCE_ID` so the API phases can reuse them
  on the next run.

### N.4 — Re-authentication

HubSpot session cookies typically last weeks but can expire after long
gaps. If a headless run fails on the very first navigation (i.e. it ends
up on the login page), simply re-run with `--first-run` to refresh the
storage state.

### N.5 — Selector resilience

All flows use **text/role-based** selectors via `page.get_by_text()` and
`page.get_by_role()` — HubSpot's CSS classes change weekly. If HubSpot
renames a button (e.g. "Create workflow" → "New workflow"), update the
regex in `playwright_phases.py` for that flow and re-run. The `_safe_flow`
wrapper guarantees that one broken flow doesn't break the others.

### N.6 — Selectors that are GUESSED vs CONFIRMED

The first time you run `--first-run`, the headed window lets you visually
confirm whether each flow's selectors hit. The following selectors were
chosen from HubSpot UI documentation and screenshots but have NOT been
exercised end-to-end against the live UI in this build:

- `upload_portal_branding`: "Upload logo" / "Primary color" / "Save"
- `create_workflow` (both types): "Create workflow", "Contact-based",
  "Set up triggers", "Add action", "Send email", "Delay"
- `create_quote_template`: "Create new template", "Modern" / "Classic",
  "Upload logo", "Primary color"
- `create_sales_sequence`: "Create sequence", "Outbound prospecting",
  "Subject"
- `kick_off_seo_scan`: "Add topic" / "Get audit"

If any of these break, screenshots in `/tmp/demo-prep-<slug>/playwright/`
will show exactly where the flow was when it failed.
