# Punch List: hubspot-demo-prep post-test tweaks

**Created:** 2026-04-26
**Source:** brain dump after Jeremy ran the plugin on Boomer McLOUD as the second test prospect
**Status:** Phase 3 — Execute (items 7 + 8 only this batch; 1–6 deferred)

## Items

### 1. Image generation: provider chooser (DEFERRED to next batch)
**What:** Auto-generate the marketing-email hero per prospect instead of consuming a manually-pre-placed file. Detect available providers in priority order: Recraft free tier (always-available default) → Google Gemini / nano-banana if AI Studio key present → OpenAI gpt-image-1 if `OPENAI_API_KEY` set → Codex/ChatGPT environment if running there. Pre-flight surfaces the chosen tool with a one-liner ("Using Recraft (free tier). Want to switch?").
**Don't break:** existing `upload_hero_image()` flow that reads from `plan["marketing_email"]["hero_image_path"]` — new code generates the image then writes the path into that field, builder consumes it unchanged.
**DOD:** new prospect runs end-to-end, marketing email shows AI-generated hero with no manual file-drop step.

### 2. NPS form quality (DEFERRED)
**What:** Current NPS form is just `email + firstname + "Submit feedback"`. Should ask "On a scale of 1 to 10, would you recommend {company}?" + "Tell us about your experience" (open-ended). Should include the prospect's logo and brand styling.
**Don't break:** form must still get accepted by HubSpot Forms v3 API (validation field, fieldType correctness, fieldGroup max 3).
**DOD:** rendered NPS form matches what a real survey looks like, branded.

### 3. Workflow link points to specific built workflow (DEFERRED)
**What:** Currently the doc's workflow link goes to the workflows index. Should open the specific workflow's edit screen for the workflow built (when one exists).
**Don't break:** when no workflow was built (current state — v4 flows API 500), link should still go somewhere useful (workflow create page).
**DOD:** click the link, land on the right edit screen for that workflow.

### 4. Quote form re-verify ✅ DONE (2026-04-26 evening)
**Resolution:** curl GET on Boomer's 3 form GUIDs all returned HTTP 200 with correct field counts (NPS=3, Marine Consultation=4, Remote Starter Quote=4). The original "form rejected" capture was a phantom — Boomer's manifest already showed all 3 forms created successfully, and the only "rejected" wording in the doc/manifest is about the v4 workflows API (`v4 flows API rejected actions; UI build is X minutes`), not the forms API. The v4 commit 9ce1cb8 validation-field fix is in place and working.
**Evidence:** `screenshots/4-form-verify.txt`

---

### 4. Quote form re-verify (ORIGINAL ENTRY — kept for history)
**What:** Boomer McLOUD doc says "form rejected by HubSpot Forms API" — but my v4 commit 9ce1cb8 added the `validation` field fix. Either the new run didn't pick up the fix, or there's a second rejection path. Investigate, log the actual error, fix.
**Don't break:** existing successful Shipperz form still works.
**DOD:** form creates clean on a new prospect's first run.

### 5. Engagement content uniqueness (DEFERRED)
**What:** All notes / calls / meetings look copy-pasted. Each engagement should have unique content tied to the deal, contact, or context (subject lines, body text, durations).
**Don't break:** parallel creation, demo_customer tagging, backdated timestamps, association to contact + deal.
**DOD:** scrolling through a contact's timeline looks like a real lived-in customer record.

### 6. Marcus Chen contact link broken (DEFERRED — verification gap)
**What:** Click on first contact's URL from doc → broken. Verification step didn't catch it (verifies 1st contact via API GET, not the doc's URL format).
**Don't break:** verification logic stays.
**DOD:** every contact link in the doc opens the right contact record. Verification step catches URL malformation.

### 7. Speed: target ≤ 15-min total runtime (THIS BATCH)
**What:** Run took ~30 min on Boomer McLOUD; goal is ≤15 min for fresh prospect, ≤5 min for re-runs. Top 3 speedups:
  - **7a.** Make Playwright opt-in (currently runs by default; phases all timeout 30s × 6 = ~3 min wasted; selectors don't work yet)
  - **7b.** Cache research per domain (research.json with 24h TTL; second run on same domain skips Firecrawl/Perplexity/Playwright-screenshot)
  - **7c.** Parallelize Phase 1 research helper (Firecrawl, Playwright screenshot, Perplexity run in background; ~1–3 min saved)
**Don't break:** existing fresh-run flow when cache miss; explicit `--playwright` opt-in still works; `--no-cache` flag for forced re-research.
**DOD:** fresh-prospect run completes in 10–15 min; re-run on same prospect (within 24h) completes in <5 min.

### 8. Doc generation regression (THIS BATCH)
**What:** New Boomer McLOUD doc shows raw markdown rendered as plain text (`# HubSpot Demo Prep`, `**Brand colors:**`) — bypassed `doc_generator.py`'s formatted .docx path. Title format ("HubSpot Demo Prep — Boomer McLOUD — 2026-04-26") differs from doc_generator's ("HubSpot Demo Prep · Boomer McLOUD"), confirming Claude in the orchestrator session generated the doc itself via Drive MCP instead of letting `builder.py:generate_doc()` invoke the Python doc_generator.
**Root cause:** SKILL.md Phase 4 + commands/hotdog.md don't prescribe the python builder.py invocation explicitly; Claude interprets "generate a Google Doc" as "you write markdown."
**Fix:** Update SKILL.md and commands/hotdog.md to explicitly run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/builder.py <slug>` and never have Claude generate the doc itself. Plus add a defensive note in builder.py output: "demo doc → <URL> (formatted via doc_generator.py)" so a future run would surface a regression.
**Don't break:** the formatted-docx output that worked on the Shipperz doc.
**DOD:** new prospect run produces a properly formatted docx with banner, agenda pills, links — matching the Shipperz doc style.

---

## Execution batches (this run)

**Batch A (parallel):**
- 7a — Playwright opt-in default
- 8 — SKILL.md + slash command explicit builder.py invocation

**Batch B (sequential after A):**
- 7b — research cache
- 7c — parallelize research helper

**Batch C:**
- bump version (0.1.0 → 0.2.0), commit, push, `claude plugin marketplace update hubspot-demo-prep`, `claude plugin install hubspot-demo-prep@hubspot-demo-prep`

## Deferred items (next session)
1, 2, 3, 4, 5, 6 — flagged for follow-up dod run. None blocking the speed work.

---

## Items added during Phase 2 codebase sweep (2026-04-26 evening)

### 9. Industry-agnostic copy refactor (NEW — proactively surfaced)
**What:** `builder.py` was first written for Shipperz (auto transport) and several user-facing strings still bake "auto transport" into every prospect's output. For Boomer (marine audio) — and any non-transport prospect — these strings read as obviously-wrong demo data the moment the rep clicks into them.

**Surfaces requiring fix (all to plan-driven):**
1. **Lead names** (line 1316): `f"{name_prefix} — auto transport inquiry ({src})"` — every lead title says "auto transport inquiry" regardless of industry. Should pull from `plan["lead_label_template"]` (e.g., for Boomer: "marine audio inquiry").
2. **Quote line items catalog** (line 1391): hardcoded `[{"name":"Enclosed transport — coast to coast","price":"2400"}, ..., {"name":"Storage (per day, post-delivery)","price":"45"}]` — six transport services. Should pull from `plan["quote_catalog"]` per industry (Boomer: JL Audio package, Garmin chartplotter, install labor, etc).
3. **Marketing email — local HTML preview** (lines 1023-1052): "personalized quote tailored to your vehicle and route", "Door-to-door enclosed transport", footer "{company_name} — Premium auto transport". Should pull from `plan["marketing_email"]["body_html"]` or a structured `plan["marketing_email"]["sections"]`.
4. **Marketing email — HubSpot widget body** (lines 1093-1108): same transport copy duplicated + hardcoded `#FF6B35` orange CTA. Should consume `plan["marketing_email"]["body_html"]` and `plan["marketing_email"]["cta_color"]` (or pull from branding).
5. **Marketing campaign** (lines 1639-1647): hardcoded `hs_name = "{company}: Snowbird Season Q1 2026"`, hardcoded "Seasonal northbound campaign targeting FL/AZ/TX snowbirds", hardcoded `hs_audience = "Snowbirds 60+ owners of vehicles needing seasonal transport"`. Should pull from `plan["marketing_campaign"]` (name, dates, notes, audience, utm).
6. **Color fallback** (lines 1016, 2130): `#FF6B35` (Shipperz orange) used as default when `branding.secondary_color` / `branding.accent_color` is missing. Should be a neutral fallback like `#3B82F6` (slate blue) or simply derived from the primary color.

**Don't break:** existing branding-derived theming when research provides colors; existing builder.py consumption flow when plan is missing the new fields (graceful fallback to a generic-but-not-Shipperz default).

**DOD:** end-to-end run on a non-transport prospect produces lead names, line items, marketing email copy, and campaign metadata that all read as appropriate to that industry. No "auto transport" string anywhere unless the prospect is genuinely a transport company.

**Verification:** grep the generated /tmp/demo-prep-<slug>/ artifacts and the HubSpot manifest entries for the literal strings "auto transport", "snowbird", "vehicle and route" — should return zero matches for non-transport prospects.

**EXPANDED (2026-04-26 evening, after 4 background sweep agents) — full surface list in `sweep-consolidated.md`:**
- builder.py: 14 known + 10 new surfaces (incl. property group name `shipperz_demo_properties`, Shipperz-specific Google Doc branching at L1740, lead labels/sources, activity pools)
- doc_generator.py: `SHIPPERZ_ORANGE`/`SHIPPERZ_DARK` constants + L674 "no marketing team" recommendation + L203 banner slug check
- references/easter-egg-catalog.md, v2-capabilities.md, v2-content-campaigns.md (ENTIRE rewrite needed), google-doc-template.md, setup-procedure.md
- playwright_phases_extras.py: entire `create_starter_dashboard()` hardcoded "Shipperz Daily Snapshot"

### 10. SKILL.md Phase 2 Quality Gate (NEW — prevents new bias upstream)
**What:** Add a "Phase 2 Quality Gate" section to SKILL.md that the orchestrator Claude reads before writing build-plan.json. Forces explicit validation:
1. **No terminology reuse from prior runs.** No phrasing carried over from a previous prospect (e.g. don't put "Tesla Model Y" in a marine audio shop's tickets).
2. **Persona freshness.** Re-infer contact personas from the prospect's industry + GTM model + research.json. Don't inherit from a previous run.
3. **Deal-stage prospect-specificity.** Pipeline stages must reflect this prospect's actual sales cycle, not a template.
4. **Custom object naming.** Object name reflects the prospect's domain (`audio_installation_job` not `shipment` for Boomer).
5. **Email voice-match.** Marketing email CTA style matches the prospect's actual website CTA pattern.
6. **No phantom numbers in recommendation text.** Only cite figures present in the manifest.
**Don't break:** existing solve-for-the-customer guidance.
**DOD:** SKILL.md has a clear Phase 2 Quality Gate section. New runs visibly use the prospect's vocabulary.

### 11. Manual-step error message hygiene (NEW)
**What:** When `add_manual_step` is called with a `reason` string sourced from a raw API error (e.g. "API returned 500", "v4 flows API rejected actions"), the doc currently shows that to the prospect. A prospect should never see "v4 API does not support send_email action directly." Sanitize: rewrite reasons as user-facing language ("Built manually for finer control over branching", "UI build adds richer logic than the API exposes") OR simply omit the reason from the public doc and keep it internally for the rep.
**Don't break:** internal manifest still records the actual reason for debugging.
**DOD:** No "API", "500", "rejected", "blocked" string appears in any rendered demo-doc; reasons read as professional rationale.

### 12. Phantom-number prevention in recommendation text (NEW)
**What:** `doc_generator._recommendation_text` (line 657+) and any other narrative-text generator must only cite figures present in `manifest`. Example bug: Boomer doc cites "$4,200 boat install" with no corresponding deal in the pipeline. Add a guard that strips any candidate sentence containing a `$<number>` pattern unless that exact amount appears in `manifest["deals"]` or `plan["deals"]`.
**Don't break:** legitimate references to actual deal amounts.
**DOD:** Boomer-style phantom-number bug cannot recur; verifier added.

## Execution Report — 2026-04-26 night

### Items completed (14 total)
- **Item 1** ✅ Image-gen provider chooser — Recraft MCP (preferred) → OpenAI gpt-image-1 → Gemini imagen via `helpers/09-generate-hero.sh` (REST), graceful skip when no provider available. Hardened: malformed JSON / non-PNG / missing-key all produce clean exits (64 = no-provider).
- **Item 2** ✅ NPS form quality — `dropdown_select` (1-10) + `multi_line_text` (open-ended) + `number` field types in `create_forms`; theme block applies branded submit color; test submissions use weighted score distribution (50% 9-10, 30% 7-8, 20% 1-6).
- **Item 3** ✅ Workflow link → specific edit URL — `_workflow_url` does exact-match → substring-match → manual_steps fallback → workflows index. Verified: keyword stubs like `"nurture"` correctly resolve to `"{Customer} - Welcome nurture"` full-name URLs.
- **Item 4** ✅ Quote forms verified working — Boomer's 3 form GUIDs all return 200 with correct field counts. Closed as already-fixed-in-v4 (commit 9ce1cb8).
- **Item 5** ✅ Engagement uniqueness — `plan["activity_content"]["per_contact_engagements"][cid]` for per-contact bodies; richer pools (notes/calls/meetings/emails as `{title, body}` objects) for fallback. Old hardcoded "Productive conversation" strings removed.
- **Item 6** ✅ Marcus Chen URL — root cause was the doc-generation regression (item 8 v0.2.0); plus new `verify_doc_urls` parses every hyperlink in the .docx and confirms each contact ID exists via API.
- **Item 9** ✅ Industry-agnostic copy refactor (massively expanded after sweep) — builder.py, doc_generator.py, playwright_phases.py + extras, 6 reference docs. All Shipperz/transport copy moved to plan-driven schema with industry-neutral fallbacks. Color fallbacks now `#3B82F6` slate blue + `#1A1A1A` near-black, replacing `#FF6B35` Shipperz orange.
- **Item 10** ✅ SKILL.md Phase 2 Quality Gate — 6 mandatory checks (no terminology reuse, persona freshness, deal-stage prospect-specificity, custom object naming, email voice-match, no phantom numbers).
- **Item 11** ✅ Manual-step reason hygiene — `_sanitize_reason` helper applied to all 14 `add_manual_step` call sites; raw error preserved in `internal_reason` for debugging.
- **Item 12** ✅ Phantom-number guard in `_recommendation_text` — handles `$1,200,000`, `$4.2K`, `$2.5M`, abbreviations like `e.g./Inc./etc.`. 7/7 self-tests pass.
- **Item 13** ✅ Manifest data integrity verifier — runs first in run() flow; `math.ceil(planned * 0.8)` tolerance (no more flooring to 0).
- **Item 14** ✅ Time saved vs manual build — `time_estimates.py` module; hero stat at top of doc + breakdown table at bottom; graceful degradation if module fails. Boomer test = ~4h (lean manifest); full runs land near 9h.
- **Item 7, 8** — already in v0.2.0 (speed + doc regression).

### Quality gates passed
- All 5 Python files (builder.py, doc_generator.py, time_estimates.py, playwright_phases.py, playwright_phases_extras.py) + helpers/09-generate-hero.sh syntax-clean
- Phantom-guard self-test: 7/7 PASS, 0 failures
- Forbidden-string sweep clean: zero `shipperz`/`Shipperz`/`snowbird`/`auto transport`/`vehicle and route`/`FF6B35` in executable code (all matches are in comments documenting prior state)
- Item 4 verification: 3 form GUIDs return HTTP 200 with correct field counts

### Reviews
- **Codex review pass #1** (codex:rescue, ~20 min): surfaced 6 Critical + 8 High + 7 Medium + 5 Low. All Critical/High fixed in FIX-1..4.
- **Opus review pass #1** (independent senior-engineer): surfaced 2 Critical + 4 High + 6 Medium overlapping with Codex. All Critical/High fixed.
- **Codex re-review pass #2**: failed (codex:rescue subagent hung, returned stub).
- **Opus re-review pass** (replacement for Codex re-review): verified 13 of 14 prior findings PASS, surfaced 1 NEW High (workflow URL exact-match miss) + 4 NEW Medium. The High and one Medium (dropdown empty-options) fixed inline. Remaining 3 Medium → backlog (`_sanitize_reason` over-aggression on "validation" word; `verify_doc_urls` doesn't BLOCK Drive upload (intentional); `runtime_seconds` referenced but never written — cosmetic).

### Diff stats (uncommitted)
14 files modified, 7 files new, ~2200 insertions / ~340 deletions. builder.py: 2330 → ~3170 lines.

### Open items requiring user input
1. **Production verify** — needs Jeremy's choice of fresh non-transport, non-marine, non-Shipperz, non-Boomer prospect URL. Suggested: a small B2B services company, HVAC contractor, boutique consultancy, or anything else genuinely different from prior runs. The verify will: run `/hotdog <url>` end-to-end, screenshot the doc + 3 contact link clicks + NPS form preview + marketing email hero, and grep for any leftover Shipperz/transport string in /tmp/demo-prep-{slug}/.
2. **Ship decision** — once production verify passes, bump `.claude-plugin/plugin.json` to 0.3.0, commit, push, run `claude plugin marketplace update hubspot-demo-prep`, `claude plugin update hubspot-demo-prep@hubspot-demo-prep`, restart Claude Code.

### Backlog items for future runs (medium severity, non-blocking)
- `_sanitize_reason` includes `"validation"` in forbidden tokens — could over-strip benign uses ("address validation"). No current callsite triggers it. Tighten to `"validation error"` / `"validation failed"`.
- `verify_doc_urls` does NOT block Drive upload on broken-link failure (logs to `manifest["errors"]` and proceeds). Intentional usability call but a broken-link doc can still land in Drive. Consider whether to fail-and-rollback.
- `runtime_seconds` referenced in `doc_generator.py:452` but never written by builder. Track wall-clock and persist for the "Built in Xm Ys" subtitle.
- HANDOFF.md v0.3.0 section mistakenly says "BRAND_ACCENT_ORANGE" — should be "BRAND_ACCENT_NEUTRAL". Cosmetic doc-only fix.

### 14. "Time saved vs manual build" estimate (NEW — Jeremy added mid-Phase-3, 2026-04-26 evening)
**What:** For everything generated/created/tested by `/hotdog`, attach a "this would have taken a human X minutes" estimate. The deliverable doc surfaces both:
1. **Hero stat at the top of the doc**: e.g. `⏱ This demo just saved you ~9 hours of manual HubSpot setup.` (sum of per-phase estimates × actual counts).
2. **Per-section breakdown** in a "Time saved" appendix or inline alongside each "What was built" entry: e.g. `8 contacts with full timelines · 45 min in UI · ~3 sec via API`.

**Estimate basis (minutes per unit, conservative side of "competent HubSpot admin"):**
- Company record: 2 min
- Contact (with properties + lifecycle stage): 3 min × N
- Deal with stage + amount + associations: 3 min × N
- Ticket: 2 min × N
- Engagement (note/task/call/meeting/email) with backdate: 1 min × N (engagements_count)
- Custom object schema: 15 min (one-time) + 2 min per record × N records
- Custom event definition: 8 min each + 0.5 min per fire × N
- Form (with fields + branding theme): 6 min × N + 0.5 min per test submission × N
- Lead score property + backfill: 5 min + 0.5 min per contact
- List (segment): 4 min × N
- Marketing email (design + content + hero upload): 60 min (or 90 if branded with hero)
- Workflow (built in UI): 8 min for simple, 15 min for branching/routing — read from manifest's manual_steps + workflow count
- Quote template usage + line items per deal: 3 min per deal + 1 min per line item
- Invoice: 3 min × N
- Marketing campaign with associations: 8 min
- Demo doc itself (writing + formatting + linking everything): 30 min
- Sandbox setup + integration sanity-check: 15 min one-time

**Implementation:**
1. New small module `helpers/time_estimates.py` (or section in `builder.py`) holds the minute-per-unit constants and a function `compute_time_saved(manifest, plan) -> dict` that returns `{total_minutes: int, breakdown: [{label, count, minutes_each, subtotal}]}`.
2. `builder.py` calls this after Phase 17 and writes result to `manifest["time_saved"]`.
3. `doc_generator.py` renders:
   - Hero stat at the top of the doc (under the title bar) — prominent format like `⏱ Saved ~Xh Ym vs manual build`
   - "Time saved" breakdown table near the bottom of the doc (under "What was built"), one row per phase with count + minutes
4. Round display: `<60` min as `~Xm`; `60-119` as `~1h Xm`; `>=120` as `~Xh` (drop minutes when ≥ 2h for cleanliness)

**Don't break:**
- All existing doc sections render in the same order
- The `What was built (every link clickable)` section keeps its current layout — the time row is additive
- If the time module fails or is missing, doc still renders without the time stat (graceful degradation)

**DOD:** every phase has a time estimate; total renders prominently in the deliverable doc; sums match the breakdown; numbers feel credible (not inflated, not deflated).

**Verification:** open the rendered docx for the production-verify run; manually sanity-check one or two of the larger numbers (e.g. 8 contacts × 3 min = 24 min should appear); confirm the hero stat is visible and accurately reflects the sum.

### 13. Manifest data integrity verifier (NEW)
**What:** Add a small `verify_manifest_integrity()` function that runs after Phase 17 and checks:
- `form_submissions_count` matches `sum(form.test_submissions for form in plan.forms)` (catches the Shipperz disconnect)
- Every deal in `plan["deals"]` has a corresponding entry in `manifest["deals"]`
- Every contact in `plan["contacts"]` has a corresponding entry in `manifest["contacts"]`
- No required field is `None` or empty
**Don't break:** Existing per-phase verify functions.
**DOD:** A deliberately mismatched manifest triggers failure; clean run shows `manifest_integrity: pass`.
