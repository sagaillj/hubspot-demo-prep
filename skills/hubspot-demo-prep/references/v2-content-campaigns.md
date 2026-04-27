# v2 Capabilities — Marketing Campaigns + Content Remix

Recipes for two demo upgrades that make the day-one HubSpot dashboard look populated and "lived in" for any prospect. Verified against HubSpot Developer Docs as of 2026-04-26.

Sibling file: `v2-capabilities.md` (sequences, meetings, quotes, invoices, playbooks, snippets, dashboards, branding, form styling, sales workspace leads, CRM cards, KB). No overlap.

> **Read this first — about industry examples in this doc.** The body of this reference uses `{customer_name}`, `{topic}`, `{seasonal_window}`, `{primary_pain}`, and `{cta_action}` placeholders so the pattern applies to any business. Phase 2 must substitute these from the prospect's research, not borrow from prior runs. Industry-specific examples are quarantined to the bottom section ("Worked examples — multiple industries"). Do **not** reuse the wording, audiences, or seasonal hooks from those examples for an unrelated prospect.

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

### Sample create body — generic template

```json
{
  "properties": {
    "hs_name": "{customer_name}: {topic} {seasonal_window}",
    "hs_start_date": "{campaign_start_iso_date}",
    "hs_end_date": "{campaign_end_iso_date}",
    "hs_notes": "{one_paragraph_describing_who_this_targets_and_why_now}",
    "hs_audience": "{audience_description_derived_from_prospect_ICP_research}",
    "hs_currency_code": "USD",
    "hs_campaign_status": "in_progress",
    "hs_utm": "utm_source=hubspot&utm_medium=email&utm_campaign={slugified_campaign_name}"
  }
}
```

Response returns `id` (the campaignGuid). Save it on every demo asset under a new custom property `demo_campaign_guid` so cleanup can match.

### Asset association — supported types

Verified type strings (use exactly these in the path):

`MARKETING_EMAIL`, `FORM`, `BLOG_POST`, `LANDING_PAGE`, `SITE_PAGE`, `SOCIAL_BROADCAST`, `AD_CAMPAIGN`, `OBJECT_LIST`, `EXTERNAL_WEB_URL`, `WEB_INTERACTIVE` (CTAs), `CTA`, `MARKETING_EVENT`, `MARKETING_SMS`, `SEQUENCE`, `MEETING_EVENT`, `PLAYBOOK`, `FEEDBACK_SURVEY`, `PODCAST_EPISODE`, `SALES_DOCUMENT`, `EMAIL`, `CASE_STUDY`, `KNOWLEDGE_ARTICLE`, `CALL`, `FILE_MANAGER_FILE`, `MEDIA`, `AUTOMATION_PLATFORM_FLOW`.

Generic association pattern (existing assets the skill already created):

```bash
# Associate the marketing email already built by the email phase
curl -X PUT \
  "https://api.hubapi.com/marketing/v3/campaigns/${CAMPAIGN_GUID}/assets/MARKETING_EMAIL/${EMAIL_ID}" \
  -H "Authorization: Bearer $TOKEN"

# Associate the form already built by the forms phase
curl -X PUT \
  "https://api.hubapi.com/marketing/v3/campaigns/${CAMPAIGN_GUID}/assets/FORM/${FORM_ID}" \
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

Single dashboard view that shows "your marketing is working" — pulls together assets the skill already creates. A campaign name pulled from the prospect's actual seasonality / GTM cycle is on-narrative for any business. Visual payoff is large because the Campaigns UI looks empty by default in a fresh portal, and one populated campaign reads as "you've been using HubSpot for a while."

### Implementation cost: **SMALL**

- One POST to create campaign, save guid.
- N PUT calls (one per asset, no body) — already-existing IDs.
- Add `demo_campaign_guid` property + tag for cleanup.
- Scope-check + 403 handling: ~30 lines.
- Total: ~80–120 lines in `builder.py`, one new helper module.

---

## Topic B — Content Remix

### What it is (and what it is NOT)

Content Remix is a Breeze AI feature inside Content Hub Pro/Enterprise. UI: `Content > Remix`. Takes 1–6 source assets (blog, page, doc, URL, video, audio, image) and conversationally generates derivative variants: blog posts, social posts, marketing emails, landing pages, SMS, podcast episodes, ads, video clips, website pages, images.

**There is no public Content Remix API.** The HubSpot Developer Docs and the Knowledge Base Content Remix page contain zero references to `/cms/v3/content-remix`, `/breeze/`, or any equivalent. The feature is UI-only as of 2026-04. Confirmed via search of `developers.hubspot.com` for "breeze" and review of the 2026 changelogs (Jan/Feb/Mar/Spring rollups) — Breeze API surface is limited to Custom Channels (for Customer Agent) and custom workflow actions in Projects, neither of which exposes Remix.

Breeze Studio agents now default to GPT-5 (Spring 2026 update), but this is engine-internal — no developer-callable Remix endpoint shipped.

### Fallback approach: pre-create the equivalent asset set manually

The trick is to **fake the output** of a Content Remix run by building the source asset + a coordinated set of variants, all tagged to the same campaign and using the same headline + hook. Prospect sees: "If we ran your {topic} brochure through Remix, here's what would come out." The demo shows the *shape* of the output, not a live Remix invocation.

#### Source asset: blog post — generic template

```
POST /cms/v3/blogs/posts
Scope: content (legacy single scope)
```

Body:
```json
{
  "name": "{topic}: {numbered_promise} Things to {cta_action} Before You {decision_moment}",
  "contentGroupId": "<defaultBlogId>",
  "slug": "{slugified_topic_and_promise}",
  "blogAuthorId": "<authorId>",
  "metaDescription": "{one_sentence_summary_naming_audience_and_seasonal_window}",
  "postBody": "<p>...</p>",
  "state": "PUBLISHED",
  "publishDate": "{publish_iso_datetime}"
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

The skill already builds a marketing email; reuse that flow. Drop the same hook (`{numbered_promise} Things to {cta_action} Before You {decision_moment}`) into subject + preview text and associate to the same campaign.

#### Variant: lead magnet (gate the same hook)

The blog gives away the headline; the lead magnet gives away the full checklist / template / scorecard derived from the same hook. Build it as either a Files-API-uploaded PDF or a long-form landing page behind the existing form. Same UTM, same campaign association.

#### Variant: social posts — **API NOT EXPOSED**

The Social Media Broadcast API (`/broadcast/v1/...`) is **deprecated** and has no replacement. There is no public API to schedule social posts to connected accounts. Two options:

1. Skip social entirely from the Remix demo, lean on email + LP + blog + lead magnet.
2. Create `SOCIAL_BROADCAST`-typed records via the Campaigns API ONLY if the records already exist (i.e., a user manually scheduled them in the UI). For an automated demo this fails — there's no way to create the underlying social broadcast asset programmatically.

Recommendation: **drop social from the Remix demo**, narrate it as "and these would also fan out to LinkedIn + X via the connected accounts." Honest gap, low cost.

#### Variant: podcast episode / video clips

No public CMS API for podcast episodes or video clips. Skip.

### Demo-value rating: **MEDIUM**

The Remix story is a top-three Breeze talking point in HubSpot 2026 marketing. Showing a pre-staged "Remix output" set (blog + LP + email + matching social copy in a Google Doc) gives the prospect a concrete picture without the audit burden of a real Remix run. But it's narration-heavy: the assets exist, but the Remix UI itself is empty unless the prospect runs Remix live (which then takes 30–60s and consumes Breeze credits).

Honest framing: this is a "show the deliverables, demo the process live" hybrid. The skill provides the deliverables; the live Remix run is the demo's punchline.

### Implementation cost: **MEDIUM**

- Blog post create + schedule: ~40 lines.
- Landing page create + push-live: ~50 lines (template path lookup is the painful part — same friction as existing landing-page builder).
- Stitching the bundle to the same campaign: ~20 lines (after Topic A is built — heavy reuse).
- A Google Doc section in the prep deliverable explaining "here's the Remix output we pre-staged" so the AE can narrate it: ~30 lines of doc generation.
- Total: ~150–200 lines, plus one new helper. Higher than Topic A because two new CMS endpoints touch templates.

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

---

## Worked examples — multiple industries

The same generic template (Campaign + Email + Landing Page + Blog Post + Lead Magnet, all tagged to one UTM and campaign) applied to three very different prospects. **These are illustrations of the shape — do not reuse copy, audiences, or seasonal hooks across runs.**

### Example 1 — Auto transport (seasonal: snowbird returns)

- **Campaign name:** "{customer_name}: Snowbird Season Q1"
- **Window:** Jan 6 – Apr 15
- **Audience:** Owners 60+ in FL/AZ/TX with vehicles needing northbound transport in spring
- **Blog:** "Snowbird Vehicle Transport: 5 Things to Ask Before You Book"
- **LP / lead magnet:** `/snowbird-q1-checklist` — "Get the 5-question checklist before you book"
- **Email subject:** "Booking your snowbird transport? Read this first"
- **UTM:** `utm_campaign=snowbird_q1`

### Example 2 — Marine audio installer (seasonal: pre-summer marine tune-up)

- **Campaign name:** "{customer_name}: Pre-Summer Marine Tune-Up"
- **Window:** Mar 1 – May 31
- **Audience:** Boat owners booking spring rigging in coastal markets, last-installed 2+ seasons ago
- **Blog:** "5 Marine Audio Upgrades That Actually Survive Saltwater Season"
- **LP / lead magnet:** `/marine-spring-tune-up` — "Free 10-point pre-season audio inspection checklist"
- **Email subject:** "Splash day's coming — is your stereo ready?"
- **UTM:** `utm_campaign=marine_pre_summer`

### Example 3 — HVAC contractor (seasonal: pre-winter furnace tune-up)

- **Campaign name:** "{customer_name}: Pre-Winter Furnace Tune-Up"
- **Window:** Sep 15 – Nov 30
- **Audience:** Homeowners in service area, last-serviced > 18 months ago
- **Blog:** "7 Furnace Warning Signs You'll Wish You Caught in October, Not January"
- **LP / lead magnet:** `/winter-ready-checklist` — "Get the 12-point furnace safety checklist"
- **Email subject:** "Your furnace has been off for 6 months. Let's make sure it starts."
- **UTM:** `utm_campaign=hvac_pre_winter`

(Optional fourth pattern for B2B SaaS: "{customer_name}: Q1 Activation Push" targeting trial-signups-without-first-value, blog "5 things every {ICP} should set up in their first week," LP gating an interactive setup checklist, email subject "You signed up 9 days ago — let's get you to your first {value moment}", UTM `utm_campaign=q1_activation`. Same structural shape, completely different surface.)

The point of all three: **same five-asset bundle, same campaign + UTM stitching, same Phase 2 fill-in-the-blanks**, completely different industry, audience, and seasonal hook. Phase 2 must derive these from the prospect's actual research — never reuse the wording above.
