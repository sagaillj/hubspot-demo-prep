# Punch List: Build HubSpot Demo Prep Skill

**Created:** 2026-04-25
**Deadline:** Friday 2026-05-01 (recording call with Jordan Craig + Mikilitus team)
**Status:** Phase 2 — Plan
**Demo portal:** 300 Tech Solutions, Hub ID `20708362` (full Enterprise — workflows, custom objects, custom events all in scope)
**North Star:** HubSpot motto — "solve for the customer." Skill output should focus on highest-leverage demo items for the target business.

## Skill features

### Inputs
1. **Company identifier** — URL, name, or other identifier (pending)
2. **Stated needs / context** — free text: rep's notes, transcript snippets, called-out pain points (pending)
3. **Optional demo agenda** — skill asks if rep already has one. If yes, use it. If not, skill generates one. (pending)

### Research phase
4. **Firecrawl the company site** — pull industry, ICP signals, products, positioning (pending)
5. **Extract logo + brand colors** — reuse Atlas / tech-stack-detector patterns (pending)
6. **Generate research-backed industry data points** — must directly support the agenda items. If no supporting data exists, return nothing (no padding). (pending)

### Demo agenda generation
7. **If no agenda provided** — skill generates top 3 demo items aligned to "solve for the customer" + business needs (pending)
8. **If agenda provided** — skill uses rep's agenda items verbatim (pending)

### Easter egg
9. **One insight NOT mentioned by the rep** — derived from deep dive on HubSpot product capabilities + ICP/persona research (pending)
10. **Ranked by uniqueness** — fall through #1 → #2 → #3 if higher-ranked is already covered by agenda or rep's stated needs (pending)

### Build phase (in HubSpot demo portal)
11. **Generate tailored CRM data** — contacts, companies, deals, tickets matching ICP personas (pending)
12. **Generate workflow(s)** — addressing the agenda items (e.g. lead nurturing for landscaping example) (pending)
13. **Generate branded marketing assets** — email template + landing page using extracted logo + brand colors (pending)
14. **Drive activity via Forms API** — submissions to make data look "alive" (pending)

### Output
15. **Output document** — agenda + Easter egg + supporting research data points + clickable links to all demo items in HubSpot portal (pending)
16. **Format: Google Doc preferred** (rep clicks links and tabs them out for demo). Word Doc fallback. Markdown third option. (pending — confirm Google Drive MCP can produce a Doc with live links)

### Setup wizard
17. **`hs` CLI auth + correct demo portal selection** (pending)
18. **Sub-tool config: Firecrawl, Recraft** (pending)
19. **Google Docs / Drive MCP** (pending — only if going with Doc output)

## Architecture (settled, not for grilling)
- API + CLI wrapped in skill, no MCP for HubSpot CRM
- Skill code lives at `~/.claude/skills/hubspot-demo-prep/`
- Punch list colocated at `~/.claude/skills/hubspot-demo-prep/docs/punch-lists/`

## Call structure (separate from skill, but related)
- Live invoke skill at start of call with Jordan + team
- Walk through how it was built so they can replicate
- Hand off code / prompt for attendees

## Table-stakes generation (every demo, every time)
Always build:
- Contact(s)
- Company(ies)
- Deal(s)
- Ticket(s)
- Deal pipeline
- Workflow
- Activity data on specific contacts (engagement timeline)

Conditional (only if relevant to agenda / deal notes):
- Quotes / invoices
- Custom objects
- Custom events
- Custom forms
- Marketing email + landing page (always for branded asset, but content depends on agenda)

If an agenda item / Easter egg requires something outside this list and HubSpot Enterprise can build it via API or CLI → build it. Nothing off the table.

## Easter egg logic (resolved)
- **With agenda:** Easter egg is added as a 4th item alongside the rep's 3 agenda items.
- **Without agenda but with context:** skill takes best guess at most-valuable demo items based on deal notes / transcript / stated needs; Easter egg = highest-value item the rep didn't call out.
- **Without context at all:** generic ICP / persona-driven Easter egg.
- **Selection criterion:** value to the customer, not uniqueness. "What helps this customer win" beats "what's rarely demoed." Tie-break to revenue impact if signaled in input.

## Output (resolved)
- **Format:** Google Doc.
- **Setup:** wizard sets up Google Docs / Drive auth if user doesn't already have it. Existing Drive MCP at `mcp__8a98d6d7-*` may be sufficient — verify in Phase 2.
- **Storage:** Google Drive folder gives a clean home for all future demo prep docs.
- **Content:** demo agenda + Easter egg + supporting research data points + clickable links to every demo asset built in HubSpot portal.

## Setup wizard checklist
1. `hs` CLI authed to portal `20708362` (currently authed to `51125186` only — needs new account add)
2. Firecrawl API key (already in `~/.claude/api-keys.env`, verify access)
3. Recraft (MCP already installed and connected)
4. Google Drive / Docs (existing MCP or fresh setup)
5. Optional: Perplexity for research data points (already installed)

## Open ambiguities to resolve in Phase 2 grilling
- Activity data scope: which engagement types (email opens, page views, form fills, meetings, notes, calls)?
- Custom events: just create event definitions, or also fire sample events?
- Industry data point sourcing: Perplexity, Firecrawl secondary, both?
- Skill structure: single SKILL.md or multi-file (helpers, references)?
- Wizard UX: one-shot setup or progressive (only set up what's missing)?
