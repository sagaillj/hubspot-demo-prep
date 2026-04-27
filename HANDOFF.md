# Handoff for next session — 2026-04-26 v2 ship

Skill at `~/.claude/skills/hubspot-demo-prep/`. Production builder is `builder.py` (1896 lines). Playwright phases in `playwright_phases.py` (1013 lines) + `playwright_phases_extras.py` (711 lines). State below reflects v2 multi-agent build session.

---

## What landed in v2 ✅

### Doc generator (locked per Jeremy)
- `/tmp/demo-prep-shipperzinc/make-doc.py` produces a polished 2-page demo runbook (.docx + Drive auto-converted to GDoc).
- **Page 1 = print-ready demo runbook**: Shipperz banner header, intro paragraph (rep input + what was built), 3-item agenda each with `[BUILT]`/`[BUILD LIVE]`/`[NOT BUILT]`/`[ANALOG]` status pills + direct HubSpot links, ★ Easter Egg (lead scoring), Also Built section (5 deals individually linked, 8 contacts, custom object, events, tickets, company), Recommendation paragraph.
- **Page 2 = supporting docs**: Pre-demo checklist, Shipperz snapshot, ICP + pain-point research, Full build inventory, Known build limitations, Sources.
- Live at: https://docs.google.com/document/d/1dInOgWLKFXdOT-u3BzsxiRBMcQXK3AvxC57P7D73B2A/edit
- Drive folder: 1SzHT9uhFUUcFIAh5z2LVCAq2Wt0OADjY (anyone-with-link)

### Marketing email v2
- Live at: https://app.hubspot.com/email/51393541/edit/211744773523/edit/content
- Includes Shipperz banner header (logo on dark navy), AI-generated BMW hero image, orange `#FF6B35` brand color throughout (headline, numbered list, CTA), navy footer with Shipperz contact info.
- HTML pushed via PATCH /marketing/v3/emails. File at `/tmp/demo-prep-shipperzinc/marketing-email-v2.html`.

### v2 API phases added to `Builder` class
1. **`create_leads()`** — 8 leads in Sales Workspace queue (object 0-136). ~72 lines.
2. **`create_quotes()`** — 5 quotes per deal × 3 line items each, with branded quote template association. ~116 lines. Requires pinned `HUBSPOT_DEMOPREP_{SLUG}_QUOTE_TEMPLATE_ID` env var (created by Playwright phase).
3. **`create_invoices()`** — 2 invoices via batch endpoint (one paid backdated 30d, one open current). ~90 lines.
4. **`create_calc_property_and_group()`** — `deal_age_days` calc property + "Shipperz Demo" property group, regroups existing demo properties. ~54 lines.
5. **`create_marketing_campaign()`** — POST /marketing/v3/campaigns + PUT to associate marketing email + NPS form + contact list. ~69 lines. Defensive: 403 fallback to manual_step (campaigns scope enforced 2026-07-09).

### Playwright UI phases (no public API for these)
File: `playwright_phases.py` exposes:
- `upload_portal_branding(...)` — Settings → Branding, upload customer logo + set primary color
- `create_workflow(..., workflow_type="lead_nurture" or "nps_routing")` — Workflows → Create
- `create_quote_template(...)` — Sales → Quotes → Templates → Create with logo + brand colors
- `create_sales_sequence(...)` — Automation → Sequences → Create
- `kick_off_seo_scan(...)` — Marketing → SEO → New topic → Get audit. **Note: SEO scan takes hours on HubSpot side. Doc surfaces the URL and timestamp; rep checks before demo.**
- Plus orchestrator `run_all_phases(...)` and context manager `PlaywrightSession` (storage-state per slug at `state/{slug}-hubspot.json`).

File: `playwright_phases_extras.py` exposes:
- `create_starter_dashboard(...)` — "Shipperz Daily Snapshot" with 4-6 cards (pipeline, tickets, contacts, email opens, NPS, custom event fires)
- `create_saved_views(...)` — 3 views (Hot Leads contacts, Open Quotes deals, Tickets Needs Reply)

Wired into `Builder.run_playwright_phases(first_run=False)` at line ~1696. CLI: `python3 builder.py {slug} --playwright [--first-run]`.

**ALL Playwright selectors are GUESSED** (text/role-based, not CSS). The `_safe_flow` wrapper catches all failures, screenshots on success/failure, falls back to `manual_step` rather than crashing.

### Codex doc fixes applied
1. Drive file title: `HubSpot Demo Prep · Shipperz Inc` (was em-dashed).
2. `[NOT BUILT]` now uses `NOT_BUILT_RED` (#B91C1C) — visually distinct from `[BUILD LIVE]` amber.
3. Recommendation says "no-marketing-team setup" (was "1-marketer team", contradicted intro).

### Setup wizard fixes
- `helpers/00-wizard.sh` line 117: grep pattern was `'^- \``' which never matched the inline scope format → patched to anchor on "paste this list into the search box". v1 wizard had silently emitted zero scopes since v1 ship.
- `references/setup-procedure.md`: scopes added — `crm.objects.leads.read/write`, `crm.objects.invoices.read/write`, `marketing.campaigns.read/write`, `analytics.behavioral_events.send`. Quotes + line_items scopes were already present.
- Playwright setup section appended to `setup-procedure.md` (pip install, first-run flow, storage-state location).

---

## Opus + Codex review findings (2026-04-26 reviews)

### Opus blockers (3 highest-leverage fixes for shipping confidence)
1. **Pre-flight scope check** at builder startup. Verify `marketing.campaigns.write`, `analytics.behavioral_events.send`, `automation.sequences.enrollments.write` are on the token; fail fast with "re-auth your private app" message rather than silently degrading. ~30 line addition.
2. **Replace workflow API attempts with template-clone.** v4 flows actionTypeId `0-5` is wrong (should be `0-2` for Set Property). HANDOFF already identifies path: GET an existing UI-built workflow, save body shape as `references/workflow-template.json`, mutate per customer.
3. **Move docx-to-Drive upload into `builder.py:generate_doc()`.** Currently doc generation stops at `.docx` on disk; rep has to manually MCP-upload. The 30-min "rep gets stuck" cliff. Solution: port `/tmp/demo-prep-shipperzinc/{make-doc,update-doc,export-pdf}.py` into a new `~/.claude/skills/hubspot-demo-prep/doc_generator.py` module, replace builder.py's HTML-based `generate_doc()` (lines ~1476-1651, now dead code).

### Opus deferrals (cut for tighter ship)
- Dashboard + saved views (`playwright_phases_extras.py`, 711 lines) — selectors fully guessed against shipping HubSpot UI; cards are generic, not Shipperz-specific. Opus says cut.
- SEO scan kickoff — async, may still be "scanning" mid-demo.
- Quotes + invoices + calc properties + marketing campaign tagging — built but not surfaced in agenda doc; invisible value unless agenda references them.
- **Counterpoint:** Jeremy explicitly asked for these. Pull only with his approval.

### Other Opus risks flagged (not yet addressed)
- `builder.py:create_contacts` rewrites `.test` → `.example.com` with `demo-{slug}.` prefix (✅ FIXED in this session per RFC 2606).
- `playwright_phases_extras.py` had `import re` at file bottom — risky for cold imports (✅ FIXED, moved to top).
- `_state_path` was keyed per-slug, forcing redundant logins per prospect on the same sandbox (✅ FIXED, now keyed per portal_id with legacy migration).
- HTML-based `Builder.generate_doc()` (lines ~1476-1651) is now dead code — should be deleted in next session.
- Marketing email is in DRAFT state — rep clicking link mid-demo lands on editor, not preview. Surface preview URL specifically.

### Codex findings on this v2 codebase
(Pending — Codex review still running as of session end. Output at `/private/tmp/claude-501/-Users-jeremysagaille-Documents/.../tasks/a82053d08362598d4.output` and `afac439972c0ff35d.output`. Read on next session resume.)

---

## Known issues / caveats

1. **Playwright selectors are guessed.** First real run on a live portal will need selector updates. Risk areas flagged in `setup-procedure.md`:
   - Branding: "Upload logo" vs "Replace logo" vs "Edit logo"
   - Workflows: heavy React canvas, may need workflow-builder-specific patterns
   - Quote template: "Modern"/"Classic" template tile names
   - Sales sequence: rich-text editor (Draft.js / contenteditable) selectors fragile
   - SEO scan: tier-dependent label ("Add topic" varies by Marketing Hub tier)

2. **Marketing Campaigns scope** `marketing.campaigns.write` is enforced 2026-07-09. Builder defensively falls back to manual_step on 403. Add to wizard scope list — done.

3. **Quote template chicken-and-egg.** `create_quotes()` needs an existing template ID. Solution: `create_quote_template()` Playwright phase runs FIRST, saves ID to env, then `create_quotes()` reads it. If Playwright fails, quotes phase logs manual_step.

4. **Sequence enrollments** — Jeremy explicitly said don't bother. Skipped.

5. **Sales rep email templates, snippets, playbooks, KB articles, account-level branding settings, dashboards, reports, meeting links** — confirmed NO public API. Some now Playwright-automated (workflows, branding, quote template, sequence, dashboard, saved views, SEO scan). Others deferred (snippets, playbooks, KB).

6. **End-to-end live test not yet run.** v2 code is parsed/imported clean but the live API + Playwright flows weren't exercised against the sandbox in this session (would require interactive first-run login). Next session: clean up existing Shipperz data and re-run end-to-end with `--first-run --playwright` to validate.

---

## Runtime estimate (when end-to-end is run)

Best case (well-cached, fully parallel): ~5 min  
Typical: ~7-9 min  
First-run-per-portal (interactive auth): +30-60s once  
With one Playwright retry: ~12-15 min

---

## Top files

- `builder.py` (1896 lines, all phases)
- `playwright_phases.py` (1013 lines)
- `playwright_phases_extras.py` (711 lines)
- `references/v2-capabilities.md` (research, top-5 quick wins ranked)
- `references/v2-content-campaigns.md` (Marketing Campaigns recipe)
- `references/setup-procedure.md` (scopes + Playwright setup)
- `helpers/00-wizard.sh` (with the v1 grep bug fixed)
- `/tmp/demo-prep-shipperzinc/make-doc.py` (doc generator — should be ported into builder.py.generate_doc() in next session)

## Final asset URLs

- **Demo Doc (final):** https://docs.google.com/document/d/1dInOgWLKFXdOT-u3BzsxiRBMcQXK3AvxC57P7D73B2A/edit
- **Drive folder:** https://drive.google.com/drive/folders/1SzHT9uhFUUcFIAh5z2LVCAq2Wt0OADjY
- **Marketing email (live):** https://app.hubspot.com/email/51393541/edit/211744773523/edit/content
- **Sandbox:** https://app.hubspot.com/contacts/51393541
- **Sample contact:** https://app.hubspot.com/contacts/51393541/record/0-1/218011238955
- **Pipeline (board):** https://app.hubspot.com/contacts/51393541/objects/0-3/views/all/board?pipeline=893842217
- **Custom object (Shipments):** https://app.hubspot.com/contacts/51393541/objects/2-61481665
- **NPS form:** https://app.hubspot.com/forms/51393541/editor/866a9eb0-c553-49c6-9374-431e82d71b5e/edit/form

## Paste-ready prompt for next session

```
Resuming hubspot-demo-prep skill. Read ~/.claude/skills/hubspot-demo-prep/HANDOFF.md.

Top priorities:
1. End-to-end live test on a fresh customer slug. Cleanup shipperzinc first, then run python3 builder.py {newslug} --playwright --first-run. Validate selectors, fix breakages, screenshot every output.
2. Port /tmp/demo-prep-shipperzinc/make-doc.py into builder.py.generate_doc() (parameterized — read from manifest, not hardcoded Shipperz IDs).
3. Address findings from Codex + Opus reviews stored at /private/tmp/claude-501/.../tasks/{ids}.output (run timestamp 2026-04-26).
4. Build CRM card UI extension via `hs project create + crm-card` for the Shipments object (deferred from v2).

Sandbox: 51393541. Token + PAK in ~/.claude/api-keys.env. Drive folder: 1SzHT9uhFUUcFIAh5z2LVCAq2Wt0OADjY.
```

---

## v3 session — 2026-04-26 evening

### Code changes that landed this session

1. **Pre-flight scope check** added at builder startup. `Builder.preflight_scopes()` (~55 lines) hits `POST /oauth/v2/private-apps/get/access-token-info` with `tokenKey` body, parses scopes, hard-fails with re-auth deep link if any of `REQUIRED_SCOPES` (defined module-level) is missing. Optional scopes surface as warnings without blocking. Wired as first call in `Builder.run()`.

2. **Private App scopes unlocked via Playwright** (Claude_in_Chrome MCP against the user's logged-in Chrome). Token now has 39 scopes — added `marketing.campaigns.read/write`, `crm.objects.leads.read/write`, `crm.objects.invoices.read/write`, `crm.schemas.deals.read/write`. Re-auth deep link: `https://app.hubspot.com/private-apps/51393541/37767254`. The existing token kept the same value but gained scopes — no env file change needed.

3. **Engagement cleanup tagging** (priority 6). `ensure_properties()` extended to create `demo_customer` on engagement object types (notes/tasks/calls/meetings/emails) with a 400 retry-without-groupName fallback. `create_engagements()` adds `demo_customer: <slug>` to every engagement payload's `properties` dict.

4. **Custom-object + calc-property cleanup** (priority 7). `cleanup()` now reads manifest's `custom_object.object_type_id`, paginates GET to delete every record, then DELETE on the schema (with 405→`/purge` fallback). Also DELETEs the calc property `deal_age_days` and the property group from manifest's `calc_property` field.

5. **Doc generator port** (priority 3) — subagent ported `/tmp/demo-prep-shipperzinc/{make-doc,update-doc,export-pdf}.py` into new `~/.claude/skills/hubspot-demo-prep/doc_generator.py` (~700 lines). Public API:
   - `generate_docx(manifest, research, plan, *, slug, work_dir, portal) -> docx_path`
   - `upload_to_drive(docx_path, *, doc_title, drive_folder_id, replace_doc_id=None) -> dict`
   - `export_pdf(doc_id, out_path) -> str | None`
   - Defaults to creating a NEW GDoc (locked Shipperz doc only overwritten when `slug == "shipperzinc"` AND env `HUBSPOT_DEMOPREP_LOCKED_DOC_ID` is set, which it isn't).
   - rclone-based OAuth refresh; on failure, saves .docx locally and returns `gdoc_url: None` (build keeps going).
   - Heuristic agenda status pills derived from manifest signals (forms/workflows/email present + agenda title keyword match).
   - **Builder.generate_doc()** now a 24-line delegate. ~150 lines of dead HTML-based code deleted.

6. **Workflow API restored with actionTypeId fix** (priority 5). After Jeremy pushed back, restored the v4 flows API call. Set Property action: `0-5` → `0-2`. API still returned 500 internal error on live test — `0-2` is also wrong. Playwright phase is the actual fallback. Kept gap-action manual_step logging for steps the API can't express.

7. **Slash command `/hotdog`** at `~/.claude/commands/hotdog.md`. Invokes the skill with a banner. Banner script at `~/.claude/skills/hubspot-demo-prep/helpers/banner.sh` uses bash ANSI-C `$'\e[...m'` quoting so heredoc preserves real escape characters. (Jeremy iterating the banner himself in another session.)

### Live test (2026-04-26 ~20:20)

**Cleanup** (`python3 builder.py cleanup shipperzinc`): worked. Custom-object schema teardown succeeded (priority 7 validated). 400s on invoices/quotes/leads/engagements searches because those properties didn't exist on those object types yet (build had never finished v2). Expected.

**API-only build** (`python3 builder.py shipperzinc`, no Playwright, ~95 sec, exit 0):

Worked: company (54459406956), 8 contacts, pipeline (reused 893842217), 5 deals, 2 tickets, **168 engagements** (now tagged with demo_customer), custom object schema (2-61503444) + 4 records, 1 custom event def + 15 fires, lead scores 8/8, marketing email (211757175353) with AI hero image, marketing campaign (c00f917c-ae80-4332-a80d-dd4b5860f240) + 2 assets linked, property group `shipperz_demo_properties`, demo doc generated locally.

Failed: **leads 0/8** (silent — create_leads swallows error), **Quote form** 400 VALIDATION_ERROR, **form submissions 0/6**, **both workflows** 500 internal error (actionTypeId 0-2 also wrong), **all 5 quotes** 400, **invoices** 400 batch, **calc property** 400 (`Unable to parse calculation formula… DAYS_BETWEEN(createdate, NOW())` — formula syntax wrong; HubSpot wants `(NOW() - createdate)` style). Drive upload 403 quota — non-blocking, .docx saved at `/tmp/demo-prep-shipperzinc/demo-doc.docx`.

19 errors, 6 manual steps. Build summary at end of `/tmp/demo-prep-shipperzinc/build-api-run-1.log`.

**Playwright phase: NOT RUN** — pending Jeremy's go-ahead at session end.

### Bugs to fix (next session)

1. **`create_leads()` swallows errors.** Prints `✓ leads: 0/8` (green) when 0 created. Need to log per-lead error responses to identify the actual API failure.
2. **Workflow v4 API actionTypeId for Set Property still wrong.** `0-2` returned 500. Either probe HubSpot's exposed action types via `GET /automation/v4/actionTypes` (if endpoint exists), OR commit to template-clone (clone an existing UI-built workflow's body shape). For Friday, Playwright UI fallback is the realistic path.
3. **Calc property formula syntax wrong.** `DAYS_BETWEEN(createdate, NOW())` rejected — needs HubSpot's actual calc-prop function set. The error message lists allowed operators; rewrite formula accordingly.
4. **Quote create 400** on all 5. Likely missing required field or wrong association ID. Need to log the response body.
5. **Quote form 400 internal error** — VALIDATION_ERROR on form body shape.

### New backlog item from Jeremy

**End-of-build verification loop** — after every phase that creates an artifact, re-fetch via API GET, confirm key fields populated, optionally Playwright-screenshot the rendered UI. If verification fails, mark the doc's status pill as `[NOT_BUILT]` instead of `[BUILT]`. Also add a "happy path walkthrough" that screenshots 3-5 demo URLs (one contact, pipeline board, email preview, NPS form) and saves to `<work_dir>/verification/`. This addresses the "we say it's built but it's not viewable" gap.

### Next-session priorities

1. **Run Playwright phase** (`python3 builder.py shipperzinc --playwright --first-run`) — handles workflows + branding + saved views via UI. Highest demo-value item still missing.
2. Fix the 5 v2 bugs above (leads error logging, calc formula, quote payload, quote form, workflow API or template-clone).
3. Build the verification loop (Jeremy's testing-loop request).
4. Wrap as Claude Code plugin (`.claude-plugin/plugin.json` + `marketing.json` + `git init`) for distribution.

### Paste-ready re-prompt

```
Resuming hubspot-demo-prep skill. Read ~/.claude/skills/hubspot-demo-prep/HANDOFF.md
(skip to "v3 session — 2026-04-26 evening" — that's the latest state).

Token has 39 scopes; pre-flight check passes. Cleanup is sound, custom-object teardown works,
engagements now tagged with demo_customer at creation.

Today's outstanding work:
1. Run python3 builder.py shipperzinc --playwright --first-run — Playwright UI phases never ran.
   Watch selector breakages, screenshot every flow.
2. Fix 5 bugs from API run (see HANDOFF "Bugs to fix" section): leads error logging,
   calc property formula, quote 400, quote form 400, workflow API.
3. Build verification loop per Jeremy's request — phase-end API GET + optional screenshot.
4. Banner is being iterated by Jeremy directly — don't touch helpers/banner.sh.

Sandbox 51393541. Last build manifest: /tmp/demo-prep-shipperzinc/manifest.json.
```

---

## v4 session — 2026-04-26 late evening

### What landed

1. **Verification loop** (~190 lines) per Jeremy's mandate. After every `create_*`,
   `verify_*` does a targeted GET, checks key fields, and writes
   `manifest["verifications"][phase] = {verified, retried, message}`. If a phase's
   verify fails AND nothing was created, `_run_with_verify` retries the create once
   (avoids duplicate side-effects on partial successes). Wired into `Builder.run()`
   for all 16 create phases. Build summary now ends with `Verified: X/Y phases` and
   lists any unverified phases by name.

2. **doc_generator integrates verifications.** `_agenda_status_lines` now AND-gates
   "is built" booleans against `manifest["verifications"][phase].verified`, so a
   phase that didn't actually land in HubSpot can't render `[BUILT]` in the doc.
   Falls back to legacy heuristics if `verifications` is absent (older manifests).

3. **Quote form 400 (`required: [validation]`) — fixed.** Each form field now
   carries a `validation` object. Email fields get
   `{blockedEmailDomains: [], useDefaultBlockList: false}`; everything else gets
   `{}`. Live test: form `Shipperz Quote Request (Demo)` now creates clean.

4. **Hot leads list 400 "already exists" — fixed.** Switched from
   `GET /crm/v3/lists?objectTypeId=0-1` (which silently returned no match) to
   `GET /crm/v3/lists/object-type-id/0-1/name/{urlencoded-name}` for the dedup
   lookup. Added a 400 fallback that re-queries by name if the create races.

5. **Leads property pre-flight 400 — fixed.** Now `GET /crm/v3/properties/leads/groups`
   first to discover the actual group name (this portal: `lead_information`, not
   `leadinformation`). Falls back to first non-hidden group if the preferred
   names aren't present.

6. **Marketing campaign 409 — fixed.** Same reuse pattern: on 409 or 400-already-exists,
   `GET /marketing/v3/campaigns?name=<name>`. The list endpoint returns matching
   campaigns with empty `properties` (HubSpot only populates on individual GETs),
   so we use the result directly when `total == 1`.

### Live test results (`build-api-run-5.log`, 2026-04-26 21:13)

```
Errors: 4  (was 5 last session, was 19 the session before)
Verified: 15/16 phases
unverified: workflows  (HubSpot v4 flows API 500 — Playwright is the fallback)
demo doc → https://docs.google.com/document/d/13W2ooC7VqpmWfVd5BR89ZOqnAtjbg_lE86WkkTlmStU/edit
```

All major phases now verified: company, contacts, leads, deals, tickets, engagements,
custom_object, custom_events, forms, lead_scoring, marketing_email, quotes, invoices,
calc_property_and_group, marketing_campaign. ~95s API-only build.

### Still open / next session

1. **Run `python3 builder.py shipperzinc --playwright --first-run`.** Playwright
   phases handle workflows + branding + saved views via UI. Needs Chrome login on
   first run; storage-state cached at `state/{slug}-hubspot.json` after that.
   Will close the `workflows` unverified gap.

2. **Form submissions stuck at 0/8 + 0/6.** Pre-existing bug, not on this
   session's priority list. The form-submit endpoint returns non-200 for every
   submission body. Likely a content-type / form-context payload issue. Cosmetic
   for the demo (rep walks the form live).

3. **Wrap as Claude Code plugin** — `.claude-plugin/plugin.json` +
   `marketing.json` + `git init` + GitHub repo. Distribution-ready packaging.

4. **Workflow v4 actionTypeId** — `0-2` and `0-5` both 500. Either probe
   `GET /automation/v4/actionTypes` or commit to template-clone (clone an
   existing UI-built workflow body shape). Playwright UI fallback is the
   realistic path for Friday.

5. **Drive 403 quota** — sometimes hits "Queries per minute" limit on rapid
   reruns. Non-blocking; .docx still saves locally. Could add exponential backoff
   in `doc_generator.upload_to_drive` if it becomes a recurring issue.

### Files touched this session

- `builder.py` — +220 lines (verifications + 4 bug fixes), still imports clean
- `doc_generator.py` — verification gate in `_agenda_status_lines`
- No changes to `playwright_phases.py`, `playwright_phases_extras.py`,
  `helpers/banner.sh`, or the locked Shipperz GDoc

### Paste-ready re-prompt for next session

```
Resuming hubspot-demo-prep. Read ~/.claude/skills/hubspot-demo-prep/HANDOFF.md
"v4 session" section — that's the latest state.

15/16 phases verified on the API path. Only workflows unverified (HubSpot v4 flows
API 500). Verification loop is running per Jeremy's spec, doc renders [NOT_BUILT]
for unverified phases.

Today:
1. Run `python3 builder.py shipperzinc --playwright --first-run`. Watch selector
   breakages, screenshot every flow. Closes the workflows gap.
2. Wrap as Claude Code plugin (.claude-plugin/plugin.json + marketing.json +
   git init + GitHub repo) for distribution.
3. (Optional) Investigate form submissions 0/n — submission-API content-type or
   form-context payload issue.

Sandbox 51393541. Last manifest: /tmp/demo-prep-shipperzinc/manifest.json.
Latest demo doc: https://docs.google.com/document/d/13W2ooC7VqpmWfVd5BR89ZOqnAtjbg_lE86WkkTlmStU/edit
```

---

## v4.5 session — 2026-04-26 late evening (Playwright reality check)

### Wins

1. **Multi-portal login flow** — Jeremy's Google account redirected to
   production portal `20708362` instead of sandbox `51393541` after auth,
   and the previous URL-match regex demanded the sandbox id, so login
   timed out at 5 min. Fix in `playwright_phases.py:_interactive_login`:
   relax the post-login regex to match any logged-in HubSpot path
   (`/home`, `/reports-dashboard`, `/contacts`, etc.), then explicitly
   `goto(/contacts/{sandbox_portal})` to switch portals before saving
   storage state. Worked first try.

2. **Storage-state load bug** — `_has_state(self.slug)` should have been
   `_has_state(self.portal_id)`; the state file is keyed per portal, not
   per slug. Without this fix the saved session would never load on
   subsequent runs and every run would prompt for login.

3. **Extras attribute bug** — `playwright_phases_extras.py` referenced
   `session.portal` (the dashboard + saved-views flows). The
   `PlaywrightSession` only has `.portal_id`. Two replacements; both
   flows now don't crash on import.

4. **Storage state saved** — `state/portal-51393541-hubspot.json` (57KB).
   Future runs (`--playwright` without `--first-run`) skip login entirely.

### Reality on Playwright UI selectors

All 6 Playwright UI phases failed on selector timeouts (30s each).
This is consistent with the v2 HANDOFF warning: "ALL Playwright
selectors are GUESSED (text/role-based, not CSS)." Each failure
fell back to a `manual_step` per the `_safe_flow` design — no
crashes, but **0/6 flows actually built anything in the UI**.
Screenshots saved at `/tmp/demo-prep-shipperzinc/playwright/` for each
timeout; useful for manual selector debugging next session.

Phases that timed out:
- `upload_portal_branding` — selector `re.compile(r"primary\s*color")`
- `create_workflow_lead_nurture` — selector `re.compile(r"contact[\-\s]based")`
- `create_workflow_nps_routing` — same as above
- `create_quote_template` — selector `re.compile(r"create\s+(new\s+)?template")`
- `create_sales_sequence` — selector `re.compile(r"create\s+sequence")`
- `kick_off_seo_scan` — selector `re.compile(r"get\s+audit|run\s+audit")`

Each of these needs a real-DOM inspection pass on the live HubSpot UI to
update selectors. Probably 30-60 min per flow if HubSpot's UI is stable.

### What this means for Friday's demo recording

The API path is demo-viable today (15/16 verified, 4 errors, all the
visible-in-demo artifacts created). Playwright doesn't add demo value
yet — selectors need iteration before any of those phases produce
real artifacts. The doc currently renders workflows as `[BUILD LIVE]`,
which is the right pill: rep walks that step live.

### Open questions for next session

- Decide whether to invest in selector iteration (high cost, brittle,
  needs HubSpot UI to be stable across portals) or commit to the API +
  manual_steps approach for v5. The "premium" demo phases (workflows,
  branding, dashboards) might be cheaper to build via the
  Workflow-template-clone approach hinted at in the v2 HANDOFF
  (clone an existing UI-built workflow, mutate the body shape per
  customer). That avoids both v4 flows API 500s AND brittle UI selectors.
- Form submissions 0/n still pre-existing bug, not investigated.
- Plugin wrap (`.claude-plugin/plugin.json` + marketplace.json + GitHub
  push) deferred per Jeremy.

---

## v5 / v0.2.0 plugin release — 2026-04-26 night

### Released

- **Plugin shipped to GitHub:** https://github.com/sagaillj/hubspot-demo-prep
  Marketplace name `hubspot-demo-prep`, plugin name `hubspot-demo-prep`,
  versions `0.1.0` (initial plugin wrap) and `0.2.0` (post-test fixes).
- **Installed in Jeremy's local Claude Code:**
  `claude plugin marketplace add sagaillj/hubspot-demo-prep`,
  `claude plugin install hubspot-demo-prep@hubspot-demo-prep`,
  later `claude plugin update hubspot-demo-prep@hubspot-demo-prep` to 0.2.0.
  After plugin update, Claude says "Restart to apply changes" — restart
  required for new manifest to load.
- **Repo restructured for plugin layout:**
  - `.claude-plugin/{plugin,marketplace}.json` at root
  - `commands/hotdog.md` at root (uses `${CLAUDE_PLUGIN_ROOT}` for paths)
  - `skills/hubspot-demo-prep/` holds all the prior skill files
  - `state/` removed from repo; STATE_DIR moved to
    `~/.claude/data/hubspot-demo-prep/state/` (portable, survives plugin
    reinstalls). Existing `portal-51393541-hubspot.json` migrated.
- **Old user-level `~/.claude/commands/hotdog.md` backed up to `.bak`**
  to prevent shadowing of the plugin's slash command.

### v0.2.0 fixes (post-test on Boomer McLOUD)

1. **Doc regression fixed.** SKILL.md Phase 3+4 was still describing
   the old shell-helper architecture (`bash helpers/02-seed-crm.sh`
   etc.) that no longer matches the implementation. The orchestrator
   in another session interpreted "Generate a Google Doc" as
   "you write markdown via the Drive MCP" — produced a markdown source
   file instead of the formatted .docx. Both SKILL.md and
   commands/hotdog.md now explicitly say "run
   `python3 ${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/builder.py
   <slug>`" and have a CRITICAL section warning against the regression
   pattern.

2. **Research script parallelized.** `helpers/01-research.sh` was
   running Firecrawl, Playwright screenshot, and Perplexity
   sequentially. Now they launch as parallel background jobs; script
   waits on each PID. Saves 1-3 min per fresh run.

3. **Research cache (24h TTL).** Same script now exits early with
   "Using cached research" if `research.json` exists for the slug
   and is younger than 86400s. `--no-cache` flag forces re-fetch.
   Saves 2-5 min on re-runs.

4. **Playwright opt-in confirmed.** Already opt-in via `--playwright`
   flag (default off). Saves 3-7 min by default.

### Known regression after the Boomer McLOUD test (v0.2.0 doesn't fix these)

Captured as a punch list at `skills/hubspot-demo-prep/docs/punch-lists/2026-04-26-post-test-tweaks/punch-list.md`.
Items 1-6 deferred to next session:

1. **Image-gen provider chooser** — auto-generate marketing-email hero
   per prospect. Detect available providers in priority order (Recraft
   free tier as default, Google Gemini if AI Studio key, OpenAI
   gpt-image-1 if `OPENAI_API_KEY`, Codex/ChatGPT environment).
   Surfaced via one-line preflight: "Using Recraft (free tier). Want to
   switch?" Recraft confirmed to have a 30-credits/day free tier.
2. **NPS form quality** — current form is just `email + firstname +
   "Submit feedback"`. Needs the actual NPS question
   ("On a scale of 1 to 10, would you recommend {company}?"), an
   open-ended "Tell us about your experience", plus prospect logo + brand
   styling.
3. **Workflow link points to specific built workflow** — currently the
   doc's workflow link goes to the workflows index page. Should open
   the specific workflow's edit screen when one was built.
4. **Quote form re-verify** — Boomer doc said "form rejected by HubSpot
   Forms API" but v4 commit 9ce1cb8 added the validation field fix.
   Either the new run didn't pick up the fix or there's a second
   rejection path. Investigate.
5. **Engagement content uniqueness** — all notes/calls/meetings look
   copy-pasted. Each engagement should have unique content tied to deal,
   contact, or context.
6. **Marcus Chen contact link broken** — first contact's URL from doc
   broken. Verification step missed it (verifies first contact via API
   GET, not the doc's URL format).

### Demo strategy decided

Jeremy will kick off `/hotdog <prospect>` at the start of the LinkedIn
recording, then spend 5-10 min talking through the architecture +
HubSpot pain-point philosophy while the build runs in background, then
reveal the doc + click through HubSpot artifacts. Friday recording.

### Paste-ready re-prompt for next session

```
Resuming hubspot-demo-prep. v0.2.0 plugin is installed locally
(claude plugin list shows hubspot-demo-prep@hubspot-demo-prep 0.2.0).
Repo at https://github.com/sagaillj/hubspot-demo-prep, dev tree at
~/.claude/skills/hubspot-demo-prep.

Read ~/.claude/skills/hubspot-demo-prep/HANDOFF.md "v5 / v0.2.0" section.

Active punch list at
~/.claude/skills/hubspot-demo-prep/skills/hubspot-demo-prep/docs/punch-lists/2026-04-26-post-test-tweaks/punch-list.md.

Items 7 + 8 shipped in v0.2.0. Items 1-6 are deferred and need to be
worked next:
  1. Image-gen provider chooser (Recraft default + Gemini/OpenAI/Codex
     fallbacks; free tier preferred).
  2. NPS form quality (real NPS questions + branding/logo).
  3. Workflow link should point to the specific built workflow.
  4. Quote form 400 re-verify after v4 fix.
  5. Engagement content uniqueness.
  6. Marcus Chen contact link broken; verification gap.

Suggested order: 4 (small, blocks #2 indirectly), 6 + verification fix
(small, trust issue), 2 (medium, demo-quality), 5 (medium, demo-quality),
3 (small, but only useful once #1 / Playwright works), 1 (largest, new
external integration). Bump to v0.3.0 when shipping.

Demo recording is Friday. /hotdog will be invoked live during the
recording, so all 6 items materially affect what the audience sees.

Sandbox: 51393541. Last manifests:
/tmp/demo-prep-shipperzinc/manifest.json,
/tmp/demo-prep-boomermcloud/manifest.json (if it exists).
HubSpot login state cached at
~/.claude/data/hubspot-demo-prep/state/portal-51393541-hubspot.json.

To resume the dod punch list: invoke `/dod` and it picks up the active
list automatically.
```

