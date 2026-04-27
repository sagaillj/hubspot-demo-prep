# Plan: Build hubspot-demo-prep Skill

**Tier:** Critical (writes to live Enterprise portal, multiple external APIs)
**Reviews required:** codex:rescue at end of build. autoresearch:security skipped — no auth/PII/payments scope. ui-ux-pro-max for the Google Doc output template.

## Don't-break list (global)
- Existing `hs` CLI auth to `300sync` (51125186) — add new account, do not replace
- `~/.claude/api-keys.env` — read-only, never modified
- Existing MCP server registrations
- 300 Tech Solutions portal (20708362) — primary path is to spin a **standard sandbox** off this portal and seed everything there (clean isolation, zero pollution risk to real reporting). If sandbox not used, every asset must carry `demo_customer=<slug>` tag + `@demo-<slug>.test` email domain.
- Existing skills in `~/.claude/skills/` — do not modify their behavior

## Resolved decisions (from Phase 2)
- **Q1 Workflows:** Build everything programmatically that the API supports. For unsupported actions (Send Marketing Email, Send SMS, AI Step, complex branching) — workflow is built up to that point, and the Google Doc output explicitly flags "manual UI step required: add X to workflow Y before demo."
- **Q2 Activity scope:** FULL — notes, calls, tasks, meetings, emails, form submissions, page views. Backdated 3-6 months on each contact for a scrollable, lived-in timeline.
- **Q3 Custom events:** Define schemas AND fire 5-10 events per contact. Default behavior, not opt-in.
- **Q4 Wizard:** Hybrid — first run is detailed and persists to `state/config.json`. Subsequent runs do a fast smoke test of connections (~5s) then proceed.
- **Q5 Pollution:** Default = spin a sandbox. Skill offers user a choice in wizard: sandbox / production-with-tags / point at separate portal.

## New requirements added in Phase 2 round 5
- **Hub ID is the first interactive prompt.** Wizard asks for parent Hub ID before anything else. All subsequent setup links are deep-linked using that ID (`https://app.hubspot.com/private-apps/{ID}`, `/personal-access-key/{ID}`, `/contacts/{ID}`, `/private-apps/{ID}/create`, etc.). Saves the user from hunting through menus.
- **Playwright vs manual choice surfaced at wizard start.** Single question after Hub ID: "Want me to drive Chrome and click through HubSpot for you (Playwright), or prefer to follow links yourself (faster if you have access already)?" User picks once, applies to all subsequent setup steps.
- **Every setup step uses a clickable deep link.** No "go to Settings → Integrations → ..." paths when a direct URL exists. Doubles as a future-proofing pattern: if HubSpot moves a menu, the URL still works.
- **Encode all gotchas from the verified-working setup procedure.** Specifically: chicken-and-egg in `hs account auth` (the `--account` flag fails until the account exists in config; omitting it triggers the interactive prompt that we then need to skip past), the name-field-blank issue (CLI leaves `name:` empty when interactive prompt is dismissed; wizard fixes config.yml post-auth), the auto-population of sandbox into hs config (no second auth needed after `hs sandbox create`). All documented in `references/setup-procedure.md` so the wizard handles them seamlessly.

## New requirements added in Phase 2 round 4
- **Full-service wizard.** The wizard is the user's white-glove onboarding, not a gatekeeper. For every dependency that's missing (HubSpot Private App token, `hs` CLI auth, Firecrawl key, Perplexity key, Recraft, Drive MCP), the wizard:
  1. Detects what's missing via programmatic checks (never "do you have X?" — actually probes for the credential or capability).
  2. Walks the user through exact manual steps with copy-pasteable commands and direct deep links to the right HubSpot/service settings page.
  3. Offers a Playwright-driven "I'll do it for you" alternative where feasible (e.g., navigate to HubSpot Private App creation page, scroll to scopes, check the right boxes, click create, capture the token, save it). User can decline and do it themselves.
  4. After completion, re-runs the programmatic check to confirm setup actually worked. Never trusts the user's word.

## New requirements added in Phase 2 round 3
- **Lead scoring (conditional, sales-relevant)** — When agenda touches sales / lead gen / sales pipeline efficiency, skill creates a custom number property (`demo_lead_score`), a scoring workflow (+points for form submission, page view, email open, meeting booked, etc.), and backfills scores on existing demo contacts so the score column is populated and the contact record's score field is non-zero on demo day. Adds a custom contact list view sorted by score for a satisfying "here are our hottest leads" demo moment. Goes in the Easter egg catalog as a top-3 option for sales-focused ICPs.
- **Cleanup prompt at start of every skill run** — Before generating new demo data, skill scans the sandbox for prior `demo_customer` tagged data and surfaces a one-line summary: "Found 47 records from prior runs (acme-robotics, sunnyside-landscaping). Wipe before proceeding? (y/N — default N since new data is tagged separately and won't conflict)." Does not run cleanup automatically.

## New requirements added in Phase 2 round 2
- **Logo + color visual reference in output Doc:** Embed logo screenshot (Playwright capture) + color swatches (extracted hex with rendered color blocks) so the demo presenter can eyeball that branding pulled correctly before showing it.
- **Optional research stack in wizard:** Playwright (primary), Firecrawl (backup for pages Playwright can't render), Perplexity (industry research). Wizard marks each optional but recommends all three.
- **Context folder ingestion (v1 scope):** Wizard accepts a path to a local folder OR Google Drive folder. Skill ingests text, markdown, PDFs, and screenshots (Claude reads images for context). v1 = use as research input. v2 future = parse Go High Level / competitor screenshots into HubSpot replication attempts (deferred, not in this build).
- **Wizard settings recap:** After first-run setup, wizard prints a single concise paragraph summarizing chosen defaults (activity level, custom event firing, sandbox vs production, etc.) plus a one-line "edit `state/config.json` to change these."
- **Gap callouts in Google Doc:** A dedicated "Manual steps before demo" section listing anything the skill couldn't build programmatically, with the exact UI clicks to finish it.

## Skill structure (multi-file)
```
~/.claude/skills/hubspot-demo-prep/
├── SKILL.md                          # entry point, frontmatter, when-to-use, phases
├── references/
│   ├── hubspot-api-reference.md      # endpoint cheat sheet (from audit)
│   ├── build-order.md                # dependency graph (pipelines before deals, etc.)
│   ├── easter-egg-catalog.md         # ICP-keyed list of high-value HubSpot capabilities
│   └── google-doc-template.md        # output doc structure
├── helpers/
│   ├── seed-crm.sh                   # batch CRM seeding via curl
│   ├── upload-templates.sh           # `hs upload` wrapper for email + LP templates
│   ├── fire-engagements.sh           # contact timeline activity
│   └── cleanup.sh                    # deletes everything tagged demo_customer=<slug>
├── templates/
│   ├── email-template/               # branded HubSpot email template (color tokens)
│   └── landing-page-template/        # branded landing page template (color tokens)
└── state/
    └── config.json                   # persisted setup (portal ID, Drive folder ID, etc.)
```

## Build batches

### Batch 0 — Setup smoke tests (sequential, fast)
| Item | DOD | Verification |
|------|-----|--------------|
| 0.0 **HARD GATE: Programmatically verify Enterprise tier** on portal 20708362. Never ask the user "are you on Enterprise?" — collect the portal ID + auth token, then hit `GET /account-info/v3/details` and parse `subscription` / hub-tier fields directly. If not Enterprise, halt the skill with a clear message listing what won't work (custom objects, custom events, sandboxes, advanced workflows, lead scoring rules). Same principle applies to all capability checks throughout the skill — verify by API, never by asking. | Skill refuses to proceed on non-Enterprise portal | API response parsed; tier asserted in code, not in conversation |
| 0.1 HubSpot API access (Private App token) for portal 20708362 stored in `~/.claude/api-keys.env` | Token exists, test call to `/crm/v3/objects/contacts?limit=1` returns 200 | curl test returns contacts |
| 0.1b Optional: `hs` CLI auth for portal 20708362 (only needed for `hs upload` of templates) | Deferred until Batch 4.2 — non-blocking for early batches | `hs accounts list` shows portal |
| 0.2 Sandbox creation via `hs` CLI (REST API doesn't support it; verified 2026-04-25). Path: `hs sandbox create --name=DemoPrep --type=standard --account=20708362`. Wizard requires `hs` CLI authed to parent portal first. | Sandbox Hub ID captured; switched as active account | `hs accounts list` shows new sandbox; sandbox CRM read returns empty |
| 0.3 Drive MCP creates native Google Doc with link styling | Test Doc named `hubspot-demo-prep smoke test` exists with a clickable link | Doc URL opens; embedded link works |
| 0.4 Playwright scrapes target site (logo + colors via DOM) | Returns logo URL/screenshot + computed CSS colors | Test on `mikilitus.com` returns logo file + ≥3 colors |
| 0.5 Firecrawl backup path | Returns markdown + branding when Playwright is unavailable | Falls through cleanly when Playwright disabled |
| 0.6 Perplexity wrapper returns structured stats | One query returns industry stats with citations | Response includes URLs |

### Batch 1 — Skill scaffolding (sequential)
| Item | DOD | Verification |
|------|-----|--------------|
| 1.1 SKILL.md frontmatter + when-to-use | Frontmatter has `name`, `description`, `user-invokable: true`, `argument-hint`. Triggers documented. | Skill appears in `Skill` tool list after reload |
| 1.2 Wizard section in SKILL.md | Wizard handles new-portal auth, Drive folder selection, dependency check. State persists to `state/config.json`. Re-runs only if missing/changed. | Cold run prompts; warm run skips |
| 1.3 Inputs section | Three inputs: company identifier, stated needs/context, optional agenda. All free-text. | SKILL.md documents the contract |

### Batch 2 — Research helpers (parallel)
| Item | DOD | Verification |
|------|-----|--------------|
| 2.1 Firecrawl company research | Returns brand colors (hex), logo URL, industry signals, ICP signals, services, headline copy | Test on `mikilitus.com` (Jordan's company) returns ≥3 colors |
| 2.2 Perplexity ICP research | Returns 5-10 industry data points with citations, filtered to those that *support* a stated agenda item — discards rest | Test on "landscaping + lead nurturing" returns supporting stats only |
| 2.3 Easter egg catalog | Static md file mapping ICP categories → ranked HubSpot value-adds (custom events, custom objects, sequences, attribution reports, etc.) | At least 10 ICPs covered, each with 3 ranked items |

### Batch 3 — Synthesis logic (sequential, depends on Batch 2)
| Item | DOD | Verification |
|------|-----|--------------|
| 3.1 Demo agenda generator | Given research + stated needs (no agenda), outputs 3 demo items aligned to "solve for the customer." Each item has a 1-line rationale. | Test produces non-generic items tied to customer's actual signals |
| 3.2 Easter egg selector | Given agenda + research + ICP, picks the highest customer-value item the rep didn't mention. Falls through #1→#2→#3 if covered. | Test on a covered #1 falls to #2; on uncovered #1, picks #1 |

### Batch 4 — Build helpers (parallel, except where build-order forces sequence)
| Item | DOD | Verification |
|------|-----|--------------|
| 4.1 `seed-crm.sh` | Batch-creates company, contacts (5-10 personas), deal pipeline + stages, deals, tickets. All tagged `demo_customer=<slug>`. Returns object IDs. | Run on test slug; ID list returned; objects visible in portal |
| 4.2 `upload-templates.sh` | Uploads branded email template + landing page template via `hs upload`. Color tokens replaced from extracted hex. | Templates appear in Design Manager |
| 4.3 `fire-engagements.sh` | Creates notes, tasks, calls, meetings, emails on tagged contacts (timeline activity). Quantity governed by `--activity-level` flag (light/medium/full). | Contact timeline shows engagements |
| 4.4 Custom event firing helper | Defines event schema if missing, fires N events per contact | Events appear on contact timeline |
| 4.5 Custom object helper | Creates schema + records when an agenda item requires it (e.g., "service appointments" for landscapers) | Schema visible in portal settings |
| 4.6 Form + form submission helper | Creates a custom form for the customer use case + submits N test fills via integration endpoint | Form GUID returned; submissions trigger workflow enrollment |
| 4.7 Marketing email creator | Creates a branded marketing email tied to uploaded template, populated with customer-relevant copy | Email visible in Marketing Hub, preview renders |
| 4.8 Landing page creator | Creates a branded landing page tied to uploaded template, customer-themed hero | Page visible, preview URL works |
| 4.9 Workflow creator | Creates programmatic workflow (set property, delay, branch, enrollment trigger). Logs unsupported actions (Send Email, Send SMS, AI Step, complex branching) to gap list for Doc output. | Workflow appears in portal, gap list returned |
| 4.10 Lead scoring helper (conditional) | When agenda is sales-relevant: creates `demo_lead_score` number property, scoring workflow, list view sorted by score, backfills scores on existing demo contacts | Score column non-zero on contact list; sort works |

### Batch 5 — Output generation (sequential)
| Item | DOD | Verification |
|------|-----|--------------|
| 5.1 Google Doc generator | Creates a Doc in a "HubSpot Demo Prep" Drive folder with: header (customer name + date), agenda (3 or 4 items), Easter egg, supporting research data points + citations, links to every asset built (with anchor text "open contact A in HubSpot", etc.) | Doc URL returned; opening it shows clickable links to portal |
| 5.2 `cleanup.sh` | One-line bash that deletes every asset tagged with the demo slug | Run on test slug; portal returns to pre-seed state |

### Batch 6 — End-to-end test (sequential)
| Item | DOD | Verification |
|------|-----|--------------|
| 6.1 Dry-run on Acme Robotics (fictional) | Skill invoked with `acme-robotics.com` placeholder + "lead nurturing" need. All assets created, Doc generated, links open. | Manual review of Doc + portal |
| 6.2 Dry-run on Mikilitus (real, Jordan's company) | Skill invoked with `mikilitus.com` + their actual context. Assets ready for the Friday call. | Walkthrough screenshot saved |
| 6.3 Cleanup test | Run cleanup, portal returns to clean state | Search for tag returns zero results |

### Batch 7 — Pre-deploy reviews (parallel)
- `codex:rescue` review of all helper scripts + SKILL.md
- `ui-ux-pro-max` review of Google Doc output formatting
- Apply all critical/high findings; medium/low to `docs/backlog/dod-findings.md`

### Batch 8 — Documentation
| Item | DOD | Verification |
|------|-----|--------------|
| 8.1 README inside skill folder | Setup, invocation, troubleshooting, cleanup, replication-for-others | Read by a fresh agent, can the skill be used? |
| 8.2 Recording prep notes | Talking points for the Friday call: what to show, in what order, common questions | Reviewed against punch-list |

## Pacing toward Friday
- Today (Apr 25): finish Phase 2, get user `go`, start Batch 0 + 1
- Apr 26-28: Batches 2-4 (the meat)
- Apr 29: Batches 5-6 (output + e2e test)
- Apr 30: Batch 7 reviews + cleanup polish
- May 1: live with Jordan
