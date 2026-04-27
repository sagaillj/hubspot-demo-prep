---
description: HubSpot Hot Dog — prep a tailored HubSpot demo environment for a prospect
argument-hint: <company URL or name> [optional pain points or agenda]
---

First, run this Bash command to print the colored banner directly to the terminal (ANSI escapes will render in color):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/helpers/banner.sh"
```

Then invoke the **hubspot-demo-prep** skill.

Customer input: $ARGUMENTS

## Workflow

1. **Parse the input** — extract the company URL/name and any pain points or agenda hints. If $ARGUMENTS is empty, ask the user for the prospect URL and any context.

2. **Phase 1: Research.** Run the research helper, which executes Firecrawl, Playwright screenshot, and Perplexity in parallel and writes `research.json` to `/tmp/demo-prep-<slug>/`. Skips automatically if a fresh `research.json` (<24h old) already exists for that slug:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/helpers/01-research.sh" <slug> <url> "<optional context>"
   ```

3. **Phase 2: Synthesize the demo plan.** Read `research.json`, write `build-plan.json` to the same work dir. The plan captures: 3-item agenda + Easter egg, list of artifacts to build, branding inputs (colors, logo).

4. **Phase 3 + 4: Build + Doc.** Run the single Python entry point. It runs all 17 sub-phases (CRM seed, engagements, custom objects, forms, marketing email, workflows, lead scoring, quotes, invoices, marketing campaign) AND generates the formatted .docx demo runbook + uploads to Drive in one shot:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/builder.py" <slug>
   ```
   Add `--playwright` for the optional UI phases (branding upload, workflow creation via UI, quote template, etc.). Add `--first-run` if no HubSpot login state is cached yet.

5. **Surface the results.** Print the Drive URL of the demo doc (parsed from the build's last log line `demo doc → <URL>`), the build summary (counts, errors, verifications X/Y), and any manual steps from `manifest.json`.

## CRITICAL — do NOT generate the doc yourself

The Python script (`builder.py` → `doc_generator.py`) produces a fully-formatted .docx with:
- A branded banner header (logo + brand colors)
- Status pills inline with the agenda items (`[BUILT]`, `[BUILD LIVE]`, `[NOT BUILT]`, `[ANALOG]`)
- Clickable links to every HubSpot artifact
- Two-page layout (page 1 = print-ready runbook, page 2 = supporting research + checklist)

If you skip the Python doc generation and write markdown into a Drive doc yourself with the Drive MCP, the result is a regression: raw markdown rendered as plain text, no banner, no pills, no formatting. **Do not do this.** Run `builder.py` and trust its doc output.
