# Consolidated sweep findings (4 background agents, 2026-04-26 evening)

## A. builder.py (24 surfaces total — 14 already known + 10 new)

### Critical (already in item 9 scope)
- L1316 lead name: `f"{name_prefix} — auto transport inquiry ({src})"`
- L1037-1038 + L1102 marketing email steps: "vehicle and route", "Door-to-door enclosed transport", "Day of pickup"
- L1049 email footer: `"{company_name} — Premium auto transport"`
- L1106 hardcoded `#FF6B35` orange CTA in widget body
- L1391-1397 quote line item catalog (transport services)
- L1639-1647 marketing campaign: "Snowbird Season Q1 2026", FL/AZ/TX snowbird audience
- L1016, L2130 `#FF6B35` color fallbacks

### NEW from agent 1 (add to item 9)
- **L1573-1574 property group**: `group_name = "shipperz_demo_properties"`, `group_label = "Shipperz Demo"` — visible in HubSpot property admin. Fix: `f"{slug}_demo_properties"` / `f"Demo ({slug})"`
- **L1740 Shipperz-specific branching**: `if (self.slug == "shipperzinc" and locked_id)` for Google Doc replacement. Generalize or remove
- **L583-585 notes pool**, **L587-591 tasks/calls/meetings/emails subjects** — move to `plan["activity_content"]["{type}_pool"]`
- **L616, L626, L637 hardcoded engagement bodies** — already item 5 scope
- **L853-854 form-submission contact names** — move to `plan["test_contact_data"]`
- **L1303 lead labels** `["WARM","HOT","COLD"]`, **L1304-1305 lead sources** — move to plan
- **L870 `"pageUri": "https://example.com/demo"`** — keep as is (RFC-reserved)
- **L2121 fallback sender** `demo@example.com` — keep as is

## B. doc_generator.py (6 surfaces)
- **L36 `SHIPPERZ_ORANGE`** → rename `BRAND_ACCENT_ORANGE`, derive from manifest
- **L264, L320 `SHIPPERZ_DARK`** → rename `DARK_TEXT`, derive from manifest
- **L674-676 hardcoded recommendation** `"show how easy it is for a no-marketing-team setup."` → move to plan
- **L203-204 banner slug check** `"shipperz-banner.png" if slug == "shipperzinc"` → use `f"{slug}-banner.png"` pattern (already at L201)

## C. references/ (5 files)
- **easter-egg-catalog.md L15, L30, L39-42** — pain patterns + "logistics company" example + service-business signals lean transport
- **v2-capabilities.md L19, L48, L183, L195** — "Shipperz Q2 outbound", `"Shipperz - Q2 LTL Pricing"`, "Latest shipment" recipe, references Jeremy
- **v2-content-campaigns.md (ENTIRE FILE)** — Shipperz Snowbird Season Q1 2026, blog titles, narratives. Rewrite as generic templates with multi-industry examples
- **google-doc-template.md L9** — "Shipperzinc" example title → placeholder
- **setup-procedure.md L175-185, L201-209** — Shipperz `shipmentsobject` example, `shipperz_quote_requested` event reference

## D. playwright_phases_extras.py (CRITICAL — 8 hardcoded surfaces)
- **L8-9, L52, L305, L375, L379, L383, L412, L521** — entire `create_starter_dashboard()` is "Shipperz Daily Snapshot" with `pipeline = Shipperz` filter and shipping-specific stages (`Quote Requested, Quote Sent, Negotiating`). Read dashboard name + pipeline name + stage names from manifest
- **commands/hotdog.md** — add warning about `--playwright` flag's industry bias

## E. SKILL.md / commands/hotdog.md
- **SKILL.md** lacks an explicit Phase 2 Quality Gate that forces Claude to validate: no terminology reuse from prior runs, industry-specific custom object naming, persona freshness, deal-stage prospect-specificity, email voice-match
- **commands/hotdog.md** — no Playwright bias warning

## F. Prior-run output inspection (Boomer + Shipperz)
- **Boomer manifest tickets**: `"Quote question — Tesla Model Y install"` — Tesla in a marine shop demo (Phase 2 LLM hygiene issue, not code; SKILL.md Quality Gate fixes upstream)
- **Boomer build-plan jobtitle**: `"Tesla Owner"` — same vocabulary bleed
- **Boomer demo-doc**: cites `"$4,200 boat install"` not in deal pipeline — phantom number; recommendation_text generator should only cite numbers present in manifest
- **Shipperz manifest**: 8 manual_steps from Playwright timeouts visible in delivered doc — credibility tax. Manual_steps shouldn't bleed "API returned 500"; sanitize visible reason strings
- **Shipperz form_submissions_count = 0** despite 8 configured — disconnect; verification gap

## Cross-cutting Phase 2 LLM-hygiene patterns (need SKILL.md Quality Gate)
1. Terminology bleed (Tesla in marine shop)
2. Phantom numbers (recommendation cites figures not in manifest)
3. Manual-step error message bleed (raw API errors visible to prospect)
4. Persona inheritance from prior runs (re-infer per industry)
5. Deal-stage template inheritance (re-derive per sales cycle)

---

## Punch-list items added based on this sweep
- **Item 9 (expanded)**: now covers all of A + B + C + D
- **Item 10 (NEW)**: SKILL.md Phase 2 Quality Gate (prevent new bias; covers cross-cutting hygiene patterns)
- **Item 11 (NEW)**: Manual-step error message hygiene (sanitize reason strings shown to prospect)
- **Item 12 (NEW)**: Phantom-number prevention in `_recommendation_text` (only cite numbers present in manifest)
- **Item 13 (NEW)**: Manifest data integrity verifier (catch form_submissions_count vs configured mismatch)
