# hubspot-demo-prep

Generate a tailored, lived-in HubSpot demo environment for a specific customer in minutes.

## What it does

Given a company URL + optional context, this skill:

1. **Researches** the prospect (Firecrawl scrape + Playwright homepage screenshot + Perplexity industry stats)
2. **Synthesizes** a demo agenda aligned to "solve for the customer" — uses the rep's agenda if provided, generates one if not, plus an Easter egg insight chosen by customer-value
3. **Builds** a tailored HubSpot demo dataset in your sandbox: contacts, companies, deals, tickets, custom objects, custom events, forms with submissions, branded marketing email + landing page, workflows (with lead scoring when sales-relevant), full backdated activity timelines
4. **Outputs** a Google Doc with the agenda, Easter egg, supporting research, manual-step callouts, and clickable links to every asset

## First-time setup (~5 min)

```bash
bash ~/.claude/skills/hubspot-demo-prep/helpers/00-wizard.sh
```

Wizard collects: parent Hub ID, Private App access token, Personal Access Key, then auto-creates a sandbox, sets up `hs` CLI, persists config to `state/config.json`. Verifies HubSpot Enterprise tier programmatically (custom-objects endpoint must respond 200) — halts on non-Enterprise.

Subsequent invocations just smoke-test connections (~5 seconds).

## Invocation

In Claude Code:
```
> Build a HubSpot demo for shipperzinc.com — they have no marketing team
  and want lead nurturing + general lead growth. Open to NPS surveys.
```

The skill activates on phrases like "demo prep for X", "build a HubSpot demo for X", "tailor a demo for X", or any explicit invocation by name.

## Architecture

```
~/.claude/skills/hubspot-demo-prep/
├── SKILL.md                  # entry, triggers, phase orchestration
├── README.md                 # this file
├── references/
│   ├── setup-procedure.md    # canonical wizard procedure (with gotchas)
│   ├── hubspot-api-reference.md
│   ├── easter-egg-catalog.md # ICP-keyed value adds
│   └── google-doc-template.md
├── helpers/
│   ├── lib.sh                # shared (auth, logging, HTTP, JSON, time, manifest)
│   ├── 00-wizard.sh          # interactive setup
│   ├── 01-research.sh        # Firecrawl + Playwright + Perplexity
│   ├── 02-seed-crm.sh        # company, contacts, pipeline, deals, tickets
│   ├── 03-engagements.sh     # backdated activity timelines
│   ├── 04-custom.sh          # custom objects + custom events
│   ├── 05-forms.sh           # forms + submissions
│   ├── 06-marketing.sh       # marketing email + landing page
│   ├── 07-workflows.sh       # workflows + lead scoring
│   ├── 08-output.sh          # Google Doc generation
│   └── cleanup.sh            # wipe by demo_customer tag
└── state/
    └── config.json           # persisted on first run
```

## Defaults (editable in `state/config.json`)

| Setting | Default | Override |
|---------|---------|----------|
| Activity level | `full` | `light` / `medium` / `full` |
| Activity backdate | 120 days | any integer |
| Custom event firing | on | toggle in config |
| Sandbox cleanup prompt | off | toggle in config |
| Output format | Google Doc | falls back to local markdown if Drive MCP unavailable |

## Hard rules

- Always writes to a sandbox by default. Production write only if user explicitly overrides during wizard.
- Every demo asset tagged `demo_customer=<slug>`. Cleanup is one bash call.
- Never asks "do you have Enterprise?" — verifies via API.
- Industry stats only included if they directly support an agenda item. No padding.
- Easter egg ranked by customer business value, not novelty.

## Cleanup

```bash
~/.claude/skills/hubspot-demo-prep/helpers/cleanup.sh --slug=<customer-slug>
```

Removes every asset tagged with that slug. Safe to re-run between customers. Sample HubSpot contacts (Maria Johnson, Brian Halligan) preserved.

## Replication

Hand this skill folder to anyone with: a HubSpot Enterprise account, the `hs` CLI installed, and `~/.claude/api-keys.env`. Run the wizard. The `references/setup-procedure.md` doc captures every gotcha encountered in the original build so they skip the trial-and-error.

## What this skill is NOT

- Not a HubSpot integration / SaaS product. Personal tool.
- Not a substitute for actual customer data — it's demo theater that *feels* real for a 30-min call.
- Not for production HubSpot portals (sandbox-first architecture).
- Not for non-Enterprise tiers (gates on custom objects).

## Known limitations (current version)

- Marketing email + landing page creation may require `hs upload` of a template before the API works. Skill logs to `manual-steps.json` if it fails.
- Workflow API can't create Send-Email / Send-SMS / AI-Step actions reliably — those are flagged in the output Doc.
- Sandbox API access tokens expire ~1 hour. For multi-hour demo runs, either generate a long-lived Private App in the sandbox (recommended) or rely on `hs` CLI auto-refresh.

## Support

Skill is maintained at `~/.claude/skills/hubspot-demo-prep/`. Issues / improvements: edit the helpers directly or open a session with Claude pointing at the punch list at `docs/punch-lists/`.
