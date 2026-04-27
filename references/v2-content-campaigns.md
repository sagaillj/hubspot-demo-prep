# v2 Capabilities — Marketing Campaigns + Content Remix

Recipes for two demo upgrades that make the day-one HubSpot dashboard look populated and "lived in" for a Shipperz-style prospect. Verified against HubSpot Developer Docs as of 2026-04-26.

Sibling file: `v2-capabilities.md` (sequences, meetings, quotes, invoices, playbooks, snippets, dashboards, branding, form styling, sales workspace leads, CRM cards, KB). No overlap.

---

## Topic A — Marketing Campaigns object

### What it is

A Campaigns object groups marketing assets (emails, forms, CTAs, blog posts, landing pages, social, ads, plus 20+ more types) under a single named campaign. Campaign GET returns rolled-up analytics by asset type. Hub UI: `Marketing > Campaigns`.

### Endpoints

Base: `https://api.hubapi.com`

| Operation | Method | Path |
|---|---|---|
| Create campaign | POST | `/marketing/v3/campaigns` |
| Get campaign (with metrics) | GET | `/marketing/v3/campaigns/{campaignGuid}?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD` |
| List campaigns | GET | `/marketing/v3/campaigns` |
| Update | PATCH | `/marketing/v3/campaigns/{campaignGuid}` |
| Delete | DELETE | `/marketing/v3/campaigns/{campaignGuid}` |
| List assets of a type | GET | `/marketing/v3/campaigns/{campaignGuid}/assets/{assetType}` |
| **Associate asset** | **PUT** | `/marketing/v3/campaigns/{campaignGuid}/assets/{assetType}/{assetId}` |
| Remove asset | DELETE | `/marketing/v3/campaigns/{campaignGuid}/assets/{assetType}/{assetId}` |
| Budget CRUD | POST/GET/PUT/DELETE | `/marketing/v3/campaigns/{campaignGuid}/budget` |
| Spend CRUD | POST/GET/PUT/DELETE | `/marketing/v3/campaigns/{campaignGuid}/spend` |

`{campaignGuid}` is a UUID. Asset PUT takes **no body** — the URL path is the association.

### Required scopes

- `marketing.campaigns.read`
- `marketing.campaigns.write` (required for create/update/delete and asset PUT/DELETE — enforced as of 2025-07-09)
- `marketing.campaigns.revenue.read` (only if surfacing revenue attribution)

These are NOT in the default token scopes for most demo accounts. Builder must verify scope presence and surface a clear error before attempting; a 403 here is silent enough that the demo will look broken without explanation.

### Sample create body

```json
{
  "properties": {
    "hs_name": "Shipperz: Snowbird Season Q1 2026",
    "hs_start_date": "2026-01-06",
    "hs_end_date": "2026-04-15",
    "hs_notes": "Seasonal northbound campaign targeting FL/AZ/TX snowbirds returning to NY/MA/CT/NJ. Mix of email nurture + paid social + landing page.",
    "hs_audience": "Snowbirds, age 60+, owners of vehicles needing seasonal transport",
    "hs_currency_code": "USD",
    "hs_campaign_status": "in_progress",
    "hs_utm": "utm_source=hubspot&utm_medium=email&utm_campaign=snowbird_q1_2026"
  }
}
```

Response returns `id` (the campaignGuid). Save it on every demo asset under a new custom property `demo_campaign_guid` so cleanup can match.

### Asset association — supported types

Verified type strings (use exactly these in the path):

`MARKETING_EMAIL`, `FORM`, `BLOG_POST`, `LANDING_PAGE`, `SITE_PAGE`, `SOCIAL_BROADCAST`, `AD_CAMPAIGN`, `OBJECT_LIST`, `EXTERNAL_WEB_URL`, `WEB_INTERACTIVE` (CTAs), `CTA`, `MARKETING_EVENT`, `MARKETING_SMS`, `SEQUENCE`, `MEETING_EVENT`, `PLAYBOOK`, `FEEDBACK_SURVEY`, `PODCAST_EPISODE`, `SALES_DOCUMENT`, `EMAIL`, `CASE_STUDY`, `KNOWLEDGE_ARTICLE`, `CALL`, `FILE_MANAGER_FILE`, `MEDIA`, `AUTOMATION_PLATFORM_FLOW`.

Example for the Shipperz demo (existing assets in skill):

```bash
# Marketing email 211744773523 -> campaign
curl -X PUT \
  "https://api.hubapi.com/marketing/v3/campaigns/${CAMPAIGN_GUID}/assets/MARKETING_EMAIL/211744773523" \
  -H "Authorization: Bearer $TOKEN"

# NPS form 866a9eb0-c553-49c6-9374-431e82d71b5e -> campaign
curl -X PUT \
  "https://api.hubapi.com/marketing/v3/campaigns/${CAMPAIGN_GUID}/assets/FORM/866a9eb0-c553-49c6-9374-431e82d71b5e" \
  -H "Authorization: Bearer $TOKEN"
```

Custom behavioral events do **not** appear in the supported-asset-type list — needs verification whether they auto-roll-up via the contact's campaign attribution or whether they're invisible in the Campaigns UI. For now: associate the form (form fills are first-class), and trust HubSpot's contact-level attribution to credit the event indirectly.

### Analytics: auto vs seeded

**Auto-populated when assets have real engagement:**
- `MARKETING_EMAIL`: SENT, OPEN, CLICKS
- `FORM`: VIEWS, SUBMISSIONS, CONVERSION_RATE
- `BLOG_POST` / `LANDING_PAGE`: VIEWS, CONTACTS_FIRST_TOUCH, CONTACTS_LAST_TOUCH, SUBMISSIONS, CUSTOMERS
- `SOCIAL_BROADCAST`: per-network clicks (FACEBOOK_CLICKS, LINKEDIN_CLICKS, TWITTER_CLICKS)
- `WEB_INTERACTIVE` (CTAs): VIEWS, CLICKS

The skill already drives backdated form submissions and email engagement. Once the email + form are associated, the Campaigns dashboard auto-fills with those metrics on its next refresh — **no separate analytics seed needed**. This is the magic moment.

There is no public endpoint to write fake metrics. If an asset has zero engagement the metric is zero; the only fix is generating real engagement (which the skill already does for emails and form submits).

### Demo-value rating: **HIGH**

Single dashboard view that shows "your marketing is working" — pulls together assets the skill already creates. Snowbird campaign name is on-narrative for Shipperz. Visual payoff is large because the Campaigns UI looks empty by default in a fresh portal, and one populated campaign reads as "you've been using HubSpot for a while."

### Implementation cost: **SMALL**

- One POST to create campaign, save guid.
- N PUT calls (one per asset, no body) — already-existing IDs.
- Add `demo_campaign_guid` property + tag for cleanup.
- Scope-check + 403 handling: ~30 lines.
- Total: ~80–120 lines in `builder.py`, one new helper module.

### Shipperz-specific example

- **Name:** "Shipperz: Snowbird Season Q1 2026"
- **UTM:** `utm_source=hubspot&utm_medium=email&utm_campaign=snowbird_q1_2026`
- **Associated assets:** the existing snowbird marketing email (id `211744773523`), the NPS form (id `866a9eb0-c553-49c6-9374-431e82d71b5e`), the landing page if the skill builds one, and the static contact list of snowbird ICP contacts (`OBJECT_LIST`).
- **Dashboard on day one shows:** ~1,200 email opens, ~340 clicks, ~45 form submissions, ~12 first-touch contacts, status "In progress," budget $5k of $7.5k spent. Status visible at `/marketing/campaigns` in the portal.

### Sources
- https://developers.hubspot.com/docs/api/marketing/campaigns
- https://developers.hubspot.com/docs/api-reference/marketing-campaigns-public-api-v3/guide
- https://developers.hubspot.com/changelog/new-campaign-api-updates
- https://knowledge.hubspot.com/campaigns/associate-assets-and-content-with-a-campaign

---

## Topic B — Content Remix

### What it is (and what it is NOT)

Content Remix is a Breeze AI feature inside Content Hub Pro/Enterprise. UI: `Content > Remix`. Takes 1–6 source assets (blog, page, doc, URL, video, audio, image) and conversationally generates derivative variants: blog posts, social posts, marketing emails, landing pages, SMS, podcast episodes, ads, video clips, website pages, images.

**There is no public Content Remix API.** The HubSpot Developer Docs and the Knowledge Base Content Remix page contain zero references to `/cms/v3/content-remix`, `/breeze/`, or any equivalent. The feature is UI-only as of 2026-04. Confirmed via search of `developers.hubspot.com` for "breeze" and review of the 2026 changelogs (Jan/Feb/Mar/Spring rollups) — Breeze API surface is limited to Custom Channels (for Customer Agent) and custom workflow actions in Projects, neither of which exposes Remix.

Breeze Studio agents now default to GPT-5 (Spring 2026 update), but this is engine-internal — no developer-callable Remix endpoint shipped.

### Fallback approach: pre-create the equivalent asset set manually

The trick is to **fake the output** of a Content Remix run by building the source asset + a coordinated set of variants, all tagged to the same campaign and using the same headline + hook. Prospect sees: "If we ran your Q1 brochure through Remix, here's what would come out." The demo shows the *shape* of the output, not a live Remix invocation.

#### Source asset: blog post

```
POST /cms/v3/blogs/posts
Scope: content (legacy single scope)
```

Body:
```json
{
  "name": "Snowbird Vehicle Transport: 5 Things to Ask Before You Book",
  "contentGroupId": "<defaultBlogId>",
  "slug": "snowbird-vehicle-transport-5-things-to-ask",
  "blogAuthorId": "<authorId>",
  "metaDescription": "Booking a snowbird transport in Q1? Here are the five questions every winter resident in FL or AZ should ask before paying a deposit.",
  "postBody": "<p>...</p>",
  "state": "PUBLISHED",
  "publishDate": "2026-01-08T13:00:00Z"
}
```

Publish via PATCH state=PUBLISHED, or schedule via `POST /cms/v3/blogs/posts/schedule` with `id` + `publishDate`. Note: the `campaign_name` field is deprecated in v3 — campaign association is now done via the **Campaigns API PUT** above (`assets/BLOG_POST/{postId}`). Needs verification that the post's `id` is the right `assetId` value (HubSpot historically used both `objectId` and `id`; v3 uses `id`).

#### Variant: matching landing page

```
POST /cms/v3/pages/landing-pages
Scope: content
Required body: name, templatePath
```

Same hook as the blog, same UTMs, same campaign. Push live via `POST /cms/v3/pages/landing-pages/{id}/draft/push-live`.

#### Variant: matching marketing email

The skill already builds a marketing email; reuse that flow. Drop the same hook ("5 Things to Ask Before You Book") into subject + preview text and associate to the same campaign.

#### Variant: social posts — **API NOT EXPOSED**

The Social Media Broadcast API (`/broadcast/v1/...`) is **deprecated** and has no replacement. There is no public API to schedule social posts to connected accounts. Two options:

1. Skip social entirely from the Remix demo, lean on email + LP + blog.
2. Create `SOCIAL_BROADCAST`-typed records via the Campaigns API ONLY if the records already exist (i.e., a user manually scheduled them in the UI). For an automated demo this fails — there's no way to create the underlying social broadcast asset programmatically.

Recommendation: **drop social from the Remix demo**, narrate it as "and these would also fan out to LinkedIn + X via the connected accounts." Honest gap, low cost.

#### Variant: podcast episode / video clips

No public CMS API for podcast episodes or video clips. Skip.

### Demo-value rating: **MEDIUM**

The Remix story is a top-three Breeze talking point in HubSpot 2026 marketing. Showing a pre-staged "Remix output" set (blog + LP + email + matching social copy in a Google Doc) gives the prospect a concrete picture without the audit burden of a real Remix run. But it's narration-heavy: the assets exist, but the Remix UI itself is empty unless the prospect runs Remix live (which then takes 30–60s and consumes Breeze credits).

Honest framing for Jeremy: this is a "show the deliverables, demo the process live" hybrid. The skill provides the deliverables; the live Remix run is the demo's punchline.

### Implementation cost: **MEDIUM**

- Blog post create + schedule: ~40 lines.
- Landing page create + push-live: ~50 lines (template path lookup is the painful part — same friction as existing landing-page builder).
- Stitching the 3-asset bundle to the same campaign: ~20 lines (after Topic A is built — heavy reuse).
- A Google Doc section in the prep deliverable explaining "here's the Remix output we pre-staged" so the AE can narrate it: ~30 lines of doc generation.
- Total: ~150–200 lines, plus one new helper. Higher than Topic A because two new CMS endpoints touch templates.

### Shipperz-specific example

- **Source asset:** Blog post titled "Snowbird Vehicle Transport: 5 Things to Ask Before You Book," published 2026-01-08, slug `/blog/snowbird-vehicle-transport-5-things-to-ask`.
- **Pre-staged variants:**
  - Landing page: `/snowbird-q1-checklist` ("Get the 5-question checklist before you book") — captures via the existing NPS form clone.
  - Marketing email: subject "Booking your snowbird transport? Read this first" — uses the same hook, sent to the snowbird-ICP segment.
  - (Social posts: skipped, narrated.)
- **All three assets:** carry `utm_campaign=snowbird_q1_2026`, associated to the "Shipperz: Snowbird Season Q1 2026" campaign from Topic A.
- **What the prospect sees:** a single campaign in `Marketing > Campaigns` with 4 asset types associated (email, form, blog, landing page) and aligned messaging across all four. AE narrates: "this is what one Remix run would produce — and you'd then post it live to LinkedIn + X with one click."

### Sources
- https://knowledge.hubspot.com/blog/repurpose-content-using-ai-with-content-remix
- https://knowledge.hubspot.com/website-and-landing-pages/use-ai-with-content-remix-in-the-content-editor-and-index-pages
- https://developers.hubspot.com/docs/api-reference/cms-posts-v3/guide
- https://developers.hubspot.com/docs/api-reference/cms-pages-v3/landing-pages/post-cms-v3-pages-landing-pages
- https://developers.hubspot.com/docs/api-reference/legacy/social-v1/create-broadcast (deprecated; cited to document the gap)
- https://developers.hubspot.com/changelog/spring-2026-spotlight

---

## Top 3 ranked: if we add only 3 capabilities to v2

Within the two topics covered in this file:

1. **Marketing Campaigns object (Topic A) — DO THIS FIRST.** Highest demo-value-per-line-of-code in either topic. Reuses every asset the skill already creates, populates a dashboard the prospect would otherwise see empty, and lands the "we connect everything to ROI" narrative HubSpot leans on hardest. Small cost (~100 lines), no new templates, no scope bargaining beyond `marketing.campaigns.write`. Ships in one builder iteration.

2. **Content Remix pre-staged bundle (Topic B) — DO SECOND.** Medium cost, medium value, but DEPENDS ON Topic A — the bundle only feels coherent when it's all tagged to one campaign. Without the campaign, the blog/LP/email look orphaned. With it, the AE has a concrete artifact to point at while narrating Breeze's value. Skip the social variant; it's a deprecated-API trap.

3. *(third slot belongs to whichever capability in `v2-capabilities.md` has the highest leverage — likely playbooks or sequences for sales-side narrative, but that's the other agent's call.)*

The reason for this order: Topic A is a force multiplier on every other marketing asset the skill already builds — it doesn't add new assets, it makes the existing ones look organized. Topic B is a force multiplier on Topic A. Doing B without A leaves three assets floating in three separate UI corners, which is a worse demo than the current state.
