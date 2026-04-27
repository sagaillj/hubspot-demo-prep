# HubSpot API Reference (skill-internal cheat sheet)

Curated subset of the API surface this skill uses. Every endpoint here is verified-working on Enterprise tier as of 2026-04-25.

Auth header pattern for all calls: `Authorization: Bearer ${HUBSPOT_TOKEN}`

## CRM objects

| Object | Create endpoint | Batch endpoint | Notes |
|--------|----------------|----------------|-------|
| Contact | `POST /crm/v3/objects/contacts` | `/contacts/batch/create` (max 100/req) | Dedupes on email. Use `batch/upsert` to avoid 409s. |
| Company | `POST /crm/v3/objects/companies` | `/companies/batch/create` | Dedupes on `domain`, not `name`. |
| Deal | `POST /crm/v3/objects/deals` | `/deals/batch/create` | Requires `pipeline` and `dealstage` internal IDs. |
| Ticket | `POST /crm/v3/objects/tickets` | `/tickets/batch/create` | Same: `hs_pipeline` + `hs_pipeline_stage` required. |
| Note | `POST /crm/v3/objects/notes` | `/notes/batch/create` | Set `hs_timestamp` for backdating. Always include `associations` to attach to contact/deal. |
| Task | `POST /crm/v3/objects/tasks` | `/tasks/batch/create` | Properties: `hs_task_subject`, `hs_task_body`, `hs_task_status`, `hs_task_priority`, `hs_timestamp`. |
| Call | `POST /crm/v3/objects/calls` | `/calls/batch/create` | Properties: `hs_call_title`, `hs_call_body`, `hs_call_duration` (ms), `hs_call_direction`. |
| Meeting | `POST /crm/v3/objects/meetings` | `/meetings/batch/create` | Properties: `hs_meeting_title`, `hs_meeting_body`, `hs_meeting_start_time`, `hs_meeting_end_time`. |
| Email engagement | `POST /crm/v3/objects/emails` | `/emails/batch/create` | Properties: `hs_email_subject`, `hs_email_text`, `hs_email_direction`, `hs_email_status`. |

### Associations (required for engagements to show on timeline)

In the create body, always include:
```json
"associations": [{"to": {"id": "<contactId>"}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": <typeId>}]}]
```

Common `associationTypeId` values:
- Note → Contact: 202
- Task → Contact: 204
- Call → Contact: 194
- Meeting → Contact: 200
- Email → Contact: 198
- Deal → Contact: 3
- Deal → Company: 5
- Ticket → Contact: 16
- Ticket → Company: 26

## Pipelines

| Operation | Endpoint |
|-----------|----------|
| Create deal pipeline | `POST /crm/v3/pipelines/deals` |
| List deal pipelines | `GET /crm/v3/pipelines/deals` |
| Create stage | `POST /crm/v3/pipelines/deals/{pipelineId}/stages` |
| Same for tickets | swap `deals` → `tickets` |

Deal stage body example:
```json
{"label": "Qualified", "displayOrder": 1, "metadata": {"probability": "0.4"}}
```

## Custom objects (Enterprise gate)

| Operation | Endpoint |
|-----------|----------|
| Create object schema | `POST /crm/v3/schemas` |
| Get all schemas | `GET /crm/v3/schemas` |
| Create record | `POST /crm/v3/objects/{objectTypeId}` |
| Batch records | `POST /crm/v3/objects/{objectTypeId}/batch/create` |

Schema body example (illustrative — pick a domain object name that fits the prospect's industry, e.g. `installation_jobs` for a marine audio installer, `service_visits` for a HVAC contractor, `shipments` for logistics, `engagements` for a B2B SaaS):
```json
{
  "name": "{domain_object_name}",
  "labels": {"singular": "{Singular}", "plural": "{Plural}"},
  "primaryDisplayProperty": "{primary_id_field}",
  "secondaryDisplayProperties": ["status", "{descriptor}"],
  "requiredProperties": ["{primary_id_field}"],
  "searchableProperties": ["{primary_id_field}", "{descriptor}"],
  "properties": [
    {"name": "{primary_id_field}", "label": "{Primary ID Label}", "type": "string", "fieldType": "text"},
    {"name": "status", "label": "Status", "type": "enumeration", "fieldType": "select",
     "options": [{"label": "{Stage 1}", "value": "{stage_1_internal}", "displayOrder": 1},
                 {"label": "{Stage 2}", "value": "{stage_2_internal}", "displayOrder": 2}]},
    {"name": "{descriptor}", "label": "{Descriptor Label}", "type": "string", "fieldType": "text"}
  ],
  "associatedObjects": ["CONTACT", "DEAL"]
}
```

## Custom behavioral events

| Operation | Endpoint |
|-----------|----------|
| Create event definition | `POST /events/v3/event-definitions` |
| Send event | `POST /events/v3/send` |

Send body example (illustrative — pick an event name that matches the prospect's actual user action, e.g. `pe<portalId>_install_booked` for a service business, `pe<portalId>_trial_started` for B2B SaaS, `pe<portalId>_shipping_quote_requested` for logistics):
```json
{
  "eventName": "pe<portalId>_{prospect_action_event}",
  "email": "contact@example.com",
  "properties": {"{relevant_property}": "{value}"},
  "occurredAt": "2026-03-15T10:00:00Z"
}
```

Event names must be prefixed with `pe<portalId>_`. The `eventName` returned at creation time must be used at send time exactly.

## Forms

| Operation | Endpoint |
|-----------|----------|
| Create form | `POST /marketing/v3/forms` |
| List forms | `GET /marketing/v3/forms` |
| Submit form | `POST /submissions/v3/integration/submit/{portalId}/{formGuid}` |

Form submission is **unauthenticated** (no Bearer token) — the body itself acts as auth. Include `context.hutk` to attribute submission to a real session if you have a tracking cookie. Without `hutk`, the contact has no page-view history attribution.

## Workflows v4

| Operation | Endpoint |
|-----------|----------|
| Create workflow | `POST /automation/v4/flows` |
| Enroll contact | `POST /automation/v4/flows/{flowId}/actions/enrollments/contacts` |
| Update workflow | `PATCH /automation/v4/flows/{flowId}` |

**Reliable actions via API:**
- `SET_PROPERTY` — set contact / company / deal property
- `DELAY` — wait N seconds before next action
- `BRANCH` — conditional routing on property value
- `LIST_ENROLLMENT` — add to / remove from a list
- `WEBHOOK` — call external URL

**Brittle / partially supported:**
- `SEND_EMAIL` (marketing email) — works in some configurations, fails in others
- `SEND_TRANSACTIONAL_EMAIL` — works if Marketing Hub Enterprise + transactional add-on
- `CREATE_TASK` — works
- `CREATE_NOTE` — works
- `AI_STEP` (Breeze) — newer, undocumented for API

**Not supported via API (build in UI):**
- Send SMS
- Send via custom integration / connected app
- Complex AI agents

## Marketing emails

| Operation | Endpoint |
|-----------|----------|
| Create email | `POST /marketing/v3/emails` |
| Get email | `GET /marketing/v3/emails/{id}` |
| Send (transactional) | `POST /marketing/v3/transactional/single-send` |

Marketing email creation requires either: (a) `templatePath` to a template uploaded via `hs upload` to Design Manager, OR (b) reference to an existing email template in the portal. For demo purposes, the simplest path is duplicating an existing email and modifying content.

## CMS landing pages

| Operation | Endpoint |
|-----------|----------|
| Create landing page | `POST /cms/v3/pages/landing-pages` |
| Push live | `POST /cms/v3/pages/landing-pages/{id}/draft/push-live` |
| List templates | `GET /cms/v3/source-code/published/{path}` |

Same template requirement: must reference an existing CMS template via `templatePath`. For demo simplicity, find the portal's default theme template path and reuse it; populate `widgets` JSON with customer-branded content.

## Account info

| Operation | Endpoint | Returns |
|-----------|----------|---------|
| Account details | `GET /account-info/v3/details` | `portalId`, `accountType` (STANDARD / SANDBOX / DEVELOPER_TEST_ACCOUNT), timezone, currency, dataHostingLocation. **Does NOT return subscription tier.** |
| API usage | `GET /account-info/v3/api-usage/daily` | `currentlyInDailyLimit`, daily counter |

For tier verification, use the custom-objects schema endpoint (`GET /crm/v3/schemas` returning 200 = at least one Enterprise hub).

## Lists

| Operation | Endpoint |
|-----------|----------|
| Create list | `POST /crm/v3/lists` |
| Add to MANUAL list | `POST /crm/v3/lists/{listId}/memberships/add` |

Body for active (DYNAMIC) list — uses filter syntax that's easier to copy from the UI than write by hand:
```json
{"name": "Demo: Hot leads", "objectTypeId": "0-1", "processingType": "DYNAMIC", "filterBranch": {...complex...}}
```

For demo purposes, a `MANUAL` list is simpler:
```json
{"name": "Demo: Hot leads", "objectTypeId": "0-1", "processingType": "MANUAL"}
```

## Rate limits

| Tier | Limit |
|------|-------|
| Free / Starter | 100 req / 10s, 250k / day |
| Professional | 110 req / 10s, 500k / day |
| Enterprise | 190 req / 10s, 1M / day |

Search API is more restrictive: 5 req/sec/account regardless of tier. Batch endpoints count as **1 request**, not N.

## Practical patterns

### Backdate engagement timestamps

Pass `hs_timestamp` (epoch milliseconds) on create. Default = "now."

```bash
backdate_ms() {
  # Returns epoch ms for N days ago
  local days=$1
  python3 -c "import time; print(int((time.time() - $days*86400) * 1000))"
}
```

### Find contact ID by email

```bash
curl -s -G "https://api.hubapi.com/crm/v3/objects/contacts/search" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode 'filterGroups=[{"filters":[{"propertyName":"email","operator":"EQ","value":"foo@bar.com"}]}]'
```

### Tag every demo asset

Add a custom property `demo_customer` on contacts/companies/deals, set to the customer slug at creation. Cleanup is one search + delete loop.
