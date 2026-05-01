---
description: HubSpot Hot Dog — prep a HubSpot sandbox in Demo mode or Feature Showcase mode, including fictional public-safe showcases (v0.4)
argument-hint: <demo|showcase> <company URL/name OR feature story> [optional context: fictional/public-safe, audience, brain dump]
---

First, run this Bash command to print the colored banner directly to the terminal (ANSI escapes will render in color):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/helpers/banner.sh"
```

Then invoke the **hubspot-demo-prep** skill.

Customer input: $ARGUMENTS

## Workflow

1. **Parse the input and choose a mode.**
   - **Demo mode:** use when the user wants a prospect/customer-specific sandbox. Extract the company URL/name and any pain points or agenda hints.
   - **Feature Showcase mode:** use when the user wants to show one or more HubSpot features with realistic dummy data for content, enablement, or a meeting. Extract the story/brain dump, requested feature(s), audience, any known objections, whether the output is public-safe/fictional, and any optional brand/company URL.
   - If $ARGUMENTS is empty or ambiguous, ask: "Is this Demo mode for a real prospect, or Feature Showcase mode for a real or fictional feature/content story?" For Feature Showcase mode, ask for the brain dump, requested feature(s), audience, and whether to invent a fictional customer for public screenshots. Default to fictional/public-safe when the user mentions LinkedIn, social posts, public content, training examples, or avoiding customer data.

2. **Phase 1: Research or story capture.**
   - **Demo mode:** run the research helper, which executes Firecrawl, Playwright screenshot, and Perplexity in parallel and writes `research.json` to `/tmp/demo-prep-<slug>/`. Skips automatically if a fresh `research.json` (<24h old) already exists for that slug:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/helpers/01-research.sh" <slug> <url> "<optional context>"
   ```
   - **Feature Showcase mode:** if the user supplied a URL and explicitly wants real-brand/private enablement, run the same helper for branding and vocabulary. If no URL was supplied, or if the user wants fictional/public-safe content, synthesize `/tmp/demo-prep-<slug>/research.json` from the brain dump with `mode: "feature_showcase"`, a fictional showcase company, `.example.com` domain/email values, the requested features, audience, success criteria, shot-list hints, `customer_basis: "fictional"`, `public_safe: true`, and no invented citations.

3. **Phase 2: Synthesize the plan (v0.3.0 base + v0.4 extensions).** Read `research.json`, write `build-plan.json` to the same work dir. Always set `plan["mode"]` to `"demo"` or `"feature_showcase"`.
   - **Demo mode:** the plan captures a 3-item agenda + Easter egg, list of artifacts to build, branding inputs (colors, logo), v0.3.0 content fields (`branding`, `property_group`, `activity_content`, `quote_catalog`, extended `marketing_email`, `marketing_campaign`, `forms[].theme` + `test_submission_data`, `recommendation_text`, `playwright_dashboard`, optional `doc_replacement_id`), and, when the prospect has a repeatable digital funnel, v0.4 `custom_event_flows` + `playwright_reports`.
   - **Feature Showcase mode:** the plan captures `feature_showcase` (`story`, `requested_features`, `audience`, `success_criteria`, `shot_list`, `artifact_goals`, `easter_egg_strategy`, `customer_basis`, `public_safe`, `fictional_company_brief`), a 3-5 item showcase flow in `agenda`, realistic dummy records, built/blocked artifact links, and an adjacent-value Easter egg. For campaign attribution showcases, include multiple campaigns/source paths, first-touch vs last-touch differences, contacts linked to deals, real deal amounts, campaign assets, attribution reports, and a workflow/manual step for associating campaign influence to deals. For fictional/public-safe showcases, do not use real customer names, logos, employee names, private screenshots, or non-reserved email domains.
   - See `SKILL.md` Phase 2 plus `docs/punch-lists/2026-04-26-post-test-tweaks/plan-schema.md` and `docs/punch-lists/2026-04-28-reports-and-dashboards/plan-schema-v0.4.md`.

   Before invoking `builder.py`, generate the marketing email hero image. Provider is auto-detected (Recraft MCP → OpenAI → Gemini → none). Override with `HUBSPOT_DEMO_HERO_PROVIDER=recraft|openai|gemini|none`.

   **Phase 2 Quality Gate.** Before writing `build-plan.json`, run the Quality Gate documented in `SKILL.md` Phase 2 (explicit mode, public-safe fictional data when requested, no terminology reuse from prior runs, persona freshness, deal-stage specificity, custom object naming, email voice-match, no phantom numbers, logo persistence, NPS radio fields, feature-showcase coverage, campaign attribution coherence, funnel-data realism, reports/events alignment). This is the upstream guard against industry-bias bleed, accidental customer leakage, and generic showcase data — do not skip.

4. **Phase 3 + 4: Build + Doc.** Run the single Python entry point. It runs all 18 sub-phases (CRM seed, engagements, custom objects, funnel-ordered custom events, forms, marketing email, workflows, lead scoring, quotes, invoices, marketing campaign, v0.4 reports status/build, doc generation) AND generates the formatted .docx runbook/showcase doc + uploads to Drive in one shot:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/builder.py" <slug>
   ```
	   Add `--playwright` for the optional UI phases (branding upload, workflow creation via UI, quote template, starter dashboard, saved views, etc.). Add `--first-run` if no HubSpot login state is cached yet. The v0.4 report phase runs when `playwright_reports` exists; until the live report-builder selectors are implemented, it records `reports_status: blocked` plus a manual step.

   **Playwright bias warning.** When `--playwright` is used, the dashboard naming and pipeline filters now read from `plan["playwright_dashboard"]` (`name`, `filter_pipeline_name`, `filter_stages`). Phase 2 should populate that field with prospect-specific values; otherwise the dashboard inherits `f"{company_name} Daily Snapshot"` as default and the pipeline filter falls back to whatever pipeline name the plan defined. If `playwright_dashboard` is missing AND the legacy fallback is hit, the dashboard can end up with leftover Shipperz-style naming — do not ship without populating it.

5. **Surface the results.** Print the Drive URL of the generated doc (parsed from the build's last log line `demo doc → <URL>`), the build summary (counts, errors, verifications X/Y), total wall-clock runtime, every v0.4 dashboard URL from `manifest["dashboards_v04"]` if present, `reports_status` if blocked/error, and any manual steps from `manifest.json`. Also surface the integrity verifiers' pass/fail status:
   - **`verify_doc_urls`** — every clickable link in the demo doc resolves to a live HubSpot artifact.
   - **`verify_manifest_integrity`** — configured-vs-actual artifact counts match (catches the "8 form submissions configured, 0 recorded" class of bug).

## Environment overrides

- `HUBSPOT_DEMO_HERO_PROVIDER=recraft|openai|gemini|none` — force the marketing email hero image generator instead of using auto-detection.

## CRITICAL — do NOT generate the doc yourself

The Python script (`builder.py` → `doc_generator.py`) produces a fully-formatted .docx with mode-aware wording:
- A branded banner header (logo + brand colors)
- Status pills inline with agenda/showcase items (`[BUILT]`, `[BUILD LIVE]`, `[NOT BUILT]`, `[ANALOG]`)
- Clickable links to every HubSpot artifact
- Two-page layout (page 1 = print-ready runbook or showcase flow, page 2 = supporting research/story context + checklist)

If you skip the Python doc generation and write markdown into a Drive doc yourself with the Drive MCP, the result is a regression: raw markdown rendered as plain text, no banner, no pills, no formatting. **Do not do this.** Run `builder.py` and trust its doc output.
