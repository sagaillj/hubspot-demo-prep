---
name: hubspot-demo-prep
description: Generate a tailored, "live"-feeling HubSpot demo environment for a specific customer in minutes. Researches the prospect (Firecrawl + Playwright + Perplexity), builds an ICP-realistic CRM dataset (contacts, companies, deals, tickets, custom objects, custom events), drives form submissions and engagement activity backdated months, generates a branded marketing email + landing page, configures workflows including lead scoring, then outputs a Google Doc with the agenda, Easter egg insight, and clickable links to every demo asset. Triggers on "prep a demo for X", "demo prep", "build me a demo for [company]", "tailor a HubSpot demo", "demo for [company URL]", "set up a customer demo", or any request to create custom-tailored HubSpot demo data for a specific business.
user-invokable: true
argument-hint: "[company-url-or-name] [optional context: pain points, agenda, transcript path]"
---

# HubSpot Demo Prep Skill

Build a tailored HubSpot demo environment for a specific customer. Solve for the customer.

## When to use

- Prepping for a sales call where you want demo data that mirrors the prospect's industry / ICP / pain
- Recording a demo for a specific company and need it to feel real
- Creating a sales-engineering practice environment
- Demonstrating HubSpot capabilities to someone outside your typical demo flow

## Inputs

The user provides:

1. **Company identifier** (required) — URL preferred (`shipperzinc.com`); company name acceptable as fallback.
2. **Stated needs / context** (recommended) — free text. Can include: pain points, transcript snippets, deal notes, "they want X." More context = better demo.
3. **Optional demo agenda** — if the rep already knows the 3 things they want to show, paste them. If absent, the skill generates them.
4. **Optional folder of context** — path to a local folder OR Google Drive folder containing transcripts, PDFs, screenshots. Skill ingests as research input.

## North star

HubSpot's motto: **"solve for the customer."** Every choice — agenda, Easter egg, build prioritization, copy in branded assets — is judged against: *does this make the customer's business better?* Not: *does this show off HubSpot?*

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

### Phase 1: Research

Run in parallel:

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

### Phase 2: Synthesize the demo plan

1. **Demo agenda generation:**
   - If user provided agenda → use it verbatim, with each item annotated with a "why this works for [customer]" line.
   - If no agenda → generate top 3 demo items aligned to "solve for the customer." Each item must:
     - Address a specific pain (stated or inferred)
     - Be visualizable in HubSpot (i.e., we can build something concrete to show)
     - Be ranked by customer business impact, not by HubSpot feature flashiness

2. **Easter egg selection:** Use `references/easter-egg-catalog.md`. Filter to items that match the customer's ICP signals; exclude anything already on the agenda; pick by `customer_value` score. If a sales-heavy / no-marketing-team / lead-flow signal is present, lead scoring is almost always the right call.

3. **Industry stats filtering:** Drop any stat that doesn't directly support an agenda item. *No padding allowed.* If an agenda item has no supporting stat, leave it without one.

4. **Build manifest planning:** From agenda + Easter egg + table-stakes list, decide what to actually build. Write the plan to `/tmp/demo-prep-<slug>/build-plan.json`:
   - Always (table stakes): 1 company, 5-10 contacts across personas, 1-3 deals, 1-2 tickets, deal pipeline, basic workflow, full activity timeline.
   - Conditional (only if relevant to agenda or Easter egg): custom object, custom event, marketing email, landing page, NPS form, lead scoring, additional workflows.
   - Quotes / invoices: only if explicitly relevant.

5. **Plan content fields (v0.3.0).** Authoritative schema: `docs/punch-lists/2026-04-26-post-test-tweaks/plan-schema.md`. Every consumer (`builder.py`, `doc_generator.py`, `playwright_phases_extras.py`) has a safe industry-neutral fallback if a field is missing — but the demo only feels real if Phase 2 actually populates these with the prospect's vocabulary, not Shipperz's, not Boomer's, not the previous run's. Generate every field below using the prospect's industry, services, and brand voice as the source of truth:

   - **`branding`** — `primary_color`, `secondary_color`, `accent_color`, `neutral_dark`, `neutral_light` (hex). Pull from research.json branding; do NOT default to `#FF6B35` (transport orange). The doc + email + form theme all read from this.
   - **`property_group`** — `name` (e.g. `f"{slug}_demo_properties"`) and `label` (e.g. `f"Demo ({company_name})"`). Visible in HubSpot property admin; must not say "Shipperz Demo" for non-Shipperz prospects.
   - **`activity_content`** — pools used by `create_engagements`: `notes_pool`, `tasks_pool`, `calls_pool`, `meetings_pool`, `emails_pool`, plus optional `per_contact_engagements` for hand-tuned per-contact timelines. Also `lead_label_template` (e.g. `"{industry_noun} inquiry"`), `lead_labels`, `lead_sources`. Every body string should use this prospect's services, pain points, and industry terminology — not generic shipping/transport copy.
   - **`quote_catalog`** — 5-7 line items priced for this industry's actual deal sizes. A marine audio shop is not selling "enclosed transport"; an agency is not selling "premium service tier."
   - **`marketing_email`** — full structured body: `body_html` (inline-styled), `cta_text`, `cta_url`, `cta_color`, `footer_tagline` (company name only, no industry suffix), and `steps` (the "what happens next" timeline). CTA copy must match the prospect's actual website CTA pattern (B2B SaaS: "Schedule a demo"; local services: "Get a free quote"; product: "Shop now"). The hero image path is filled in by the image-gen step below.
   - **`marketing_campaign`** — `name`, `start_date`, `end_date`, `notes`, `audience`, `utm_campaign`. Replaces the legacy hardcoded "Snowbird Season Q1 2026". Pick a seasonal or topical angle that's actually relevant to this prospect.
   - **`forms[].theme`** — `submit_button_color` (defaults to `branding.primary_color`) and `submit_text_color`. For the NPS form, also include `forms[].test_submission_data`: `first_names`, `last_names`, `score_distribution`, `feedback_pool`. Use names + feedback that fit the prospect's customer base.

     **NPS field type — ALWAYS use `radio` with 10 options 1-10 (Fix E1, 2026-04-26).** The `number` field type forces free-text "type a 1-10" entry, which looks unprofessional and breaks the standard NPS UX pattern. Use `field_type: "radio"` for the score field. builder.py auto-populates the 10-option ladder when `options` is omitted on a radio field named `nps_score` (or any radio with `min:1, max:10`), so the plan can stay terse. NPS question wording: prefer the canonical Reichheld phrasing — *"On a scale of 1 to 10, how likely are you to recommend {company} to a friend or colleague?"* — over *"would you recommend...?"*. Optional follow-up: *"What's the primary reason for your score?"* instead of generic "Tell us about your experience".
   - **`recommendation_text`** — the doc's "how to lead the demo" paragraph. Generate prospect-specific copy that references real plan values (sample contact name, agenda items, custom object name). **Critical:** any dollar amount you cite MUST exist as a deal in the manifest. Otherwise omit the dollar amount. (See Quality Gate item 6 — phantom numbers killed the Boomer demo with a "$4,200 boat install" that never existed.)
   - **`playwright_dashboard`** — `name` (e.g. `f"{company_name} Daily Snapshot"`), `filter_pipeline_name` (matches the actual pipeline name in this plan), `filter_stages` (prospect-specific stage names). Required when `--playwright` is used; otherwise the dashboard inherits leftover Shipperz naming.
   - **`doc_replacement_id`** (optional) — Google Doc template ID override; replaces the legacy `if self.slug == "shipperzinc"` branching. Leave unset for default behavior.

6. **Generate the marketing email hero image.** Run this immediately before invoking `builder.py`. Detect available providers in priority order:

   1. **Recraft MCP** (preferred — free tier, 30 credits/day): if `mcp__recraft__generate_image` is callable in the orchestrator session, use it directly. Print `Using Recraft (free tier). Want to switch?` so the user can override.
   2. **OpenAI gpt-image-1**: if `OPENAI_API_KEY` is set in env, run `bash ${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/helpers/09-generate-hero.sh openai <slug>`.
   3. **Google Gemini imagen**: if `GEMINI_API_KEY` (or `GOOGLE_AI_STUDIO_KEY`) is set, run `bash ${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/helpers/09-generate-hero.sh gemini <slug>`.
   4. **None available**: skip image generation; `builder.py` will create the email without a hero (no manual step required).

   Once an image is generated to `/tmp/demo-prep-<slug>/hero-image.png`, write its path into `plan["marketing_email"]["hero_image_path"]` so `builder.py` uploads it. The user can override provider selection with `HUBSPOT_DEMO_HERO_PROVIDER=recraft|openai|gemini|none`.

7. **Phase 2 Quality Gate — must pass before invoking `builder.py`.** Before writing the final `build-plan.json`, run these 6 checks mentally on the plan you just generated. If any check fails, fix the plan before continuing. The cost of failing here is a prospect noticing a "wait, this isn't really for me" detail — which kills the demo.

   1. **No terminology reuse from prior runs.** No phrasing carried over from a previous prospect. Search the plan you wrote for any of: `"shipment"`, `"snowbird"`, `"transport"`, `"vehicle"`, `"route"`, `"Tesla"`, `"marine"`, `"boat"`, `"audio"`, `"install"`, `"HVAC"`, `"furnace"` and confirm each instance is genuinely correct for THIS prospect's industry — not an artifact of a prior run's leakage.
   2. **Persona freshness.** Re-infer contact personas from this prospect's `research.json` + industry + GTM model. Don't reuse personas from any previous run.
   3. **Deal-stage prospect-specificity.** Pipeline stages reflect this prospect's actual sales cycle (e.g. SaaS: "Demo Scheduled / Proposal / Negotiation / Closed-won"; agency: "Discovery / Scope / Signed / Kickoff"; services: "Inquiry / Quote / Scheduled / Completed").
   4. **Custom object naming.** Object name reflects the prospect's domain (`audio_installation_job` not `shipment` for a marine audio shop).
   5. **Email voice-match.** Marketing email CTA style matches the prospect's actual website CTA pattern (B2B SaaS: "Schedule a demo"; local services: "Get a free quote"; product: "Shop now").
   6. **No phantom numbers.** Any dollar amount cited in `recommendation_text` or any narrative field must correspond to an actual deal amount in the plan. (Recall the Boomer "$4,200 boat install" bug.)
   7. **Logo persistence (Fix F, 2026-04-26).** Confirm `plan["branding"]["logo_path"]` is set AND the file exists on disk. The doc banner + marketing email header strip both depend on it; without it, both look generic. Phase 1 (`helpers/01-research.sh`) always runs a Playwright logo screenshot to `{work_dir}/logo.png` and writes the path into `research.branding.logo_path` — Phase 2 must copy that path into `plan["branding"]["logo_path"]`. If the screenshot file is missing (Playwright failed entirely on a JS-heavy site), fall back to `research.branding.logo_url` (the og:image / favicon Firecrawl returned), or omit the logo entirely. Do NOT cite a logo path that doesn't exist on disk — builder.py will silently skip the upload and the demo will look generic.
   8. **NPS form uses `radio` not `number` (Fix E1, 2026-04-26).** Any form whose name contains "NPS" or whose fields include `nps_score` MUST declare the score field as `field_type: "radio"`. The 1-10 options ladder is auto-populated by builder.py if omitted. Question wording follows the canonical Reichheld NPS prompt: *"On a scale of 1 to 10, how likely are you to recommend {company} to a friend or colleague?"*

   If any check fails, fix the plan before continuing. The cost of failing here is a prospect noticing a "wait, this isn't really for me" detail — which kills the demo.

### Phase 3: Build + Output (single Python command, runs all 17 sub-phases incl. demo doc)

**Critical:** all build phases AND the formatted demo doc are produced by a single Python entry point: `builder.py`. Do NOT generate the demo doc yourself with the Drive MCP — `builder.py` calls `doc_generator.py` which produces a properly formatted .docx (banner, agenda status pills, links, branding) and uploads it to Drive. A markdown-only doc is a regression.

After Phase 1 (research) and Phase 2 (synthesize) have written `research.json` and `build-plan.json` to `/tmp/demo-prep-<slug>/`, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/builder.py" <slug>
```

Or, when running outside a plugin context (development):

```bash
python3 ~/.claude/skills/hubspot-demo-prep/skills/hubspot-demo-prep/builder.py <slug>
```

This runs all 17 phases monolithically:
- Properties, company, contacts, leads, pipeline + deals, tickets, engagements (parallel)
- Custom object + custom events
- Forms + form submissions
- Lead scoring + hot leads list
- Marketing email (with AI hero image when present)
- Workflows (best-effort via v4 flows API; graceful manual_step fallback)
- Quotes + invoices + calc property + marketing campaign
- **Phase 17: Generate demo doc** — calls `doc_generator.py` to produce `/tmp/demo-prep-<slug>/demo-doc.docx` with full formatting (banner, agenda pills, links, brand colors), then uploads to the project's Drive folder. The Drive URL is returned and printed.

The verification loop runs alongside (16 phase verifications, retry-once on empty), and `manifest.json` records every artifact for cleanup.

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
