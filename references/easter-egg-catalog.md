# Easter Egg Catalog

Used by the Easter egg selector. Each entry: an ICP / pain pattern paired with a HubSpot capability that delivers outsized customer value but is rarely volunteered by reps. Selection rule: if any item is already covered by the rep's stated agenda, fall through to the next.

## Selection algorithm

1. Filter the catalog for items whose `applies_to` matches the customer's ICP signals (industry, business size, GTM model, pain points).
2. Within that filtered set, exclude any item already mentioned in the rep's agenda or the rep's stated needs / context.
3. Rank remaining by `customer_value` (the only ranking criterion — never "uniqueness" or "novelty").
4. Return top item. If filtered set is empty, fall through to "generic_default" entries.

## Catalog

### Sales-heavy / no-marketing-team / lead-flow signal
- **Lead scoring with custom property** — `customer_value: 10/10` — Creates a `demo_lead_score` custom number property + scoring workflow + sorted list view. Reps with no marketing team can't manually triage hundreds of leads; scoring lets them focus on hot ones first. **Highest customer value when the rep mentions: "no marketing team," "too many leads," "we lose track," "where to focus," "lead quality."**
- **Sales pipeline automation** — `customer_value: 9/10` — Auto-create deals from form fills, auto-assign to owners, auto-task creation for follow-up. Eliminates manual data entry. Strong fit when rep mentions "manual," "spreadsheets," "we forget."
- **Email sequences (Sales Hub)** — `customer_value: 8/10` — Personalized 5-7 email outreach cadences, paused on reply. Distinct from marketing nurtures (those go to lists). Sales-rep-driven 1:1 outreach. Fit when rep is doing cold outreach without automation.

### Customer feedback / retention / NPS signal
- **NPS survey + automated follow-up** — `customer_value: 10/10` — Feedback Surveys tool + workflow that routes detractors to support and promoters to a referral / review-request flow. **Highest value when: "no surveys yet," "want feedback," "customer satisfaction," "retention."**
- **Service ticket SLA + escalation workflows** — `customer_value: 8/10` — Auto-escalate stale tickets, auto-route by category. Strong fit when service quality / response time is the pain.
- **Customer Health Score (custom calculation)** — `customer_value: 9/10` — Custom property aggregating engagement, ticket count, NPS, contract value into a single score. Stronger for B2B SaaS / subscription businesses.

### Lead-nurture / inbound-marketing signal
- **Workflow + Smart Content email** — `customer_value: 9/10` — Same email shows different content per persona/property. Without it, every lead gets the same generic message.
- **Behavior-based workflow enrollment (custom events)** — `customer_value: 9/10` — Trigger nurtures based on actual product / page behavior, not just form fills. Way more relevant than "you filled a form 3 days ago, here's an email."
- **Marketing email A/B testing** — `customer_value: 7/10` — Built-in A/B tooling for subject lines and content. Free quality boost for any marketing email program.

### B2B / enterprise / complex-sales signal
- **Custom object for non-standard records** — `customer_value: 9/10` — e.g., for a logistics company: `Shipment` object linked to deals + contacts. Enterprise-only feature, often misunderstood. Concrete demo lands hard.
- **Deal stage probability + forecasting** — `customer_value: 8/10` — Pipeline rollup with weighted probabilities. Sales leadership uses this constantly once installed.
- **Quote-to-cash flow** — `customer_value: 7/10` — Quote → e-sign → payment all in HubSpot. Strong when rep mentions "Stripe" / "DocuSign" pain.

### Reporting / leadership signal
- **Custom dashboards + cross-object reports** — `customer_value: 9/10` — "Show me deals by source by closed-won rate." Report builder is more powerful than reps usually demo.
- **Attribution reporting (multi-touch)** — `customer_value: 9/10` — Connects which marketing actions led to closed-won. Enterprise-tier feature, ROI-justifying.
- **Lifecycle stage automation** — `customer_value: 8/10` — Contacts automatically move from Lead → MQL → SQL → Customer based on rules. Cleans the database.

### Service-business / local-business / home-services signal
- **Online booking via Meetings tool** — `customer_value: 9/10` — Public scheduler with availability + calendar sync. Often replaces Calendly/Acuity entirely.
- **Customer portal** — `customer_value: 8/10` — Lets customers self-serve view tickets, invoices, knowledge base. CMS Hub feature.
- **Two-way SMS via integrations** — `customer_value: 8/10` — Native (US) or via Aircall / Kixie. Critical for service-business confirmation/reminder workflows.

### Generic defaults (when ICP is unclear or stated context is sparse)
- **Lead scoring** — see above. Always near top.
- **Workflow automation (any flavor)** — `customer_value: 8/10` — The "save 10 hours a week" demo lands universally.
- **Built-in AI: Breeze content assistant / data agent** — `customer_value: 8/10` — Modern; resonates with anyone curious about AI.

## Customer-value definition

`customer_value` is rated on a per-item basis as: "if this customer adopted this in the next 30 days, how much would it move their business metric?" Calibration:
- 10/10: solves a stated pain, immediate measurable impact (e.g., NPS for a customer-feedback-blind business)
- 9/10: addresses a major implicit pain that the rep didn't surface but research suggests is present
- 8/10: high-leverage but more discretionary
- 7/10: nice-to-have, polish

Re-rate when business context changes. Don't trust this catalog blindly — it's a starting point.
