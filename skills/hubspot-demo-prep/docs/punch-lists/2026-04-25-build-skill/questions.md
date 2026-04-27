# Questions / Assumptions

## Assumption 1 — Enterprise tier gate uses custom-objects probe
Decided 2026-04-25. The `/account-info/v3/details` endpoint only returns `accountType` (STANDARD vs SANDBOX vs DEVELOPER_TEST_ACCOUNT) — it does NOT expose subscription tier. Using `GET /crm/v3/schemas` 200 as the proxy: if custom object schemas are accessible, the portal has at least one Enterprise hub (Marketing/Sales/Service/CMS/Operations Hub Enterprise). Verified working on portal 20708362.

## Assumption 2 — Drive MCP needs HTML, not markdown
The Drive MCP `create_file` with `text/plain` content + target mime `application/vnd.google-apps.document` does NOT render markdown. The literal `#`, `-`, `[link](url)` characters appear in the output Doc. To resolve in Phase 3:
- Option A: Build content as HTML and pass with `mimeType: text/html` (Drive auto-converts on import to GDoc).
- Option B: Create empty GDoc, then call Google Docs API `batchUpdate` with structured requests.

Option A is simpler. Validating in Phase 3 batch 5.1.

## Assumption 3 — Standard sandbox creation is one-time
HubSpot Enterprise portals get 1 standard sandbox by default. Sandbox is the persistent demo home; per-customer cleanup happens via tag-based deletion. Wizard treats sandbox creation as a first-run-only step.

## Assumption 4 — `hs` CLI auth required for sandbox creation
`hs sandbox create` needs the CLI authed to the parent portal (20708362). REST API token alone is insufficient. Wizard prompts for `hs init` or PAK paste on first run.
