# Sweep findings — doc_generator.py + references/

Saved from background Explore agent (2026-04-26 evening).

## doc_generator.py
- **line 36** — `SHIPPERZ_ORANGE = RGBColor(0xFF, 0x6B, 0x35)` (Critical) — rename to `BRAND_ACCENT_ORANGE`, derive from manifest branding
- **line 264** — `_set_run(r, color=SHIPPERZ_DARK, ...)` (Critical) — rename `SHIPPERZ_DARK` → `DARK_TEXT`; derive
- **line 320** — section header still uses `SHIPPERZ_DARK` styling
- **line 376** — generic GRAY OK; line context references Shipperz constants
- **line 674-676** — recommendation narrative hardcoded `"show how easy it is for a no-marketing-team setup."` — Shipperz pain. Move to plan/research
- **line 203-204** — `os.path.join(work_dir, "shipperz-banner.png") if slug == "shipperzinc" else None` — replace with `f"{slug}-banner.png"` pattern (line 201 already has it)

## references/easter-egg-catalog.md
- **line 15** — pain patterns ("no marketing team", "too many leads", etc.) framed as universal but bias toward sales/transport. Reframe as ICP signals
- **line 30** — `"e.g., for a logistics company: 'Shipment' object linked to deals + contacts."` — remove logistics-only example; generalize
- **line 39-42** — service-business signals lean home-services; broaden to also include product-sales, B2B SaaS

## references/v2-capabilities.md
- **line 19** — `"Shipperz Q2 outbound" sequence` example — change to "&lt;CustomerName&gt; Q2 outbound prospecting"
- **line 48** — `"hs_title": "Shipperz - Q2 LTL Pricing"` — placeholder
- **line 183** — references Jeremy's context + Sales Workspace; generalize
- **line 195** — `"Latest shipment" card` recipe — generalize: "custom domain object card, e.g. shipment for logistics, installation for service"

## references/v2-content-campaigns.md (ENTIRE FILE — Critical)
- **lines 50, 54, 110, 201-209** — all Shipperz-named: `"Shipperz: Snowbird Season Q1 2026"`, `"Snowbird Vehicle Transport: 5 Things to Ask Before You Book"` etc.
- **line 51** — Snowbird audience targeting text
- **Action:** rewrite the entire reference as a generic template structure (Campaign &gt; Blog + Email + LP) with `{customer_name}` / `{topic}` / `{seasonal_window}` placeholders, plus 2-3 short EXAMPLES across distinct industries (transport, marine audio, B2B SaaS) so Phase 2 synthesis sees how to translate

## references/google-doc-template.md
- **line 9** — example title `HubSpot Demo Prep — Shipperzinc — 2026-04-26` — change to `HubSpot Demo Prep — &lt;CustomerName&gt; — &lt;Date&gt;`

## references/setup-procedure.md
- **line 175-185** — Shipperz example for `shipmentsobject` custom object — keep as one of multiple examples
- **line 201-209** — Playwright addendum references `shipperz_quote_requested` event — generalize

## references/hubspot-api-reference.md
- Clean. No prospect-content.

---

**Cross-cutting:** doc_generator constants (`SHIPPERZ_*`) leak Shipperz into every prospect's deliverable doc visually. v2-content-campaigns.md is the most-Shipperz-leaking single reference and shapes Phase 2 output the most.
