# v2-capabilities.md — Expansion research for hubspot-demo-prep

Investigation of HubSpot API + CLI surface for adding more pre-built demo assets to `builder.py`. Verified against HubSpot Developer Docs as of 2026-04-26.

Auth pattern (matches existing builder): `Authorization: Bearer ${HUBSPOT_DEMOPREP_SANDBOX_TOKEN}`, JSON body, `self.client.request(method, path, body)` shape from `HubSpotClient`. Object base path `/crm/v3/objects/{type}` with `properties` and `associations` arrays in the body — same structure as the contact/deal/ticket recipes already in builder.

Demo-value rating key: H = "lived-in" feel a buyer would notice on the call. M = nice extra. L = niche.

---

## 1. Sales sequences

| Capability | Feasibility | Endpoint / `hs` | Sample body / invocation | Scopes | Gotchas | Demo |
|---|---|---|---|---|---|---|
| Create sequence | NO | (no API) | — | — | Sequences must be authored in UI. No POST endpoint exists. | — |
| List sequences | YES | `GET /automation/sequences/2026-03` | — | `automation.sequences.read` | Returns sequences already authored. | M |
| Enroll contact | YES | `POST /automation/sequences/2026-03/enrollments` | `{"contactId":"123","sequenceId":"44","senderEmail":"rep@portal.com"}` | `automation.sequences.enrollments.write` | Sender email must be a connected inbox owned by a paid Sales/Service Hub seat. 1,000 enrollments / portal / day cap. | H |

Recipe: hand-author a "{CustomerName} Q2 outbound prospecting" sequence in UI once, then have the skill enroll the demo contacts. See https://developers.hubspot.com/docs/api-reference/automation-sequences-v4/guide

---

## 2. Meeting scheduling pages

| Capability | Feasibility | Endpoint | Body | Scopes | Gotchas | Demo |
|---|---|---|---|---|---|---|
| Create meeting link | NO | (no API) | — | — | Library Meetings v3 is read-only + book-only. No POST to create meeting-links. | — |
| List meeting links | YES | `GET /scheduler/v3/meetings/meeting-links` | — | `scheduler.meetings.meeting-link.read` | Pulls existing user scheduling pages. | M |
| Get availability | YES | `GET /scheduler/v3/meetings/meeting-links/book/availability-page/{slug}` | — | same | Useful only if a link exists. | L |
| Book a meeting | YES | `POST /scheduler/v3/meetings/meeting-links/book` | standard book payload | same | No CAPTCHA support, no payment, no UTM tracking. | M |

Recipe: skill cannot programmatically scaffold a booking page. **Workaround**: pre-create one round-robin scheduling page in the sandbox UI per rep, store its slug in env (`HUBSPOT_DEMOPREP_MEETING_SLUG`), surface that link in the Google Doc as "Book with sales." See https://developers.hubspot.com/docs/api-reference/library-meetings-v3/guide

---

## 3. Quotes

| Capability | Feasibility | Endpoint | Body shape | Scopes | Gotchas | Demo |
|---|---|---|---|---|---|---|
| Create quote (DRAFT) | YES | `POST /crm/v3/objects/quotes` | see below | `crm.objects.quotes.write` + line_items + deals + contacts | Must associate a quote-template (assoc 286), a deal (64), at least one line item (67), and a contact for signature. Template must already exist in the portal. | H |
| Add line item | YES | `POST /crm/v3/objects/line_items` then assoc to quote | `{"properties":{"name":"...","price":"500","quantity":"1","hs_product_id":"<optional>"}}` | `crm.objects.line_items.write` | Line items are first-class CRM objects. | H |
| Publish quote | YES | `PATCH /crm/v3/objects/quotes/{id}` | `{"properties":{"hs_status":"APPROVAL_NOT_NEEDED"}}` | quotes.write | States: DRAFT -> APPROVAL_NOT_NEEDED -> PENDING_APPROVAL -> APPROVED -> REJECTED. | H |

Sample create body (matches builder's existing pattern):
```json
{
  "properties": {
    "hs_title": "{CustomerName} - Q2 Pricing",
    "hs_expiration_date": "2026-06-30",
    "hs_currency": "USD",
    "demo_customer": "{slug}"
  },
  "associations": [
    {"to":{"id":"<dealId>"},"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":64}]},
    {"to":{"id":"<contactId>"},"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":71}]},
    {"to":{"id":"<lineItemId>"},"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":67}]},
    {"to":{"id":"<templateId>"},"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":286}]}
  ]
}
```

Gotcha: getting a quote-template ID without UI — `GET /crm/v3/objects/quote_templates` (object type `0-64`). If sandbox has no template, hand-create one once and pin its ID. Source: https://developers.hubspot.com/docs/api-reference/crm-quotes-v3/guide

---

## 4. Invoices

| Capability | Feasibility | Endpoint | Body | Scopes | Gotchas | Demo |
|---|---|---|---|---|---|---|
| Create invoice (DRAFT) | YES | `POST /crm/v3/objects/invoices` | see below | `crm.objects.invoices.write` | Invoices follow same CRM object pattern as quotes. | H |
| Batch w/ line items | YES | `POST /crm/v3/objects/invoices/batch/create` | uses `inputs[]` array | same | Line item assoc type 181, contact assoc 177. | H |
| Move to `open` | YES | `PATCH /crm/v3/objects/invoices/{id}` | `{"properties":{"hs_invoice_status":"open"}}` | invoices.write | Requires >=1 contact + >=1 line item before transition. | M |

Sample body:
```json
{
  "properties": {
    "hs_currency": "USD",
    "hs_invoice_date": "2026-03-15T00:00:00Z",
    "hs_due_date": "2026-04-15T00:00:00Z",
    "demo_customer": "{slug}"
  },
  "associations": [
    {"to":{"id":"<contactId>"},"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":177}]},
    {"to":{"id":"<lineItemId>"},"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":181}]}
  ]
}
```

Statuses: `draft`, `open`, `paid`, `voided`. Commerce Hub tier requirement is not stated in docs — invoices appear in Sales Hub starter+. Source: https://developers.hubspot.com/docs/api-reference/crm-invoices-v3/guide

---

## 5. Playbooks

| Capability | Feasibility | Endpoint | Demo |
|---|---|---|---|
| Create / update / delete | NO | (no public API) | — |
| Read / search | NO | (no public API) | — |

Marked NOT_SUPPORTED by HubSpot on the Ideas board. Must be authored in UI. Skip from builder.py. Source: https://community.hubspot.com/t5/HubSpot-Ideas/Playbook-API-Endpoint/idi-p/405136

---

## 6. Snippets

| Capability | Feasibility | Endpoint | Demo |
|---|---|---|---|
| Create snippet | unknown | (no documented endpoint found) | — |

No public Snippets API surfaced in HubSpot docs as of 2026-04-26. Conversations API has thread/message endpoints but no snippet CRUD. Skip. https://developers.hubspot.com/docs/api-reference/conversations-conversations-v3/guide

---

## 7. Email templates (sales/service)

| Capability | Feasibility | Endpoint | Body | Scopes | Gotchas | Demo |
|---|---|---|---|---|---|---|
| Create marketing email | YES (already in builder) | `POST /marketing/v3/emails` | full JSON content (no templateId param) | `content` + `marketing-email` | Cannot reference a template by ID — must POST full module/content JSON. Pattern: GET an existing email, copy structure, POST modifications. | already H |
| Sales-rep email template | unknown | (no documented public POST endpoint for `/email/templates`) | — | — | The "Templates" inside Sales Hub (used in 1-to-1 emails) appear UI-only. CMS-side `cms/v3/source-code/...` lets you upload `.html`/`.hubl` template files via Files/Design Manager but those are CMS templates, not Sales templates. | — |

Skip Sales templates from builder. Marketing email is already covered. Source: https://developers.hubspot.com/docs/api-reference/marketing-emails-v3

---

## 8. Dashboards + reports

| Capability | Feasibility | Endpoint | Demo |
|---|---|---|---|
| Create dashboard | NO | (no public API) | — |
| Create report | NO | (no public API) | — |
| Pull report data | YES (read-only) | `GET /analytics/v2/reports/{breakdown}/{period}` | M |

HubSpot has explicitly stated no plans to ship a write-side reports/dashboards API. **Workaround for "morning coffee" reports**: build them once in the demo sandbox UI and pin their dashboard ID in env (`HUBSPOT_DEMOPREP_DASHBOARD_ID`), then surface the deep-link URL in the Google Doc. Source: https://community.hubspot.com/t5/APIs-Integrations/Is-It-Possible-To-Dynamically-Create-HubSpot-Reports-with-the/m-p/1092148

---

## 9. Custom reports

Same answer as #8 — not creatable via API. Use the dashboard-template pinning workaround.

---

## 10. Account branding (logo + colors)

| Capability | Feasibility | Endpoint | Demo |
|---|---|---|---|
| Set brand logo | partial | `POST /files/v3/files` (multipart) — uploads file only; brand-kit assignment is UI-only | M |
| Set brand colors | NO | (no public endpoint for brand_settings) | — |
| Sync brand kit to sandbox | NO | HubSpot confirmed no API + no copy-tool | — |

Brand colors/logo on portal-defaults are **not exposed via public API** — `{{brand_settings.*}}` HubL tokens are read-side only. Files API uploads images to Files tool but cannot wire them into Brand Kit programmatically.

**Workaround**: skill uploads logo to `/demo-prep/<slug>/logo.png` via Files API (already wired in `upload_hero_image`), surfaces URL in Google Doc with a manual_step instructing demo presenter to drag-drop it into Brand Kit. Sandbox tier has no extra limitation here.

Sources: https://community.hubspot.com/t5/CMS-Development/How-do-I-sync-the-brand-kit-to-my-dev-sandbox-account/td-p/794608, https://developers.hubspot.com/docs/cms/start-building/building-blocks/fields/brand-and-settings-inheritance

---

## 11. Sales Workspace leads (object 0-136)

| Capability | Feasibility | Endpoint | Body | Scopes | Gotchas | Demo |
|---|---|---|---|---|---|---|
| Create lead | YES | `POST /crm/v3/objects/leads` | see below | `crm.objects.leads.read` + `crm.objects.leads.write` | Lead **must** be associated with an existing contact at create time. Sales Hub Pro+ required. Object type id = `0-136`. | H |

Sample body:
```json
{
  "properties": {
    "hs_lead_name": "Jane Doe - {primary_inquiry_topic}",
    "hs_lead_type": "NEW_BUSINESS",
    "hs_lead_label": "WARM",
    "demo_customer": "{slug}"
  },
  "associations": [
    {"to":{"id":"<contactId>"},"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":578}]}
  ]
}
```

`hs_lead_label` enum: COLD/WARM/HOT. `hs_lead_type` enum: NEW_BUSINESS/EXISTING_BUSINESS/etc. Source: https://developers.hubspot.com/docs/reference/api/crm/objects/leads

This is **the highest-leverage addition** — prospects opening Sales Workspace and seeing a populated leads queue creates a "lived-in" effect.

---

## 12. CRM card UI extensions (`hs project`)

| Capability | Feasibility | Command / config | Gotchas | Demo |
|---|---|---|---|---|
| Scaffold project | YES | `hs project create --templateSource="HubSpot/ui-extensions-examples"` | Requires Sales/Service Hub Enterprise + CRM dev tools beta opt-in. | H if it works |
| Define card | YES | extension JSON: `type:"crm-card"`, `location:"crm.record.tab"`, `objectTypes:["contacts"]` | Card is React + GraphQL. | H |
| Upload | YES | `hs project upload` | Project files in `<project>/src/app/extensions/`. Example folder `deals-summary` is closest to a "latest shipment" card. | H |

Recipe for a "Latest custom-object record card on contact" (e.g., "Latest shipment" for logistics, "Latest installation" for service businesses, "Latest project" for agencies — name it after whatever object the prospect's domain actually uses):
1. `hs project create` (template `crm-card`)
2. Extension reads from the custom object created by the `create_custom_object` phase (named per the prospect's domain), associated to contact
3. `hs project upload --account=demoprep` -> card appears on contact records

Gotcha: this is a multi-file scaffold (`.json` + `.tsx` + `package.json`) — heavy to embed in Python. **Recommendation**: ship a static template under `~/.claude/skills/hubspot-demo-prep/templates/crm-card-shipment/` and have builder.py shell out to `hs project upload --account ${portal}` after token-substituting the slug. Sources: https://developers.hubspot.com/docs/platform/create-custom-crm-cards-with-projects, https://github.com/HubSpot/ui-extensions-examples

---

## 13. Conversations inbox (shared, sample threads)

| Capability | Feasibility | Endpoint | Body | Scopes | Gotchas | Demo |
|---|---|---|---|---|---|---|
| List inboxes | YES | `GET /conversations/v3/inboxes` | — | `conversations.read` | Returns existing inboxes. | — |
| Create inbox | unknown | (no documented POST) | — | — | Inbox creation appears UI-only. | — |
| Register custom channel | YES | `POST /conversations/v3/custom-channels` | uses dev API key + app id | `conversations.custom_channels.write` | Requires public app, not just private app token. | M |
| Post message to existing thread | YES | `POST /conversations/v3/conversations/threads/{threadId}/messages` | `{"type":"MESSAGE","text":"...","senderActorId":"..."}` | conversations.write | Need an existing thread first. | M |

**Practical demo recipe**: skill cannot create an inbox, but can post sample messages into an existing thread if one is pre-seeded. Cleaner alternative: pre-create one shared inbox (UI, once) named "{CustomerName} support", store its `inboxId`, then have builder push 3-5 sample threads using a custom-channel app. **Heavy lift** — better to defer until after #11. Source: https://developers.hubspot.com/docs/api-reference/conversations-custom-channels-v3/guide

---

## 14. Custom views (saved list filters)

| Capability | Feasibility | Endpoint | Demo |
|---|---|---|---|
| Create saved view | NO | (no public API) | — |
| Lists API (alternative) | YES | `POST /crm/v3/lists` | M |

"Saved Views" on object index pages have no public CRUD API. Closest equivalent is **dynamic Lists** (which builder already touches via the lists endpoint).

Recipe to fake a saved view with a list:
```json
{
  "name": "Demo: Hot Leads - {CustomerName}",
  "objectTypeId": "0-1",
  "processingType": "DYNAMIC",
  "filterBranch": {
    "filterBranchType":"AND",
    "filterBranches":[],
    "filters":[{
      "filterType":"PROPERTY",
      "property":"lifecyclestage",
      "operation":{"operator":"IS_ANY_OF","values":["lead","marketingqualifiedlead"]}
    }]
  }
}
```

Scopes: `crm.lists.write`. Source: https://developers.hubspot.com/docs/api-reference/crm-lists-v3/list-filters

Demo value: M — lists != saved views in the UI, but they show "we segment your audience."

---

## 15. Forms with conditional logic

| Capability | Feasibility | Endpoint | Demo |
|---|---|---|---|
| Create form | YES (already in builder) | `POST /marketing/v3/forms` | — |
| Conditional logic / dependent fields | partial | same endpoint, `dependentFieldFilters` in field config | M |

Dependent fields are part of the form field schema (`dependentFieldFilters[]`). The current builder forms phase creates basic forms — adding conditional logic is a same-endpoint config change, not a new endpoint. Limited to dropdown/radio/checkbox/single-line-text triggers per docs. Source: https://developers.hubspot.com/docs/api-reference/marketing-forms-v3/guide

---

## 16. Knowledge base articles

| Capability | Feasibility | Endpoint | Demo |
|---|---|---|---|
| Create / update KB article | NO | HubSpot confirmed "Not currently planned" | — |
| Search KB | YES | `GET /cms/v3/site-search/search` | L |

Skip from builder. Source: https://community.hubspot.com/t5/APIs-Integrations/Create-and-Modify-Knowledge-Base-KB-Articles-via-API/td-p/286882

---

## 17. Properties — calculation, score, groups

| Capability | Feasibility | Endpoint | Body | Scopes | Gotchas | Demo |
|---|---|---|---|---|---|---|
| Calculation property | YES | `POST /crm/v3/properties/{objectType}` | see below | `crm.schemas.{obj}.write` | Use `fieldType:"calculation_equation"`. | M |
| Score property | NO | (UI only) | — | — | Score-property creation has never been API-exposed. Builder's existing `demo_lead_score` is a plain number — fine. | — |
| Property group | YES | `POST /crm/v3/properties/{objectType}/groups` | `{"name":"{slug}_demo","label":"Demo ({CustomerName})","displayOrder":-1}` | schemas.write | Useful for keeping demo properties grouped together in UI. | M |

Calculation property body:
```json
{
  "name": "deal_age_days",
  "label": "Deal Age (days)",
  "type": "number",
  "fieldType": "calculation_equation",
  "groupName": "dealinformation",
  "calculationFormula": "DAYS_BETWEEN(createdate, NOW())"
}
```

Sources: https://developers.hubspot.com/docs/api-reference/crm-properties-v3/guide, https://community.hubspot.com/t5/APIs-Integrations/Possible-to-create-a-Score-or-Calculation-custom-property-via/m-p/546605

---

## CLI investigation (`hs`)

Verified commands (https://developers.hubspot.com/docs/developer-tooling/local-development/hubspot-cli/reference):

| Command | Purpose | Demo-relevant? |
|---|---|---|
| `hs init` / `hs auth personalaccesskey` | Auth a portal | yes (one-time setup) |
| `hs account list/use/remove` | Switch portals | yes |
| `hs project create` | Scaffold UI extensions / private apps | **HIGH** — only path to crm-card |
| `hs project upload` | Push project | yes |
| `hs project dev` | Local dev server | no (interactive only) |
| `hs cms upload` / `hs upload` | Push themes/modules to Design Manager | M (theme work) |
| `hs cms theme create` | Scaffold theme | M |
| `hs cms module create` | Scaffold module | M |
| `hs filemanager upload` | Push files | yes (logo) |
| `hs secrets {add,update,list}` | Serverless function secrets | no |
| `hs sequence` | **does not exist** | — |
| `hs snippet` | **does not exist** | — |
| `hs playbook` | **does not exist** | — |

Verdict: CLI is **only useful for crm-card extensions and theme uploads**. None of the high-priority gaps (sequences, snippets, playbooks, dashboards, brand-kit) have a CLI escape hatch. Source: https://developers.hubspot.com/docs/developer-tooling/local-development/hubspot-cli/reference

---

## TOP 5 quick wins to add to builder.py next

Ranked by (demo-value x ease-of-implementation). All five are pure HTTP — no new dependencies, just new phases on the `Builder` class matching the existing `create_*` pattern.

### 1. Leads object (`0-136`) phase — highest leverage
**Demo value: H. Effort: ~1 hour.** Adds 8-12 leads pre-staged in Sales Workspace. Buyer opens prospecting workspace -> sees populated queue -> instantly visualizes their reps using HubSpot.
- Endpoint: `POST /crm/v3/objects/leads`
- Pattern: identical to `create_tickets()` — loop, build properties, attach contact assoc 578, call `client.request`
- Gate: requires Sales Hub Pro/Ent (sandbox 51393541 already meets this; verify via leads schema GET in `ensure_properties` if defensive)
- Add 2 dynamic lists with lead-stage filters as bonus

### 2. Quotes phase (with line items + template)
**Demo value: H. Effort: ~2 hours.** A quote with the prospect's name + branded line items is the "wow this is real" moment.
- Steps: GET existing quote-template ID once -> POST line_items (3-5) -> POST quote with all 4 association types -> PATCH to `APPROVAL_NOT_NEEDED`
- One gotcha: builder needs to pin a quote-template ID per portal in env (`HUBSPOT_DEMOPREP_QUOTE_TEMPLATE_ID`)
- Worth tagging line_items with `demo_customer` for cleanup parity

### 3. Invoices phase
**Demo value: H. Effort: ~1.5 hours.** Reuses line_items from Quotes phase. Demonstrates Sales->Commerce flow.
- Use batch endpoint `POST /crm/v3/objects/invoices/batch/create`
- Generate 2 invoices: one `paid` (backdated 30d), one `open` (current). Use existing `ms_ago` helper for `hs_invoice_date`
- Status transitions are property PATCHes — no special endpoint

### 4. Calculation property + property group
**Demo value: M. Effort: ~30 min.** Fast, low-risk, makes properties phase feel polished. Adds `deal_age_days` (DAYS_BETWEEN formula) and groups all demo properties under a per-customer property group (e.g., `Demo ({CustomerName})`) instead of `contactinformation`.
- Same `POST /crm/v3/properties/{obj}` already used; new fieldType + new sibling endpoint for groups
- Cleanup phase needs `DELETE /crm/v3/properties/{obj}/groups/{name}`

### 5. Sequence enrollments (assuming a hand-built sequence exists)
**Demo value: M-H. Effort: ~30 min** once a base sequence is hand-authored once in the sandbox.
- Add `HUBSPOT_DEMOPREP_SEQUENCE_ID` + `HUBSPOT_DEMOPREP_SENDER_EMAIL` to env
- Loop through `manifest["contacts"]`, POST `/automation/sequences/2026-03/enrollments` for 3-4 of them
- Watch the 1k/portal/day cap — fine for demos
- If env var missing, skip phase silently with a `manual_step` pointing to the Sequences UI

### Deferred / not worth pursuing for v2
- **Brand-kit colors**: no API. Pre-configure sandbox once with neutral branding, surface logo upload as `manual_step`.
- **Playbooks, snippets, KB articles, dashboards, saved views, score properties, scheduling pages**: confirmed no public API.
- **Conversations sample threads**: requires custom-channel app registration — high friction for low marginal demo value vs. tickets the builder already creates.
- **CRM card UI extension**: high demo value but requires a templates dir + `hs` shell-out — defer to v3 once shipments object is more mature.
