# Google Doc Output Template

The skill produces one Google Doc per demo prep run. Below is the canonical structure; the helper at `helpers/08-output.sh` populates an HTML version of this and uploads to Drive (which auto-converts HTML → native Google Doc format).

## Filename pattern

`HubSpot Demo Prep — <CompanyName> — <YYYY-MM-DD>`

Example: `HubSpot Demo Prep — Shipperzinc — 2026-04-26`

## Drive folder

Default: a folder named `HubSpot Demo Prep` at root of the user's Drive. Wizard creates it on first run and persists the folder ID to `state/config.json`.

## Document structure

```
============================================================
HubSpot Demo Prep
[Customer name] · [demo date]
============================================================

[Brand strip: customer logo screenshot embedded, color swatches as colored
boxes labeled with hex codes — 3-5 colors max, primary first]

------------------------------------------------------------
Demo agenda (in order)
------------------------------------------------------------

1. [Item 1 title]
   Why it matters for [Customer]: [1-2 sentence rationale tied to their pain]
   What to show: [link to specific HubSpot record / workflow / report]
   Supporting stat: [data point + citation, only if it directly supports this item]

2. [Item 2 title]
   ...same shape...

3. [Item 3 title]
   ...same shape...

★ Easter egg — [Item title]                        [highlighted in brand color]
   Why it's the highest-leverage thing you didn't ask for: [rationale]
   What to show: [link]
   Supporting stat: [data point + citation]

------------------------------------------------------------
What was built in your demo portal
------------------------------------------------------------

Sandbox: [Sandbox name]   Hub ID: [ID]   [link to portal home]

[For each category, a bullet list of created artifacts with anchor links]

CRM
- Contact: [Persona name 1] — [link]
- Contact: [Persona name 2] — [link]
- Company: [Customer name] — [link]
- Deals: [N deals across the pipeline] — [link to pipeline view]
- Tickets: [N tickets] — [link to pipeline view]

Activity (backdated timeline)
- [N notes, M tasks, P calls, Q meetings, R emails, S form fills, T page views]
  spanning [Y] months across [Z] contacts
- Open the timeline of [Contact 1] to see — [link]

Workflows
- "[Workflow 1 name]" — [link]
- "[Workflow 2 name]" — [link]
- ⚠ Manual step before demo: [if any unsupported actions need UI completion]

Marketing email + landing page
- Email: "[email name]" — [link]
- Landing page: "[page name]" — [link]

Custom data (Enterprise-only, sandbox-isolated)
- Custom object: [name] with [N records] — [link to list view]
- Custom event: [name], [N occurrences fired across timeline] — [link to timeline]

Lead scoring (if applicable)
- Custom property: demo_lead_score
- Workflow: "[name]" — [link]
- Sorted list view: "Demo: Hot leads by score" — [link]

------------------------------------------------------------
Research summary
------------------------------------------------------------

[3-5 paragraphs synthesized from Firecrawl + Perplexity, summarizing:]
- Customer's positioning, services, target market
- Tech stack signals (CMS, marketing tools)
- Stated pain points (from rep's input)
- Implicit pain points (inferred from research)

Sources: [list of URLs cited]

------------------------------------------------------------
Manual steps before demo (if any)
------------------------------------------------------------

[For any HubSpot capability that the API couldn't fully build:]
- Open workflow "[name]" → [link] → add [missing action] step
  Why: API can create workflow shells but [send-email / SMS / AI step] needs UI

[If empty: "Nothing — everything is API-built and ready."]

------------------------------------------------------------
Pre-demo checklist
------------------------------------------------------------

[ ] Open [link to first contact] and verify timeline looks alive
[ ] Open [link to deal pipeline] and confirm deal distribution
[ ] Open [link to workflow] and confirm enrollment count > 0
[ ] Open [link to landing page] and check the branded preview
[ ] Open [link to lead score sorted list] (if applicable)
[ ] If manual workflow step needed (above), do it now

------------------------------------------------------------
Notes for the rep
------------------------------------------------------------

[1-2 paragraphs of demo-day talking points: how to weave the easter egg
in naturally, which artifacts to lead with, common objections to be ready for]

------------------------------------------------------------
Cleanup
------------------------------------------------------------

When done with this demo, run:
  ~/.claude/skills/hubspot-demo-prep/helpers/cleanup.sh --slug=[customer-slug]

This wipes everything tagged `demo_customer=[customer-slug]` from the sandbox.
Sample HubSpot contacts (Maria Johnson, Brian Halligan) are preserved.
============================================================
```

## Style notes

- Font: default Google Doc body (Arial 11pt). Headings use customer's primary brand color.
- Logo image: full-width across header strip if landscape, otherwise left-aligned at 200px width.
- Color swatches: rendered as small colored squares (40x40px) with hex code label below.
- Links: never bare URLs. Always anchor text. Open-in-new-tab is automatic for Drive Docs.
- Bullet style: hyphens, not bullets, for HTML→Doc compatibility.
- The "Manual steps before demo" section is suppressed if empty — don't show "Nothing." Just hide.

## Implementation in helpers/08-output.sh

The script:
1. Reads `/tmp/demo-prep-<slug>/manifest.json` (built by earlier helpers)
2. Renders an HTML template with all values filled
3. Inlines the logo as `<img src="data:image/png;base64,...">` for transport into the Doc
4. Uploads to Drive via the MCP `create_file` with `mimeType: text/html` (Drive auto-converts to GDoc)
5. Returns the Doc ID + URL
