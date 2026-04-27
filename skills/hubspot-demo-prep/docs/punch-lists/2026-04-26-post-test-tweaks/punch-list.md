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

### 4. Quote form re-verify (DEFERRED)
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
