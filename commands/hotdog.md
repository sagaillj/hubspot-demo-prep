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

Workflow:
1. Parse the input — extract the company URL/name and any pain points or agenda hints.
2. Run the skill's research phase (Firecrawl + Perplexity + screenshot).
3. Synthesize the demo agenda and build plan.
4. Execute the build (CRM seed, engagements, custom objects, marketing email, workflows, lead scoring).
5. Run the Playwright UI phases for items the API can't handle.
6. Generate the .docx demo runbook and upload to Drive.
7. Return the Google Doc URL plus a short summary of what was built.

If $ARGUMENTS is empty, ask the user for the prospect URL and any context they want included.
