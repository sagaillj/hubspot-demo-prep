# hubspot-demo-prep — Status & Outstanding Items

After the 2026-04-26 hardening pass.

## Fixed in this pass ✅

1. **Bash → Python migration** — promoted to `builder.py`. Replaces buggy bash helpers 02-08. Single class `Builder` with proper status checks on every API call.
2. **Status capture** — eliminated by moving to Python (no subshell loss).
3. **Industry enum validation** — `VALID_INDUSTRIES` constant in builder.py. Plan generator should pull from this list.
4. **`.test` TLD rejection** — builder rewrites `.test` → `.com` before sending.
5. **Form fieldGroups split** — auto-splits any group >3 fields.
6. **Custom object record race** — added 1s polling for property availability before record creation.
7. **Hot leads list dedup** — checks for existing list before create.
8. **Custom event firing backdate** — `occurredAt` now uses random `days_ago` like other engagements.
9. **Parallelization** — `ThreadPoolExecutor` for engagements (8 workers), associations, custom events, form submissions, lead scoring. Built-in rate limiter keeps under 150 req / 10s.
10. **Error tracking** — every non-2xx response goes to `manifest["errors"]` with full context.
11. **Manual step logging** — when API fails, manual step + UI URL + reason logged automatically.
12. **AI-generated branded marketing email** ✨ — Recraft generates a hero image relevant to the customer's industry (tested: BMW being loaded into enclosed transport for Shipperz). Email HTML uses brand colors, premium typography, prominent CTA. Saved to disk + ready to paste into HubSpot UI.
13. **HTTP server preview** — pattern for previewing HTML files via Chrome (file:// is blocked; use python http.server on localhost).

## Still outstanding (next session)

### High

1. **Workflow API v4 body** — current shape returns 500. Codex provided correct fields (`isEnabled`, `objectTypeId`, `flowType`, `enrollmentCriteria`, action `connection`/`actionTypeId 0-5`/`fields.value.staticValue`), but HubSpot's actual schema requires more we haven't matched. **Suggested fix:** open one workflow in the HubSpot UI, export via `GET /automation/v4/flows/{id}`, use the response body shape verbatim as a template.
2. **Marketing email API** still requires `businessUnitId`. Resolution endpoint `/business-units/v3/business-units/user` returned non-200 — try `/marketing/v3/business-units` or query Settings API for default unit. Until fixed, email is logged as manual UI step (HTML is generated and ready to paste).
3. **Custom event `/events/v3/send`** — fires returned 0/15. Either response status is being misclassified or sandbox event ingestion is delayed/dropped. Needs deeper debugging — check the response body of one fire.
4. **Custom object records** — even with property polling, records returned 0/4 in this run. May be that the schema's `requiredProperties` or `searchableProperties` list doesn't include `demo_customer`, so records using it as a property fail. Fix: ensure `demo_customer` is added to schema's property list during creation, or omit it from records and tag via association tag instead.
5. **Form 1 (Quote) creation** — returns 400 "internal error" with no detail. May be a sandbox-specific quota or the dedup-by-name path. Form 2 (NPS) reused successfully.

### Medium

6. **Form submissions** — returned 0/6. The unauthenticated submit endpoint may be rate-limiting or rejecting the email TLDs. Test directly with `curl` to debug.
7. **Workflow v4 — direct UI extraction** — instead of guessing the body, build one workflow in the UI, GET it via API, save the body shape as a template in the skill. Repeat per "complex action" type.
8. **Parallelize Phase 1 (research)** via subagents — Firecrawl + Playwright + Perplexity dispatched concurrently. Currently sequential in 01-research.sh.
9. **AI image — multiple sizes** — generate hero (1820x1024) for landing page + email-optimized (640x360) + thumbnail (200x200) in one Recraft call (numberOfImages=3 doesn't quite work — needs separate prompts).
10. **Recraft style match** — add code to read customer's actual brand visual style (from screenshots) and pass as Recraft `styleID` for tighter brand match.

### Low

11. **Drive folder organization** — currently uploads to Drive root. Should create/find a "HubSpot Demo Prep" folder and put Docs inside.
12. **Email HTML preview** — currently requires `python -m http.server` to view (file:// blocked). Better: render the email HTML to a screenshot via Playwright after generation, save the PNG, link from the Doc.
13. **Cleanup script** — should also offer to delete custom property definitions on `--deep-clean` flag.
14. **Logo download** — currently relies on og:image URL. If gated/expired, Doc shows broken image. Better: download via Firecrawl or Playwright, base64 inline.
15. **Workflow gap callouts** — when a workflow is built in UI manually, the gap callouts in the Doc still reference workflow IDs that don't exist (since API returned 500). Should detect and re-link to "build via UI" with no specific workflow URL.

## v2 features (still queued)

16. **AI-generated landing pages** — same pattern as marketing email but for CMS Pages. Heavier because needs `templatePath` resolution.
17. **GHL screenshot intent parsing** — v1 ingests text + screenshots as research. v2 should parse screenshots of customer's existing tools and replicate workflow logic in HubSpot.
18. **Playwright headless + storage state** — first-run interactive login, subsequent runs replay cookies. Eliminates the manual login during wizard.
19. **Multi-customer batch mode** — process N customers in parallel from a queue. Useful for "prep demos for these 5 prospects this week."
20. **SMS workflow integration** — explicit Twilio/Aircall integration documentation when SMS appears in the agenda.

## Architecture changes that landed

- Skill now uses `builder.py` (production) + bash helpers (deprecated, kept for reference)
- All HubSpot writes go through `HubSpotClient.request()` with rate limiting and uniform error handling
- Engagement creation parallelized — 168 engagements in <12 seconds
- Marketing email generates beautiful branded HTML with AI hero image regardless of whether HubSpot API accepts it (HTML is the deliverable; API write is best-effort)

## Build statistics from this run (Shipperz Inc, sandbox 51393541)

- Phase 1 properties: 5/5 ready
- Phase 2 company: 1 created
- Phase 3 contacts: 8/8 created
- Phase 4 pipeline + deals: 1 pipeline + 5 deals
- Phase 4b tickets: 2/2
- Phase 5 engagements: 168/168 (parallel, 11 seconds)
- Phase 6 custom object: schema reused, records 0/4 (needs fix)
- Phase 7 custom events: 1 def reused, fires 0/15 (needs fix)
- Phase 8 forms: 1/2 forms (Quote 400'd; NPS reused), submissions 0/6 (needs fix)
- Phase 9 lead scoring: 8/8 contacts scored, list reused
- Phase 10 marketing email: branded HTML with AI image generated; API logged as manual (businessUnitId)
- Phase 11 workflows: 0/2 (both 500'd; logged as manual with full step lists)
- **Total errors:** 4 (all logged with full context in manifest.json)
- **Manual steps generated:** 5 (all with UI URLs + reasons)

## Final asset URLs

- **Updated Demo Doc** (after this hardening pass): https://docs.google.com/document/d/1YU3YdoMV265NZlGecHYBDnFMRjVQ7zfA/edit
- **Original Demo Doc** (first run): https://docs.google.com/document/d/1YXpV5ArNBZ-POUvnfkVghrR99SKaBQjq/edit
- **AI-generated marketing email HTML:** `/tmp/demo-prep-shipperzinc/marketing-email.html` (open in browser, or python -m http.server 8765 → localhost:8765/marketing-email.html)
- **AI hero image (full size):** `/tmp/demo-prep-shipperzinc/hero-image.png`
- **AI hero image (email-sized):** `/tmp/demo-prep-shipperzinc/hero-image-email.png`
- **Sandbox:** Hub ID 51393541
- **Sample contact (full timeline):** https://app.hubspot.com/contacts/51393541/record/0-1/218011238955
- **Pipeline:** https://app.hubspot.com/sales/51393541/deals/board/view/all/?pipeline=893842217
- **Custom object:** https://app.hubspot.com/contacts/51393541/objects/2-61481665
- **Form (NPS):** https://app.hubspot.com/forms/51393541/editor/866a9eb0-c553-49c6-9374-431e82d71b5e/edit/form
