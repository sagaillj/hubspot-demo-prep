---
name: hubspot-demo-prep
description: Generate a tailored, "live"-feeling HubSpot sandbox in minutes in either Demo mode or Feature Showcase mode. Demo mode researches a prospect and builds customer-specific CRM data, workflows, forms, marketing assets, reports, and a Google Doc runbook. Feature Showcase mode starts from a user's story / brain dump about one or more HubSpot features, then builds screenshot-ready data and artifacts that prove that feature story, with a Google Doc linking to everything built plus an adjacent-value Easter egg. Triggers on "prep a demo for X", "demo prep", "feature showcase", "showcase HubSpot attribution", "build dummy data for HubSpot", "build me a demo for [company]", "tailor a HubSpot demo", "demo for [company URL]", "set up a customer demo", or any request to create custom-tailored HubSpot demo data or feature-showcase data.
user-invokable: true
argument-hint: "[demo|showcase] [company-url-or-name OR feature story] [optional context: pain points, agenda, transcript path]"
---

# HubSpot Demo Prep Skill

Build a tailored HubSpot sandbox through one of two paths:

1. **Demo mode** — build a customer-specific demo environment for a prospect. Solve for the customer.
2. **Feature Showcase mode** — build a screenshot-ready or recording-ready environment that proves a HubSpot feature story with realistic dummy data. Solve for the audience's "can HubSpot really do this?" moment.

## When to use

- Prepping for a sales call where you want demo data that mirrors the prospect's industry / ICP / pain
- Recording a demo for a specific company and need it to feel real
- Creating content, enablement, or training assets around one or more HubSpot features
- Showing a new feature with realistic dummy data, e.g. campaign attribution, journeys, custom events, reporting, scoring, workflows, forms, or associations
- Creating a sales-engineering practice environment
- Demonstrating HubSpot capabilities to someone outside your typical demo flow

## Inputs

First, determine the run mode. If the user does not make the mode clear, ask one concise question: **"Is this Demo mode for a prospect, or Feature Showcase mode for a feature/content story?"**

### Demo mode inputs

1. **Company identifier** (required) — URL preferred (`shipperzinc.com`); company name acceptable as fallback.
2. **Stated needs / context** (recommended) — free text. Can include pain points, transcript snippets, deal notes, "they want X." More context = better demo.
3. **Optional demo agenda** — if the rep already knows the 3 things they want to show, paste them. If absent, the skill generates them.
4. **Optional folder of context** — path to a local folder OR Google Drive folder containing transcripts, PDFs, screenshots. Skill ingests as research input.

### Feature Showcase mode inputs

1. **Feature story / brain dump** (required) — ask for the user's explanation of what they are trying to show. Encourage messiness: Slack messages, bullets, "I need to show first touch vs last touch," screenshots, known objections, report examples, workflow notes. More is better.
2. **Requested feature(s)** (required) — one or more HubSpot features or outcomes. Examples: campaign attribution, custom events, journey analytics, deal-to-campaign reporting, lead scoring, workflow automation, forms + submissions, reporting dashboards.
3. **Audience and output context** (recommended) — content audience, enablement audience, customer type, recording/demo setting, what the audience should believe by the end.
4. **Optional company or brand URL** — use only for visual branding and vocabulary. If absent, create a neutral showcase company whose name reflects the story, e.g. "Campaign Attribution Showcase."
5. **Optional folder of context** — path to local or Drive materials. Skill ingests as story input.

## North star

In Demo mode, HubSpot's motto applies directly: **"solve for the customer."** Every choice — agenda, Easter egg, build prioritization, copy in branded assets — is judged against: *does this make the customer's business better?* Not: *does this show off HubSpot?*

In Feature Showcase mode, the goal is different: **prove the feature story with credible, audience-ready data.** Every choice is judged against: *does this make the feature obvious, believable, and easy to record or demo?* Not: *did we create the maximum number of objects?*

## Phases

### Phase 0: Wizard / smoke test (programmatic, never trusts user-stated state)

On first run: full setup wizard. Walks the user through HubSpot Private App creation, Personal Access Key generation, sandbox creation, optional dependency setup (Firecrawl, Perplexity, Recraft, Drive MCP). Uses direct deep links (`https://app.hubspot.com/private-apps/{HUB_ID}`, etc.) and offers Playwright automation for slow steps.

On subsequent runs: 5-second smoke test of all connections. Re-enters wizard only for what's actually broken.

Authoritative procedure: `references/setup-procedure.md`. Run it via:

```bash
bash ~/.claude/skills/hubspot-demo-prep/helpers/00-wizard.sh
```

Wizard persists state to `state/config.json`. Subsequent invocations read it.

**Hard gate:** the wizard verifies HubSpot Enterprise tier programmatically (custom-objects schema endpoint must return 200). If not Enterprise, halts with a clear error listing what won't work.

### Phase 1: Research or story capture

**Demo mode:** run the research workflow in parallel:

1. **Firecrawl** the company URL with `formats: ["markdown", "branding"]` to get site content + brand colors + logo. (Falls back to Playwright if Firecrawl fails on a JS-heavy site.)
2. **Playwright** screenshot of the homepage at 1440x900 — captures logo for the output Doc.
3. **Perplexity** with industry research prompts framed by the customer's signals: "pain points common to [industry] [size] businesses doing [GTM model]" — return only stats with citations.
4. **Ingest context folder** (if provided): read every text/markdown/PDF/screenshot. Use Claude's multimodal reading for screenshots. Summarize all of it as research input.

Outputs to `/tmp/demo-prep-<slug>/research.json`:
- `company`: name, industry, GTM model, target customer signals, services
- `branding`: primary hex, secondary hex, accent hex, logo URL, font family if detected
- `pain_points_stated`: bulleted list from rep's input
- `pain_points_inferred`: bulleted list from research, citing source
- `industry_stats`: array of `{stat, citation_url}`, only stats relevant to the agenda

**Feature Showcase mode:** if the user supplied a URL, run the same research workflow for branding and vocabulary. If no URL was supplied, synthesize `/tmp/demo-prep-<slug>/research.json` from the story:

- `mode`: `"feature_showcase"`
- `company`: neutral showcase company name, industry, and GTM model inferred from the feature story
- `branding`: neutral but polished defaults unless a brand URL provided colors/logo
- `stated_context`: the user's raw brain dump or concise summary
- `feature_showcase`: requested features, audience, story, success criteria, and shot-list hints
- `sources`: optional user-provided links/files; do not invent citations

### Phase 2: Synthesize the plan

Write `plan["mode"]` as `"demo"` or `"feature_showcase"` on every new plan. Omit only for backward compatibility with old v0.3.x plans, where consumers default to `"demo"`.

1. **Agenda / showcase-flow generation:**
   - **Demo mode:**
     - If user provided agenda → use it verbatim, with each item annotated with a "why this works for [customer]" line.
     - If no agenda → generate top 3 demo items aligned to "solve for the customer." Each item must:
       - Address a specific pain (stated or inferred)
       - Be visualizable in HubSpot (i.e., we can build something concrete to show)
       - Be ranked by customer business impact, not by HubSpot feature flashiness
   - **Feature Showcase mode:**
     - Generate a 3-5 step `agenda` that reads as a showcase flow, not a sales-call agenda.
     - Every item must map to at least one requested feature and one artifact the builder will create or a manual step the doc will honestly surface.
     - Prefer story labels like "Show first touch vs last touch," "Open the campaign-attributed deal," "Compare revenue by campaign," or "Trigger the association workflow" over generic feature names.

2. **Easter egg / adjacent-value selection:**
   - **Demo mode:** Use `references/easter-egg-catalog.md`. Filter to items that match the customer's ICP signals; exclude anything already on the agenda; pick by `customer_value` score. If a sales-heavy / no-marketing-team / lead-flow signal is present, lead scoring is almost always the right call.
   - **Feature Showcase mode:** Still include an Easter egg, but treat it as adjacent value: something connected to the feature story that strengthens the audience's understanding. It should answer "if you demo this, here is the related move that adds context, clarity, or value." For campaign attribution, strong adjacent-value ideas include: campaign influence workflow, first-touch vs last-touch comparison, revenue attribution caveat, attribution-toggle pre-stage warning, board-ready dashboard, or a source-quality cleanup view.

3. **Industry stats filtering:** Drop any stat that doesn't directly support an agenda item. *No padding allowed.* If an agenda item has no supporting stat, leave it without one.

4. **Build manifest planning:** From agenda/showcase flow + Easter egg + table-stakes list, decide what to actually build. Write the plan to `/tmp/demo-prep-<slug>/build-plan.json`:
   - Always (table stakes): 1 company, 5-10 contacts across personas, 1-3 deals, 1-2 tickets, deal pipeline, basic workflow, full activity timeline. If v0.4 funnel reports are planned, expand contacts to at least 30 so custom-event Sankey/funnel data has visible mass.
   - Conditional (only if relevant to agenda or Easter egg): custom object, custom event, marketing email, landing page, NPS form, lead scoring, additional workflows.
   - Quotes / invoices: only if explicitly relevant.
   - **Reports + dashboards (v0.4, conditional on digital-funnel signal):** see step 5b below.
   - **Feature Showcase mode:** Build only what supports the requested feature story, but make the data deep enough to record. For report/attribution stories, this usually means 30+ contacts, 3+ campaigns or source buckets, multiple deals with real amounts, and named sample records that the doc's shot list can link to.

5. **Plan content fields (v0.3.0 base + v0.4 extensions).** Authoritative base schema: `docs/punch-lists/2026-04-26-post-test-tweaks/plan-schema.md`. v0.4 adds reports/funnel fields in `docs/punch-lists/2026-04-28-reports-and-dashboards/plan-schema-v0.4.md`. Every consumer (`builder.py`, `doc_generator.py`, `playwright_phases_extras.py`) has a safe industry-neutral fallback if a field is missing — but the output only feels real if Phase 2 populates these with the prospect's or showcase story's vocabulary, not Shipperz's, not Boomer's, not the previous run's. Generate every field below using the prospect's industry, services, brand voice, or the feature-showcase story as the source of truth:

   - **`mode`** — `"demo"` or `"feature_showcase"`. Defaults to `"demo"` when missing.
   - **`feature_showcase`** (required when `mode == "feature_showcase"`) — `{story, requested_features, audience, success_criteria, shot_list, artifact_goals, easter_egg_strategy}`. This block drives doc language, showcase flow, and the quality gate.

   - **`branding`** — `primary_color`, `secondary_color`, `accent_color`, `neutral_dark`, `neutral_light` (hex). Pull from research.json branding; do NOT default to `#FF6B35` (transport orange). The doc + email + form theme all read from this.
   - **`property_group`** — `name` (e.g. `f"{slug}_demo_properties"`) and `label` (e.g. `f"Demo ({company_name})"`). Visible in HubSpot property admin; must not say "Shipperz Demo" for non-Shipperz prospects.
   - **`activity_content`** — pools used by `create_engagements`: `notes_pool`, `tasks_pool`, `calls_pool`, `meetings_pool`, `emails_pool`, plus optional `per_contact_engagements` for hand-tuned per-contact timelines. Also `lead_label_template` (e.g. `"{industry_noun} inquiry"`), `lead_labels`, `lead_sources`. Every body string should use this prospect's services, pain points, and industry terminology — not generic shipping/transport copy.
   - **`quote_catalog`** — 5-7 line items priced for this industry's actual deal sizes. A marine audio shop is not selling "enclosed transport"; an agency is not selling "premium service tier."
   - **`marketing_email`** — full structured body: `body_html` (inline-styled), `cta_text`, `cta_url`, `cta_color`, `footer_tagline` (company name only, no industry suffix), and `steps` (the "what happens next" timeline). CTA copy must match the prospect's actual website CTA pattern (B2B SaaS: "Schedule a demo"; local services: "Get a free quote"; product: "Shop now"). The hero image path is filled in by the image-gen step below.
   - **`marketing_campaign`** — `name`, `start_date`, `end_date`, `notes`, `audience`, `utm_campaign`. Replaces the legacy hardcoded "Snowbird Season Q1 2026". Pick a seasonal or topical angle that's actually relevant to this prospect.
   - **`campaign_attribution_showcase`** (recommended when the story mentions attribution, campaigns, first/last touch, or deal revenue by campaign) — plan at least 3 campaigns and define how contacts, source properties, custom events, forms/emails, deals, and workflow/manual steps support the attribution story. See `docs/punch-lists/2026-04-28-reports-and-dashboards/plan-schema-v0.4.md` for the schema and example.
   - **`forms[].theme`** — `submit_button_color` (defaults to `branding.primary_color`) and `submit_text_color`. For the NPS form, also include `forms[].test_submission_data`: `first_names`, `last_names`, `score_distribution`, `feedback_pool`. Use names + feedback that fit the prospect's customer base.

     **NPS field type — ALWAYS use `radio` with 10 options 1-10 (Fix E1, 2026-04-26).** The `number` field type forces free-text "type a 1-10" entry, which looks unprofessional and breaks the standard NPS UX pattern. Use `field_type: "radio"` for the score field. builder.py auto-populates the 10-option ladder when `options` is omitted on a radio field named `nps_score` (or any radio with `min:1, max:10`), so the plan can stay terse. NPS question wording: prefer the canonical Reichheld phrasing — *"On a scale of 1 to 10, how likely are you to recommend {company} to a friend or colleague?"* — over *"would you recommend...?"*. Optional follow-up: *"What's the primary reason for your score?"* instead of generic "Tell us about your experience".
   - **`recommendation_text`** — the doc's "how to lead the demo" paragraph. Generate prospect-specific copy that references real plan values (sample contact name, agenda items, custom object name). **Critical:** any dollar amount you cite MUST exist as a deal in the manifest. Otherwise omit the dollar amount. (See Quality Gate item 6 — phantom numbers killed the Boomer demo with a "$4,200 boat install" that never existed.)
   - **`playwright_dashboard`** — `name` (e.g. `f"{company_name} Daily Snapshot"`), `filter_pipeline_name` (matches the actual pipeline name in this plan), `filter_stages` (prospect-specific stage names). Required when `--playwright` is used; otherwise the dashboard inherits leftover Shipperz naming.
   - **`doc_replacement_id`** (optional) — Google Doc template ID override; replaces the legacy `if self.slug == "shipperzinc"` branching. Leave unset for default behavior.

5b. **Plan v0.4 fields — reports + funnel events.** Authoritative schema: `docs/punch-lists/2026-04-28-reports-and-dashboards/plan-schema-v0.4.md`. Authoritative report-bundle catalog: `references/best-reports-catalog.md`. Phase 2 emits these only when the prospect's research surfaces a **digital-funnel signal**.

   **Digital-funnel signal detection.** Read `research.json` and assess presence of:
   - Free-trial / signup / "demo CTA" language on the site
   - In-app product, dashboard CTAs, pricing tiers, "MRR / ARR / churn" vocabulary (B2B SaaS / PLG)
   - Cart / checkout / product catalog / Shopify mentions (e-commerce)
	   - "Quote / consultation / intake" + a high-volume top-of-funnel (legal, local services, services with web inquiry). A quote form alone is not enough; there must be evidence that repeatable funnel reporting would matter.
   - "RFQ / distributor / dealer" (industrial)
   - Multi-touch marketing program (paid + organic + email + content) — attribution use case

	   When **none** of these signals appear (e.g. a single-location restaurant, a B2B sales team with no marketing engine, a low-volume custom-shop services business with one-off bespoke work), **skip v0.4 fields entirely** — Phase 7 falls back to v0.3.0 random-fire `custom_events`, and the build records only the v0.3.0 starter dashboard/manual UI steps.

   When at least one signal **does** appear, generate:

   - **`custom_event_flows`** — one or more funnel-ordered event sequences. Pick the matching pattern from `references/best-reports-catalog.md` § "Custom event flow patterns" (or invent one keyed to the prospect's actual funnel — e.g. for a marketing-ops SaaS, `landing_viewed → demo_booked → demo_attended → trial_started → activated`). Use the catalog's drop-off rates as a starting point; tighten or loosen based on the prospect's stated conversion benchmarks if research surfaced any. Always vary drop-off step-by-step so the resulting Sankey isn't a single uninterrupted line.

   - **`playwright_reports.dashboards`** — pick 1-3 dashboard bundles from `references/best-reports-catalog.md` that match the prospect's signals. Rules:
     - Cap at 3 dashboards. One mega-dashboard always loses to 2-3 role-specific ones.
     - Each dashboard caps at 8-12 reports. More than that = info overload (per Vantage Point's 8-12 rule).
     - Mix visualization types — every plan should use at least 6 distinct viz types across all reports (KPI, gauge, line, bar, donut, table, funnel, Sankey, etc). All-bars = AI slop tell.
     - Name dashboards by **audience + outcome** (`"Acme — VP Marketing Funnel Health"`), never `"Sales Dashboard"`.
     - Reuse the prospect's brand color as the 30% secondary fill, HubSpot orange `#ff4800` as the 10% accent only — define a `color_dictionary` per dashboard.

	   - **Tier gating.** Sandbox `51393541` is on Marketing Hub Enterprise — full Sankey/journey/attribution menu is open. `builder.py` always writes `manifest["sandbox_tier"]`; for any other portal, provide `HUBSPOT_DEMOPREP_SANDBOX_TIER` or let the reports phase degrade unknown tiers per plan-schema-v0.4.md § "Tier degradation rules":
     - `marketing_pro`: substitute Sankey → vertical funnel, revenue attribution → contact-create attribution
     - `marketing_starter`: skip dashboards beyond starter; record manual_step

   - **Custom Journey + revenue attribution toggle.** When a dashboard includes a journey/attribution report on Marketing Enterprise, **flag it for the rep**: HubSpot's attribution reprocessing window can be up to 2 days when an event is first toggled as an interaction type (per knowledge.hubspot.com/analytics-tools/analyze-custom-behavioral-events). Phase 3 records this as a manual_step with the exact UI URL so the rep can pre-stage ≥48h before the demo.

   - **Funnel-data realism.** The Phase 7 firing strategy must produce a Sankey that doesn't look broken. Always:
     - Spread `contact_count` ≥ 30 contacts through the funnel (otherwise the chart is too thin)
     - Vary drop-off step-by-step so the chart shows movement, not a single straight line
     - Backdate `occurredAt` across a 30-60 day window with later steps biased to recent dates (momentum)
	     - Set `validate_via_get: true` — this confirms event schemas are reachable after firing. HubSpot does not expose a readback endpoint for historical custom-event occurrence counts.

6. **Generate the marketing email hero image.** Run this immediately before invoking `builder.py`. Detect available providers in priority order:

   1. **Recraft MCP** (preferred — free tier, 30 credits/day): if `mcp__recraft__generate_image` is callable in the orchestrator session, use it directly. Print `Using Recraft (free tier). Want to switch?` so the user can override.
   2. **OpenAI gpt-image-1**: if `OPENAI_API_KEY` is set in env, run `bash ${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/helpers/09-generate-hero.sh openai <slug>`.
   3. **Google Gemini imagen**: if `GEMINI_API_KEY` (or `GOOGLE_AI_STUDIO_KEY`) is set, run `bash ${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/helpers/09-generate-hero.sh gemini <slug>`.
   4. **None available**: skip image generation; `builder.py` will create the email without a hero (no manual step required).

   Once an image is generated to `/tmp/demo-prep-<slug>/hero-image.png`, write its path into `plan["marketing_email"]["hero_image_path"]` so `builder.py` uploads it. The user can override provider selection with `HUBSPOT_DEMO_HERO_PROVIDER=recraft|openai|gemini|none`.

7. **Phase 2 Quality Gate — must pass before invoking `builder.py`.** Before writing the final `build-plan.json`, run these checks mentally on the plan you just generated. If any check fails, fix the plan before continuing. The cost of failing here is a prospect or content audience noticing a "wait, this isn't real" detail — which kills the demo or recording.

   1. **Mode is explicit.** New plans set `mode`. Demo plans include a real company identifier. Feature Showcase plans include `feature_showcase.story` and at least one requested feature.
   2. **No terminology reuse from prior runs.** No phrasing carried over from a previous prospect. Search the plan you wrote for any of: `"shipment"`, `"snowbird"`, `"transport"`, `"vehicle"`, `"route"`, `"Tesla"`, `"marine"`, `"boat"`, `"audio"`, `"install"`, `"HVAC"`, `"furnace"` and confirm each instance is genuinely correct for THIS prospect/story — not an artifact of a prior run's leakage.
   3. **Persona freshness.** Re-infer contact personas from this prospect's `research.json` + industry + GTM model, or from the showcase audience/story. Don't reuse personas from any previous run.
   4. **Deal-stage specificity.** Pipeline stages reflect the prospect's actual sales cycle or the feature story's reporting need (e.g. SaaS: "Demo Scheduled / Proposal / Negotiation / Closed-won"; agency: "Discovery / Scope / Signed / Kickoff"; attribution showcase: "Campaign Influenced / SQL / Opportunity / Closed-won").
   5. **Custom object naming.** Object name reflects the prospect domain or feature story (`campaign_touchpoint` for an attribution showcase, not `shipment` for a campaign report).
   6. **Email voice-match.** Marketing email CTA style matches the prospect's website CTA pattern or the showcase story's asset being demonstrated.
   7. **No phantom numbers.** Any dollar amount cited in `recommendation_text` or any narrative field must correspond to an actual deal amount in the plan. (Recall the Boomer "$4,200 boat install" bug.)
   8. **Logo persistence (Fix F, 2026-04-26).** Confirm `plan["branding"]["logo_path"]` is set AND the file exists on disk when a brand URL was researched. If no brand URL exists in Feature Showcase mode, use intentional neutral branding and do not cite a missing logo path.
   9. **NPS form uses `radio` not `number` (Fix E1, 2026-04-26).** Any form whose name contains "NPS" or whose fields include `nps_score` MUST declare the score field as `field_type: "radio"`. The 1-10 options ladder is auto-populated by builder.py if omitted. Question wording follows the canonical Reichheld NPS prompt: *"On a scale of 1 to 10, how likely are you to recommend {company} to a friend or colleague?"*
   10. **Feature Showcase coverage.** When `mode == "feature_showcase"`, every requested feature must have at least one built artifact, planned report, or explicit manual step in the doc. Sample records named in the shot list must exist in `contacts`, `deals`, `campaign_attribution_showcase`, or manifest-linked assets.
   11. **Campaign attribution coherence.** When showing attribution, include multiple campaigns/source paths, first-touch and last-touch differences, contact-to-deal linkage, deal amounts that sum cleanly in reports, and a workflow/manual step for propagating campaign influence to deals if the public API cannot build that association directly.
   12. **Funnel-data realism (v0.4, when `custom_event_flows` is present).** For each flow: `firing_strategy.drop_off_rates` length equals `events.length - 1`; every value is between 0 and 1; values vary step-by-step (not a flat 0.6 across every step — produces a single-line Sankey); cumulative survivors do not collapse to 0 before the final step unless the flow intentionally models total abandonment; `contact_count` ≥ 20 (Sankey looks broken below 20); `date_range_days` ≥ 30 (gives the line chart room to show momentum).
   13. **Reports / events alignment (v0.4, when `playwright_reports` is present).** Every report whose `data_source: "custom_events"` references events that actually exist in some `custom_event_flows[].events[].name` (no orphan references). Every dashboard with a `tier_required: "marketing_enterprise"` report has a tier-degradation alternative noted in case the sandbox is downgraded. Each dashboard uses ≥ 4 distinct `viz_type` values (no all-bar dashboards). Each dashboard has ≤ 12 reports. Dashboard names follow audience-plus-outcome pattern (not "Sales Dashboard").

   If any check fails, fix the plan before continuing. The cost of failing here is someone noticing a "wait, this isn't really for me" detail — which kills the demo, showcase, or recording.

### Phase 3: Build + Output (single Python command, runs all 18 sub-phases incl. demo doc)

**Critical:** all build phases AND the formatted demo doc are produced by a single Python entry point: `builder.py`. Do NOT generate the demo doc yourself with the Drive MCP — `builder.py` calls `doc_generator.py` which produces a properly formatted .docx (banner, agenda status pills, links, branding) and uploads it to Drive. A markdown-only doc is a regression.

After Phase 1 (research) and Phase 2 (synthesize) have written `research.json` and `build-plan.json` to `/tmp/demo-prep-<slug>/`, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/builder.py" <slug>
```

Or, when running outside a plugin context (development):

```bash
python3 ~/.claude/skills/hubspot-demo-prep/skills/hubspot-demo-prep/builder.py <slug>
```

This runs all 18 phases monolithically:
- Properties, company, contacts, leads, pipeline + deals, tickets, engagements (parallel)
- Feature Showcase attribution support when `campaign_attribution_showcase` exists: creates safe first-touch/last-touch/source-path fields and patches sample contacts/deals so the presenter has real records to open
- Custom object + custom events (v0.4: funnel-ordered flows when `custom_event_flows` is present, varied drop-off so the resulting Sankey isn't a single line)
- Forms + form submissions
- Lead scoring + hot leads list
- Marketing email (with AI hero image when present)
- Workflows (best-effort via v4 flows API; graceful manual_step fallback)
- Quotes + invoices + calc property + marketing campaign
- **Phase 17 (v0.4, conditional on `playwright_reports`): Reports & dashboards** — the builder records the planned report bundle and delegates to Playwright when `create_reports_and_dashboards` is available. UI-only because HubSpot has no public reports/dashboards API. If the UI builder is unavailable, it writes `manifest["reports_status"].status = "blocked"` plus a manual step so the doc and verifier surface the gap honestly. When implemented, the phase builds 1-3 role-specific dashboards from the plan, each with 8-12 reports across mixed visualization types, tier-degrades gracefully (Sankey → vertical funnel on Marketing Pro), and writes `manifest["reports"]` + `manifest["dashboards_v04"]`.
- **Phase 18: Generate demo doc** — calls `doc_generator.py` to produce `/tmp/demo-prep-<slug>/demo-doc.docx` with full formatting (banner, agenda pills, links, brand colors, **Reporting section** when v0.4 dashboards exist), then uploads to the project's Drive folder. The Drive URL is returned and printed.

The verification loop runs alongside (including v0.4 reports/dashboard verification, retry-once on empty), and `manifest.json` records every artifact for cleanup.

**Manual-step reason hygiene.** Any `add_manual_step` call's `reason` string is USER-FACING — it gets rendered into the demo doc the prospect sees. Never put raw API error text there. Forbidden patterns in the visible reason: `"API returned"`, `"500"`, `"rejected"`, `"blocked"`, `"validation"`, `"INVALID_"`. Acceptable rephrases: "Built manually for finer control over branching", "UI build is faster than the API setup", "Configured by hand for advanced logic". The internal manifest can still record the raw error in a separate field for debugging — but the visible `reason` must read as an intentional choice, not a failure.

Optional flags:
- `--playwright` — also run Playwright UI flows for branding, workflows, quote template (off by default; selectors are still under iteration)
- `--first-run` — interactive HubSpot login for the first Playwright session (subsequent runs reuse storage state at `~/.claude/data/hubspot-demo-prep/state/`)

### Phase 4: Surface the result

After `builder.py` completes:
- Print the Drive URL of the generated demo doc (or local `.docx` path if Drive upload was skipped due to quota)
- Print the build summary (counts, errors, verifications X/Y)
- Surface the pass/fail status of the two new integrity verifiers `builder.py` runs at the end:
  - **`verify_doc_urls`** (item 6) — confirms every clickable link in the generated demo doc actually resolves to a live HubSpot artifact (no dead deep-links).
  - **`verify_manifest_integrity`** (item 13) — catches mismatches between configured vs. actual artifact counts (e.g. "8 form submissions configured, 0 recorded" — the Shipperz disconnect).
- **v0.4: print every dashboard URL** from `manifest["dashboards_v04"]` so the rep can preview before the demo. Surface any tier-degraded reports (Sankey → vertical funnel substitutions) with the manual_step recording the substitution.
- **v0.4: surface the attribution-toggle pre-stage warning** if any report uses revenue or deal-create attribution — HubSpot's reprocessing window is up to 2 days when an event is first toggled as an interaction type, so the rep needs to flip the toggle ≥48h before the demo.
- List any manual steps written to `manifest.json["manual_steps"]`
- Do NOT write or rewrite the demo doc yourself — it has already been generated and uploaded
- Doc renders a prominent "time saved vs manual build" stat at the top + breakdown table at the bottom, computed from manifest counts × per-phase minute estimates.

### Phase 5: Cleanup (when done with the demo)

```bash
bash helpers/cleanup.sh --slug=<customer-slug>
```

Deletes every asset tagged `demo_customer=<slug>`. Sandbox returns to the state of the previous run. Sample HubSpot contacts (Maria Johnson, Brian Halligan) preserved.

## Defaults (editable in `state/config.json`)

| Setting | Default | Why |
|---------|---------|-----|
| Activity level | `full` (notes + tasks + calls + meetings + emails + form submissions + page views) | Demo timelines should be scrollable and lived-in |
| Activity backdate | 90-180 days | Timeline must look real, not "all created today" |
| Custom events | define + fire 5-10 per contact | Defining without firing under-sells the capability |
| Lead scoring | conditional on sales-heavy ICP | Adds 1 property + 1 workflow + 1 list view when triggered |
| Sandbox cleanup prompt | Default no | New demo data is tagged separately; manual opt-in to wipe |
| Output format | Google Doc | Falls back to local Markdown if Drive MCP unavailable |
| Agenda items | 3 generated if not provided | "Solve for customer" priorities |
| Easter egg | Always shown, by customer-value not uniqueness | The "wow" moment |

## Composition

This skill composes with:
- `playwright-skill` — for screenshot capture during research and verification of created HubSpot UI
- `competitive-intelligence` — when the rep wants competitor benchmark context layered into the agenda
- `tech-stack-detector` — when an "external audit + demo prep" combined deliverable is needed

## Hard rules

1. **Never write to a non-sandbox HubSpot portal** unless the user explicitly overrides during wizard. Default = sandbox.
2. **Tag every demo asset** with `demo_customer=<slug>`. No exceptions. This is what makes cleanup safe.
3. **Programmatic verification of every capability** — never ask the user "do you have Enterprise?" Probe via API.
4. **Industry stats must support the agenda.** If a stat doesn't tie directly to an agenda item, drop it. No padding.
5. **Easter egg ranks by customer value, not novelty.** What helps this business win, not what's rare.
6. **Manual steps go in the output Doc with exact UI URLs.** Never leave the rep guessing what's incomplete.
7. **Deep-link every setup step** using the user's Hub ID. No "Settings → Integrations → ..." instructions when a URL works.
8. **Verify in production after build.** When the run completes, screenshot key HubSpot UI surfaces (contact timeline, workflow editor, landing page preview) so the rep can confirm before the demo.

## Failure modes the skill must handle gracefully

- Firecrawl DNS failure on the target domain → fall back to Playwright + Perplexity-only research, surface to rep
- HubSpot rate limit (429) → exponential backoff, don't abort the run
- Workflow API rejects a complex action → log to `manual-steps.json`, continue
- Drive MCP unavailable → output Doc as local Markdown at `/tmp/demo-prep-<slug>/demo-doc.md`, surface as fallback
- Custom event firing fails on first send → it's eventually consistent; retry once with delay
- Contact creation hits dedupe (existing email) → upsert instead of create

## Replication

This skill is designed to be hand-off-able. The README explains how someone else can install and use it. The `references/setup-procedure.md` doc captures every gotcha encountered in development so subsequent users skip the trial-and-error.
