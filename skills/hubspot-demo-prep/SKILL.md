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

### Phase 3: Build (parallel where dependencies allow)

Sequential by dependency (pipelines before deals, schemas before custom records, etc.); within each layer, batch where possible.

```bash
SLUG=<customer-slug>  # e.g., shipperzinc

bash helpers/02-seed-crm.sh "$SLUG"        # company, contacts, pipelines, deals, tickets
bash helpers/03-engagements.sh "$SLUG"      # backdated activity timeline
bash helpers/04-custom.sh "$SLUG"           # custom objects, custom events (if needed)
bash helpers/05-forms.sh "$SLUG"            # form creation + submissions
bash helpers/06-marketing.sh "$SLUG"        # marketing email + landing page (if needed)
bash helpers/07-workflows.sh "$SLUG"        # workflows + lead scoring
```

Each helper:
- Reads `/tmp/demo-prep-<slug>/build-plan.json` for what to build
- Reads `/tmp/demo-prep-<slug>/research.json` for branding/copy inputs
- Writes back to `/tmp/demo-prep-<slug>/manifest.json` recording every created artifact (id, name, URL, type)
- Tags every asset with the custom property `demo_customer = <slug>` for cleanup

For workflow actions the API can't handle (Send Email, Send SMS, AI Step, complex branching), the helper:
- Builds the workflow shell up to the unsupported action
- Logs the gap to `/tmp/demo-prep-<slug>/manual-steps.json` with: workflow name, step name, what to add, exact UI URL

### Phase 4: Output

```bash
bash helpers/08-output.sh "$SLUG"
```

Generates a Google Doc per `references/google-doc-template.md`:
- Customer name + date in title
- Logo screenshot + color swatches at the top
- Demo agenda (3 items + Easter egg as 4th, or 4 items if rep provided agenda)
- "What was built" with clickable links to every artifact in HubSpot
- Research summary (3-5 paragraphs, sources cited)
- "Manual steps before demo" (if any)
- Pre-demo checklist
- Cleanup command
- Doc lives in a "HubSpot Demo Prep" Drive folder (created on first run)

Returns the Doc URL.

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
