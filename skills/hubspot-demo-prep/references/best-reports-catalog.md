# Best Reports Catalog

Used by Phase 2 to plan industry-appropriate reports and dashboards. Each entry describes a *bundle* (3-7 reports that hang together as a dashboard the prospect would actually log in to look at), tagged with the ICP signals it serves, the visualizations it uses, the HubSpot tier it requires, and the custom events that need to be firing for the analytical reports to render meaningfully.

The single most important standard: every dashboard the skill builds must look like a designer made it. Top 10% lens. If a Sankey shows 3 contacts in a single straight line because we only fired full-path events, the demo defeats itself.

## Selection algorithm

1. Filter the catalog for bundles whose `applies_to` matches the prospect's ICP signals (industry, GTM model, business size, stated pain).
2. Rank bundles even when `tier_required` exceeds the sandbox tier, then apply the v0.4 schema's degradation rules. Do not drop a high-value customer problem solely because Sankey/journey/attribution is unavailable; substitute the closest semantic report and record the substitution.
3. Within the qualifying set, rank by `customer_value`. Pick **1-3 bundles** for a typical demo (one sales-focused, one marketing-focused, optionally one ops/CS-focused). One mega-dashboard with 30 cards loses; two role-specific dashboards with 8-12 cards each wins. (Source: Vantage Point's 8-12 cap.)
4. For each chosen bundle, the orchestrator emits matching `custom_event_flows` entries so the Sankey/funnel/journey reports actually have data behind them.

## Tier matrix (gating)

| Capability | Tier required | API or UI? |
|---|---|---|
| Single-object + cross-object reports (custom report builder) | Marketing Pro+ | UI only — no public Reports API |
| Funnel reports (vertical/horizontal) | Marketing Pro+ | UI only |
| Custom dashboards (create + add reports) | Marketing Pro+ (Free has 3, Starter 10, Pro+ 350) | UI only |
| Specific user/team dashboard sharing | Marketing Enterprise | UI only |
| Sankey diagrams (Customer Journey Report) | **Marketing Enterprise** | UI only |
| Customer Journey Analytics | **Marketing Enterprise** | UI only |
| Multi-touch deal-create + revenue attribution | **Marketing Enterprise** | UI only — needs interaction-type toggle ≥48h before demo |
| Contact-create attribution | Marketing Pro+ | UI only |
| Custom Events (define + fire + backdate via API) | Marketing Pro+ | API |
| Codeless Event Visualizer | Marketing Enterprise | UI only |

> **Rule of thumb.** All "report and dashboard creation" is Playwright work. The API gives us data (events, deals, engagements) but not layouts. Plan accordingly: API seeds the underlying records, Playwright assembles the chart.

## Visualization-by-use-case (the design tell is the right chart for the right job)

HubSpot's chart-type menu: KPI, gauge, vertical bar, horizontal bar, line, area, donut, pie, summary, table, pivot table, combination, scatter — plus funnel and Sankey inside the journey/funnel builders. **Use all of them across a demo, not just bars.**

| Use case | Recommended viz | Why |
|---|---|---|
| Hero KPI ("ARR this quarter") | KPI tile with period delta | Built-in delta arrow + % change reads in 1 second |
| Goal progress ("vs. quota") | Gauge with Alert palette | Bands give instant green/yellow/red |
| Pipeline by stage | Vertical funnel | Visual width matches conversion math |
| Stage-to-stage flow / journey | **Sankey** (Marketing Enterprise) | Multi-touch movement; the wow chart |
| Lead source attribution | Donut + horizontal bar combo | Donut for share-of-total, bar for ranked list |
| Revenue / MRR trend | Line or area | Area for cumulative build-up; line for clean trend |
| Activities per rep (leaderboard) | Horizontal bar | Names readable, ranking obvious |
| Deal velocity / aging | Pivot table or scatter | Buckets for 0-30/30-60/60+ |
| Forecast vs actual | Combination chart (bar + line, dual y-axis) | Bars = actual, line = forecast |
| Cohort retention | Pivot table heatmap | SaaS retention grid |
| Conversion funnel by step | Vertical funnel | Default; pair with Sankey for entry-mix |
| Customer journey (multi-touch) | Sankey | Best for showing path divergence |
| Top-N (products, sources, reps) | Horizontal bar (cap 8-10) | Names readable |
| Win/loss reasons | Donut + table | Composition + drill-down |
| Goal completion ladder | Summary card + gauge | "12 of 30 calls today" |
| At-risk / overdue lists | Table with conditional cell coloring | Status flags |

Pie >5 slices = donut. Donut >8 slices = horizontal bar. Stage labels >12 chars = vertical funnel, never horizontal.

## Catalog

> **About these signals:** the phrases below ("free trial," "pipeline visibility," etc.) are illustrative. Phase 2 must re-derive the prospect's actual signals — every industry voices the same underlying need differently. A SaaS founder says "low activation"; a law firm says "intake leak"; a manufacturer says "RFQ-to-PO drop-off." Match the underlying business problem, not the literal phrase.

### B2B SaaS / product-led growth signal
Triggers: free trial, demo CTA, signup funnel, in-app product, pricing tiers, "MRR / ARR / churn" language anywhere on the site.

- **B2B SaaS Acquisition Funnel** — `customer_value: 10/10` — `tier_required: Marketing Enterprise` (for Sankey)
  - Reports: (1) **Sankey** of full funnel `landing → signup_started → signup_completed → activated → first_value`; (2) **Vertical funnel** of step-by-step conversion %; (3) **KPI** signups this week + delta; (4) **Line** of weekly signups (12wk); (5) **Donut** of signup source channels; (6) **Combination** of trial-to-paid by cohort week
  - Custom events needed: `landing_viewed`, `signup_started`, `signup_completed`, `activation_completed`, `first_value_action`. Fire ≥30 contacts in funnel order with realistic 100→60→35→20→12% drop-off
  - Best when rep mentions: "low activation," "leaky funnel," "trials we never reach out to," "where do users drop"

- **Subscription Revenue Health** — `customer_value: 9/10` — `tier_required: Marketing Pro+` (Enterprise needed only if revenue attribution is included)
  - Reports: (1) **KPI** ARR + period delta; (2) **Area** MRR build (new + expansion + contraction + churn stacked); (3) **KPI** Net Revenue Retention; (4) **Gauge** Gross Revenue Retention vs goal; (5) **Pivot heatmap** cohort retention; (6) **Horizontal bar** logo churn reasons
  - Custom events needed: minimal — most signal is from deals + companies properties. If product-usage signal needed, fire `feature_engaged` events
  - Best when rep mentions: "MRR," "churn," "retention," "expansion," "land-and-expand," "QBR with the board"

- **Product-Qualified Lead (PQL) Engine** — `customer_value: 9/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** PQLs created this week; (2) **Vertical funnel** PQL → SQL → demo → won; (3) **Horizontal bar** behaviors driving PQL score (top 10); (4) **Table** at-risk PQLs aging in queue with conditional red on >7 days; (5) **Line** PQL → demo conversion trend
  - Custom events needed: `feature_engaged`, `deep_engagement_threshold_reached`, `invite_sent`, `team_size_grew`. Tie to a `pql_score` calculated property
  - Best when rep mentions: "PQL," "product-led sales," "we don't know which trials to call"

### B2B services / agency / professional services signal
Triggers: agency, consulting, "case studies," scoped engagements, retainer language, hourly billing, tiered service packages.

- **Agency Pipeline Health** — `customer_value: 10/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Pipeline value (open deals); (2) **Combination** weighted forecast vs goal (line) overlaid on stage value (bars); (3) **Vertical funnel** Discovery → Scope → Signed → Kickoff with conversion %; (4) **Horizontal bar** sources of new opportunities (top 10); (5) **Table** stale opps (no engagement >14d) with conditional red; (6) **Donut** deal-size mix (small/mid/enterprise)
  - Custom events: optional — `proposal_sent`, `scope_revised`, `contract_signed` if agency wants stage-level granularity beyond deal stages
  - Best when rep mentions: "where's our pipeline," "forecasting," "we lose deals in scope," "stale opps"

- **Client Engagement & Retention** — `customer_value: 9/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Active retainers + delta; (2) **Pivot heatmap** monthly retention by client tier; (3) **Horizontal bar** clients ranked by lifetime value; (4) **Table** clients by last-touch date with conditional red on >30d; (5) **Line** NPS trend by quarter; (6) **Gauge** % of clients within retention SLA
  - Best when rep mentions: "client churn," "I don't know who's about to leave," "we don't track engagement"

- **Service Delivery Velocity** — `customer_value: 8/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Avg time-to-deliver per engagement type; (2) **Horizontal bar** rep utilization (% of capacity); (3) **Pivot table** project-status grid by team; (4) **Combination** burn rate (bars) vs forecast (line); (5) **Scatter** project size vs delivery time outliers
  - Best when rep mentions: "delivery on time," "project velocity," "are we overworked"

### E-commerce / retail / DTC signal
Triggers: shop, cart, checkout, product catalog, AOV, repeat purchase, Shopify integration mentions.

- **E-commerce Revenue Operations** — `customer_value: 10/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Revenue today + 7-day delta; (2) **Line** weekly revenue trend (24 weeks); (3) **Horizontal bar** top-10 SKUs by revenue; (4) **Donut** new vs repeat revenue; (5) **KPI** AOV with period delta; (6) **Pivot heatmap** repeat-purchase rate by acquisition month; (7) **Gauge** revenue vs monthly goal
  - Custom events: `cart_started`, `checkout_initiated`, `purchase_completed`. ≥50 firings to make the funnel meaningful
  - Best when rep mentions: "abandoned cart," "repeat purchase," "AOV," "our reporting is in 4 places"

- **DTC Cart Abandonment Recovery** — `customer_value: 9/10` — `tier_required: Marketing Enterprise` (Sankey for journey)
  - Reports: (1) **Sankey** full path `viewed_product → cart_started → checkout_initiated → purchased` showing every dropout point; (2) **Vertical funnel** cart-recovery email sequence performance; (3) **KPI** recovered revenue from automation last 30d; (4) **Horizontal bar** top abandoned products; (5) **Combination** abandon rate (bars) vs recovery rate (line) by week
  - Custom events: `viewed_product`, `cart_started`, `checkout_initiated`, `purchased`. Fire 50+ contacts with realistic 100→55→30→18% drop-off
  - Best when rep mentions: "cart abandonment," "we leave money on the table," "recovery emails"

- **DTC Customer Lifetime Value** — `customer_value: 8/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Avg CLTV with delta; (2) **Pivot heatmap** retention cohorts (acquisition month × month-since-acquired); (3) **Horizontal bar** top customers by lifetime spend; (4) **Donut** acquisition-channel CLTV breakdown; (5) **Line** CLTV trend by acquisition cohort
  - Best when rep mentions: "loyalty," "we don't know our LTV," "CAC payback"

### Local services / home services / B2C services signal
Triggers: "schedule a quote," service area, technician, install, dispatch, local business indicators.

- **Service Pipeline & Capacity** — `customer_value: 10/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Open jobs + delta; (2) **Vertical funnel** Inquiry → Quoted → Scheduled → Completed with conversion %; (3) **Horizontal bar** jobs by service type; (4) **Pivot table** technician/installer schedule (rows: tech or installer, columns: day, cells: job count) with conditional color when capacity is exceeded; (5) **KPI** Avg quote-to-close time + delta; (6) **Donut** jobs by lead source
  - Customization notes: use the prospect's service nouns. A marine audio installer should show "stereo refit", "speaker upgrade", "chartplotter/audio integration", and "seasonal install capacity"; a home-services contractor should show its trade-specific job types. Do not ship generic "service call" labels when the website provides real offerings.
  - Best when rep mentions: "scheduling," "tech utilization," "quote-to-close time," "we miss callbacks"

- **Local Service Marketing ROI** — `customer_value: 9/10` — `tier_required: Marketing Pro+` (Enterprise needed if revenue-attribution view added)
  - Reports: (1) **Donut** lead sources (Google, paid ads, referral, organic); (2) **Combination** marketing spend (bars) vs revenue closed (line) by source; (3) **KPI** Cost-per-acquired-customer + delta; (4) **Horizontal bar** ROI by channel (top 10); (5) **Pivot table** service-type × source profitability; (6) **Gauge** monthly leads vs goal
  - Best when rep mentions: "I don't know which marketing works," "Google Ads ROI," "where do leads come from"

### Legal / law firm signal
Triggers: practice area, "free consultation," intake, case management, bar admission language.

- **Legal Intake Conversion** — `customer_value: 10/10` — `tier_required: Marketing Pro+` (Enterprise for the journey Sankey)
  - Reports: (1) **Vertical funnel** Inquiry → Intake call → Qualified → Retained; (2) **KPI** New cases this month + delta; (3) **Horizontal bar** case mix by practice area; (4) **Pivot table** intake source × practice area conversion; (5) **Sankey** (Enterprise) journey from inquiry to retainer signed; (6) **Table** stale leads with conditional red on >3d no contact
  - Custom events (if Sankey): `inquiry_received`, `intake_call_completed`, `case_qualified`, `retainer_signed`
  - Best when rep mentions: "intake leak," "we lose leads to follow-up," "speed to lead"

- **Case Velocity & Health** — `customer_value: 9/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Active cases + delta; (2) **Pivot table** case-stage by attorney; (3) **Horizontal bar** avg days-in-stage by phase; (4) **Combination** new cases (bars) vs resolved (line) by month; (5) **Table** cases at risk with conditional color
  - Best when rep mentions: "case management visibility," "attorney workload," "case velocity"

### Manufacturing / B2B industrial signal
Triggers: RFQ, BOM, distributor, dealer, capital equipment, "request a quote," industry verticals (HVAC, automation, parts).

- **Industrial Pipeline + RFQ** — `customer_value: 10/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Open RFQs + delta; (2) **Vertical funnel** RFQ → Quoted → PO → Shipped; (3) **Horizontal bar** RFQ sources (distributor, direct, web); (4) **Pivot table** RFQ status by region; (5) **Combination** weighted forecast (bars) vs goal (line); (6) **Donut** deal-size mix
  - Best when rep mentions: "RFQ-to-PO conversion," "long cycle," "where do RFQs come from"

- **Distributor / Channel Performance** — `customer_value: 9/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **Horizontal bar** top distributors by closed revenue YTD; (2) **Pivot heatmap** distributor × month revenue trend; (3) **KPI** % of revenue through channel; (4) **Combination** channel revenue (bars) vs direct (line); (5) **Table** distributors with conditional cells for at-risk metrics
  - Best when rep mentions: "channel partners," "distributor performance," "indirect sales"

### Reporting / leadership / exec signal (cross-industry)
Triggers: "I need to report to the board," forecasting, "where are we vs goal," exec dashboards.

- **Executive Pipeline Snapshot** — `customer_value: 10/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Pipeline value (3 of them: total, weighted, this-quarter); (2) **Gauge** % of quota; (3) **Combination** forecast (line) vs actual (bars) by month; (4) **Vertical funnel** by deal stage; (5) **Horizontal bar** rep leaderboard; (6) **Donut** segment mix
  - Best when rep mentions: "board meeting," "forecasting," "exec rollup"

- **Marketing Multi-Touch Attribution** — `customer_value: 9/10` — `tier_required: Marketing Enterprise` (deal-create + revenue attribution)
  - Reports: (1) **KPI** Pipeline-attributed revenue last 90d; (2) **Horizontal bar** revenue by source/channel; (3) **Sankey** journey through touchpoints to closed-won; (4) **Donut** first-touch vs last-touch breakdown; (5) **Combination** marketing spend (bars) vs influenced revenue (line); (6) **Table** top 20 won deals with attributed touchpoints
  - Tier reminder: requires the interaction-type toggle flipped ≥48h before demo (per attribution reprocessing window)
  - Best when rep mentions: "marketing ROI," "which channel works," "executive marketing report"
  - Feature-showcase pattern: create at least 3 campaigns with different roles (first touch, last touch, influenced), custom source fields / form submissions / custom events that differ in useful ways, and deals with real amounts tied to those contacts. Do not try to write HubSpot read-only analytics properties directly in `contacts[]`. The story should let the presenter say: "This deal first came from the webinar, converted after retargeting, and now rolls up to campaign revenue." Use a workflow/manual step to propagate campaign influence from contacts to associated deals when HubSpot's public APIs cannot create that association directly.

### Customer Success / Service signal
Triggers: ticketing, NPS, customer health, account management, support team.

- **Customer Success Health** — `customer_value: 9/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Avg health score + delta; (2) **Horizontal bar** at-risk accounts (bottom 10 health); (3) **Pivot heatmap** health-score trend by cohort; (4) **Gauge** % of accounts in healthy band; (5) **Donut** churn reason breakdown; (6) **Table** accounts in red with last-touch date
  - Best when rep mentions: "churn risk," "health score," "renewal forecasting"

- **Support Ticket Operations** — `customer_value: 8/10` — `tier_required: Marketing Pro+`
  - Reports: (1) **KPI** Tickets created today + delta; (2) **Combination** SLA on-time rate (line) vs ticket volume (bars); (3) **Horizontal bar** top issue categories; (4) **Pivot table** tickets by team × priority; (5) **Gauge** % within SLA; (6) **Table** overdue tickets with conditional red
  - Best when rep mentions: "ticket volume," "SLA," "agent capacity"

## Custom event flow patterns (for Sankey + funnel reports)

When a bundle includes a Sankey or vertical funnel based on custom events, Phase 2 must also generate the matching `custom_event_flows` block in the plan. The pattern: define the event sequence with explicit `step` values, then specify a per-contact firing strategy that produces realistic drop-off.

| Vertical | Event sequence | Realistic drop-off (each step's % of prior) |
|---|---|---|
| B2B SaaS PLG | `landing_viewed → signup_started → signup_completed → activation_completed → first_value_action → upgrade_clicked` | 60% → 70% → 65% → 55% → 25% |
| DTC e-commerce | `viewed_product → cart_started → checkout_initiated → purchased` | 55% → 55% → 60% |
| Legal intake | `inquiry_received → intake_call_scheduled → intake_call_completed → case_qualified → retainer_signed` | 80% → 70% → 65% → 50% |
| Local services | `quote_requested → quote_sent → quote_accepted → job_scheduled → job_completed` | 85% → 55% → 90% → 95% |
| Industrial RFQ | `rfq_received → quote_sent → po_received → shipped` | 85% → 35% → 95% |
| Marketing journey | `email_opened → cta_clicked → page_viewed → form_submitted → demo_booked` | 25% → 80% → 30% → 60% |

For Sankey to look meaningful, fire ≥30 contacts through the full funnel with each contact dropping off at varied points, not all at the same place. The orchestrator should distribute drop-off probabilistically — e.g., 10 contacts make it all the way, 8 stop at step 4, 6 at step 3, 4 at step 2, 2 at step 1. **Avoid the failure mode where everyone drops at the same step** — produces a one-line Sankey that looks broken.

Backdate `occurredAt` across the past 30-60 days, with later steps biased to recent dates (so the chart shows momentum). After firing, GET each event definition to confirm schemas are reachable; HubSpot does not expose a readback endpoint for historical event occurrence counts.

## Color palette (carries across every chart on a dashboard)

Mirror the prospect's brand color as the primary fill for non-status data. Use HubSpot orange `#ff4800` only for accents (hero KPI numbers, alerts). Reserve status colors:

- Green `#00BDA5` — healthy, on-track, completed
- Yellow `#F5C26B` — at-risk, approaching threshold
- Red `#FF7A59` — overdue, lost, problem
- Brand color (primary, ~30% of fill) — non-status data, lifecycle stages
- Neutral surface (white or `#F5F8FA`, ~60%) — backgrounds, table cells
- HubSpot orange (~10%) — accents only

Build a **color dictionary** before laying out the dashboard: each lifecycle stage / deal stage / pipeline gets ONE color, used everywhere a chart references that stage. Consistency across cards is what separates designer-quality from AI slop.

For gauges, use HubSpot's built-in "Alert - Green to Red" or "Alert - Red to Green" palettes — never reinvent.

## Anti-patterns (don't do these)

1. **All-orange everything.** Reserve HubSpot orange for accents. AI slop tell.
2. **Pie charts with 8+ slices.** Switch to horizontal bar.
3. **KPI numbers without deltas.** Always pair with period comparison + arrow.
4. **Uniform tile grid.** Mix sizes — small KPI row, medium charts, wide tables.
5. **Generic dashboard names.** "Sales Dashboard" loses; "VP Sales — Quarterly Pipeline Health" wins.
6. **Default chart titles.** "Deals by Stage Closed Date Last 30 Days" → "Deals closed this month".
7. **Funnel with equal-width stages when conversion is dramatic.** Visual width should match the math.
8. **Stale dates in headers.** "Last updated 47 days ago" kills credibility — use dynamic ranges.
9. **Charts without baselines or goals.** Anchor with a target reference line.
10. **One mega-dashboard with 30 cards.** Cap at 8-12 per dashboard. Multiple role-specific dashboards beat one giant one.
11. **Decorative color.** Each color encodes information, not variety.
12. **Sankey with no drop-off variation.** Fire varied paths so the chart looks meaningful, not a single-line trace.

## Customer-value definition

`customer_value` is rated on a per-bundle basis: "if this prospect's exec saw this dashboard at the demo, would it directly move their next purchase decision?"
- 10/10: solves a stated pain immediately, would be the screenshot they share with their team
- 9/10: addresses a major implicit pain that research suggests is present
- 8/10: high-leverage but more discretionary
- 7/10: nice-to-have, polish

Re-rate when the prospect's stated context contradicts catalog defaults.
