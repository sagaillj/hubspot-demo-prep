# Handoff — hubspot-demo-prep next-iteration session
**Created:** 2026-04-26 night, end of v0.3.1 ship
**Context:** previous orchestration session got long; opening a fresh chat

---

## Current state (post-v0.3.1)

- **Repo:** `~/.claude/skills/hubspot-demo-prep` (GitHub: https://github.com/sagaillj/hubspot-demo-prep)
- **Latest commit on `main`:** `8a771e6 v0.3.1: Walkthrough fixes + top-10% polish iteration`
- **Plugin installed:** `hubspot-demo-prep@hubspot-demo-prep 0.3.1` (verify: `claude plugin list | grep hubspot`; if it shows 0.3.0, run `claude plugin update hubspot-demo-prep@hubspot-demo-prep` and restart Claude Code)
- **Sandbox:** portal `51393541`. PAK at `HUBSPOT_DEMOPREP_SANDBOX_TOKEN` in `~/.claude/api-keys.env`
- **HubSpot login state cached at:** `~/.claude/data/hubspot-demo-prep/state/portal-51393541-hubspot.json`
- **Friday 2026-05-01 demo recording** is in **5 days**

## Read first (mandatory context)

1. `~/.claude/skills/hubspot-demo-prep/HANDOFF.md` — full release history (v0.1 → v0.3.1) including the v0.3.1 walkthrough findings
2. `~/.claude/skills/hubspot-demo-prep/skills/hubspot-demo-prep/SKILL.md` — current skill instructions including Phase 2 Quality Gate (8 mandatory checks)
3. `~/.claude/skills/hubspot-demo-prep/skills/hubspot-demo-prep/docs/punch-lists/2026-04-26-post-test-tweaks/plan-schema.md` — locked plan/builder contract
4. `/tmp/demo-prep-1800law1010/` — last full verify run on a real prospect (Harding Mazzotti, consumer PI law). May or may not survive a reboot. If gone, regenerate with `/hotdog 1800law1010.com`.

## Critical directives (carried over)

- **Top 10% lens** — every deliverable (doc, email, form, dashboard, report) must look top 10%. Not "functional" — visually stunning, brand-consistent, makes HubSpot look good. If it looks like AI slop, the skill defeats itself. **This is the single most important standard.**
- **No em-dashes** when writing on Jeremy's behalf (CLAUDE.md preference).
- **Subagent pattern** for non-trivial work — parallel subagents for sweeps + implementation; Opus for orchestration/review, Sonnet for impl. (Reads memory: `feedback_subagents_models.md`.)
- **Two-pass adversarial review before ship**: codex:rescue (Codex) + Opus self-review. Iterate until both return zero blockers. (Reads: `feedback_adversarial_review.md`, `feedback_overnight_review_loop.md`.)
- **Production verify on a fresh non-Shipperz, non-Boomer, non-1800LAW1010 prospect** before declaring done. Generic-genericization holds when the deliverable for an unseen industry reads as native to that industry.

## v0.3.1 verify result on Harding Mazzotti (1800LAW1010)

API layer is now solid: 18/18 phases passed, 14/14 form submissions (was 0/N before the `api.hsforms.com` host fix), `manifest_integrity` passes, `doc_url_verification` passes. All 6 walkthrough fixes landed (logo+title doc header, time-saved reword, pipeline shows deals, Priya 1× association, NPS API radio scale, logo extraction across doc + email + portal-branding-where-allowed).

**Drive doc from latest run:** https://docs.google.com/document/d/14FwzdZGBAoBcsFwM_Gb3LY49F5sQ91tF5w3o9nhC9sc/edit

---

## NEW scope for this session: Reports + analytics polish (Jeremy's just-stated direction)

> "Custom events Sankey diagram showing somebody clicking into somebody's portal — for a customer that might have a SaaS use case. Customer journey analytics and revenue attribution — those are always key things that people ask for. Reporting in general: clean stuff that looks really nice. Research the best-looking HubSpot reports and try to replicate some based on the client's use case. If they're asking for sales, having really clean, beautiful reports that look almost like a designer designed them. Use all of the different HubSpot visuals available."

### Concrete deliverables

For prospects with the right shape (heuristic: SaaS, B2B services with digital funnel, e-commerce), `/hotdog` should also build:

1. **Custom event funnel / Sankey** — multi-step events that tell a real story for the prospect's product. For SaaS: `page_viewed → feature_clicked → signup_started → signup_completed → first_value_action`. Render via HubSpot's Custom Report Builder Sankey chart (Marketing Hub Pro+) OR a multi-card dashboard if Sankey not available.

2. **Customer journey analytics** — the chronological story of a sample contact's engagements + page views + form fills + email opens. HubSpot has Customer Journey Analytics (Marketing Hub Enterprise) but Pro+ can build session paths via reporting.

3. **Revenue attribution report** — which marketing source drove the most pipeline / closed-won. HubSpot has multi-touch attribution (Marketing Hub Pro+).

4. **Industry-appropriate sales reports** — clean, designer-quality dashboards using the right HubSpot visuals per vertical. Use ALL the visualization types HubSpot offers (gauges, funnels, Sankeys, heat maps, cohort tables, etc.) where they fit, not just bar charts everywhere.

### Suggested implementation approach

- **Phase 0/1 research extension**: detect "is this prospect SaaS / has a digital funnel?" from `research.json` (industry, GTM model, services). Signals: trial/signup mentions, app/dashboard CTAs, pricing pages with tiers, "free trial" / "demo" CTAs.
- **Phase 2 plan extension**: when the prospect fits the funnel pattern, the orchestrator generates:
  - 5-7 custom events with realistic names + property definitions for the prospect's actual funnel
  - 30-50 firings of these events across contacts (in funnel order so the Sankey shows meaningful drop-off)
  - A new `reports` block in the plan describing the dashboards/charts to build
- **Phase 3 build extension**:
  - `create_custom_events` already exists (Phase 7) — extend to fire in funnel order with realistic conversion rates (e.g. 100% → 60% → 35% → 20% → 12%).
  - New phase: `create_dashboards_and_reports` — HubSpot Reports & Dashboards v3 APIs (`/cms/v3/reports/...`, `/dashboards/v3/...`). API-first; Playwright polish for fine-tuning visuals where API doesn't expose layout/style controls.
- **Doc generator update**: render dashboard URLs in the agenda + add a "Reporting" section in the doc.

### Research first

Before building, do a research pass:

- Firecrawl + Perplexity for: HubSpot's published "best dashboards" examples, knowledge.hubspot.com Report Builder docs, customer-success blog posts featuring real dashboards.
- Find 3-5 "designer-quality" reference reports per industry (SaaS, services, e-commerce) to anchor the visual bar.
- Document in new `references/best-reports-catalog.md` so Phase 2 syntheses can reference it.

---

## Three carryover items from v0.3.1

1. **NPS form visual on sandbox** — API ships `radio` + 10 options + Reichheld phrasing correctly. Visual on Marketing Hub Free/Starter sandboxes shows vertical radio stack + default-orange submit button (HubSpot's tier limitation, not the skill's). Resolved on Pro+ via `polish_nps_form` Playwright phase.
   - **Decision before Friday:** pre-stage form's horizontal layout via UI once on the demo sandbox, OR confirm the demo sandbox is on Pro+, OR accept vertical-stack appearance.

2. **Pipeline deep-link belt-and-suspenders** — now emits both `?pipeline=` and `?pipelineId=`. If HubSpot drops both in a future UI rev, the post-build PATCH loop still confirms data integrity at the API level.
   - **Action:** spot-check on the Friday demo that the link auto-switches pipeline view.

3. **HubSpot login state cache freshness** — `~/.claude/data/hubspot-demo-prep/state/portal-51393541-hubspot.json` may expire before Friday.
   - **Action:** Thursday, run `python3 builder.py <slug> --playwright --first-run` once to refresh. Or schedule a `keep-warm` cron via the `/schedule` skill.

---

## Suggested 5-day plan

| Day | Date | Focus |
|-----|------|-------|
| Sun/Mon | 2026-04-27 / 28 | Research best-in-class HubSpot dashboards. Document in `references/best-reports-catalog.md`. Update plan-schema.md with new `reports` + `custom_event_flows` blocks. Update SKILL.md Phase 2 to detect SaaS prospects + plan the right reports. |
| Tue | 2026-04-29 | Implement `create_dashboards_and_reports` builder phase. Extend `create_custom_events` for funnel-ordered firings. Wire into Builder.run(). Doc generator: render dashboard URLs + add "Reporting" agenda section. |
| Wed | 2026-04-30 | New Playwright phase for dashboard layout polish (if API doesn't expose all styling). codex:rescue + Opus reviews. Apply review findings. |
| Thu | 2026-05-01 | End-to-end run on a fresh SaaS prospect (suggest a small B2B SaaS or martech tool). Refresh HubSpot login state cache. ui-ux-pro-max review of the dashboards specifically. |
| **Fri** | **2026-05-01** | **Demo recording.** Pre-flight: confirm sandbox is clean, login state is fresh, sample run is good. /hotdog kicks off the LinkedIn recording. |

---

## Setup state the next session can rely on

- `~/.claude/api-keys.env` — has all the relevant API keys (HUBSPOT_DEMOPREP_SANDBOX_TOKEN, OPENAI_API_KEY, GEMINI_API_KEY, FIRECRAWL_API_KEY, PERPLEXITY_API_KEY)
- `~/.claude/bin/firecrawl`, `~/.claude/bin/perplexity` — local CLI wrappers (memory: `feedback_perplexity_firecrawl_wrappers.md`)
- Recraft MCP — available in session for hero image generation
- Drive MCP — available for doc upload
- Playwright (Python + Node) — installed and working

---

## Paste-ready re-prompt for the next chat

```
Resuming hubspot-demo-prep, fresh session.

Read ~/.claude/skills/hubspot-demo-prep/skills/hubspot-demo-prep/docs/punch-lists/handoff-2026-04-26-night.md
for the full handoff. TL;DR:

- v0.3.1 shipped to main (commit 8a771e6); plugin installed at 0.3.1
- Friday 2026-05-01 demo recording is in 5 days
- API layer is solid; v0.3.1 verify on Harding Mazzotti passed all
  6 walkthrough fixes
- NEW scope this session: reports + analytics polish — custom events
  Sankey for SaaS, customer journey analytics, revenue attribution,
  designer-quality industry-appropriate dashboards using all of
  HubSpot's visualization types
- 3 carryover items: NPS form sandbox visual, pipeline deep-link
  monitor, HubSpot login state cache refresh
- Top-10% lens still applies — every output must look top 10%

Start by reading the handoff doc, then do a research pass on
best-in-class HubSpot dashboards before scoping the implementation.

Subagent pattern + parallel agents preferred. Two-pass adversarial
review (codex:rescue + Opus) before ship. Production verify on a
fresh non-prior-prospect.
```

---

## Files of note in the v0.3.1 codebase

| Path | Purpose |
|------|---------|
| `skills/hubspot-demo-prep/SKILL.md` | Skill instructions + Phase 2 Quality Gate |
| `skills/hubspot-demo-prep/builder.py` (~3170 lines after v0.3.1) | Phase 3 executor — all 18 build phases + 2 verifiers |
| `skills/hubspot-demo-prep/doc_generator.py` | Doc rendering — logo+title header, agenda, time-saved hero, sections |
| `skills/hubspot-demo-prep/playwright_phases.py` | UI flows — branding upload, workflow build, NPS polish, etc. |
| `skills/hubspot-demo-prep/playwright_phases_extras.py` | Dashboard + saved views (where the Sankey work would extend) |
| `skills/hubspot-demo-prep/time_estimates.py` | "Saved ~Xh" hero stat computation |
| `skills/hubspot-demo-prep/helpers/01-research.sh` | Phase 1 research with Playwright logo capture |
| `skills/hubspot-demo-prep/helpers/09-generate-hero.sh` | OpenAI/Gemini hero image fallback |
| `skills/hubspot-demo-prep/helpers/cleanup.sh` | Slug-based teardown |
| `skills/hubspot-demo-prep/references/` | Reference docs Phase 2 reads during synthesis |
| `commands/hotdog.md` | Slash command entry point |
| `.claude-plugin/plugin.json` | Version 0.3.1 |
| `HANDOFF.md` | Full release history |
