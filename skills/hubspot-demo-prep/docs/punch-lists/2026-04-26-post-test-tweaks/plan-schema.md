# build-plan.json schema additions for v0.3.0

This document is the single source of truth for the plan-schema extension that ships with v0.3.0. Phase 2 (the orchestrator Claude session) writes these fields. `builder.py`, `doc_generator.py`, and `playwright_phases_extras.py` consume them. Every consumer must implement a safe industry-neutral fallback when a field is missing — the skill must not break if Phase 2 omits a field.

## Top-level fields (additions)

```jsonc
{
  // ... existing fields ...

  // Deal pipeline definition (consumed by builder Phase 4).
  // Each stage MUST be an object with `label` (string) and `probability`
  // (float 0.0-1.0). Bare-string stages will crash builder.py — Phase 4
  // indexes `s["label"]` and `s["probability"]` directly. As of 2026-04-27
  // builder.py also coerces bare-string stages defensively, but plans should
  // emit the object form.
  "deal_pipeline": {
    "name": "{Industry} Pipeline (Demo)",
    "stages": [
      {"label": "Stage Name", "probability": 0.10},   // probability is 0.0-1.0
      {"label": "Next Stage", "probability": 0.30},
      // ... 4-7 stages typical
    ]
  },

  // Deal records (consumed by builder Phase 4 alongside deal_pipeline).
  // builder.py reads `d["name"]`, `d["stage"]` (must match a stage label
  // exactly from deal_pipeline.stages above), and `d.get("amount", 5000)`.
  // Note v0.3.1 walkthrough caught: do NOT use `dealname`, `stage_label`,
  // or `closedate_offset_days` — those are HubSpot-internal property names
  // that builder.py does NOT read. Use the simple keys below.
  "deals": [
    {
      "name": "Acme Corp - Q3 Renewal",
      "stage": "Stage Name",          // MUST match deal_pipeline.stages[i].label
      "amount": 12500,                 // USD; defaults to 5000 if omitted
      "closedate": "2026-06-30"        // optional, ISO 8601
    }
  ],

  // NEW — branding / theming
  "branding": {
    "primary_color": "#0070F0",       // hex; existed but now load-bearing
    "secondary_color": "#1A1A1A",     // hex; replaces #FF6B35 transport-orange fallback
    "accent_color": "#3B82F6",        // hex; replaces #FF6B35 transport-orange fallback
    "neutral_dark": "#111827",        // for body/title text in doc
    "neutral_light": "#F9FAFB",       // for backgrounds

    // Fix F (2026-04-26): logo persistence. Phase 1 (helpers/01-research.sh)
    // always runs a Playwright logo screenshot to {work_dir}/logo.png and
    // records the path in research.json -> branding.logo_path. Phase 2
    // copies that path into plan["branding"]["logo_path"]. builder.py's
    // marketing_email phase reads logo_path, uploads to HubSpot Files, and
    // populates the HubSpot CDN URL into plan/manifest. doc_generator reads
    // the HubSpot URL (via manifest) for the doc banner.
    "logo_path": "/tmp/demo-prep-{slug}/logo.png",   // local Playwright screenshot path
    "logo_url": "https://...hubspot.com/...",        // HubSpot CDN URL after upload (set by builder)
    "logo_hubspot_file_id": "..."                    // HubSpot Files ID for cleanup (set by builder)
  },

  // NEW — naming / branding for HubSpot-side artifacts
  "property_group": {
    "name": "{slug}_demo_properties",  // builder default: f"{slug}_demo_properties"
    "label": "Demo ({company_name})"   // builder default: f"Demo ({company_name})"
  },

  // NEW — content pools used by create_engagements
  "activity_content": {
    "notes_pool": [
      "Customer asked about availability for the {service} package — sent the PDF.",
      "Spoke with {firstname}; they're comparing us against {competitor_or_industry_alt}. Following up Friday.",
      "Confirmed install/delivery date for {month}; tech assigned."
    ],
    "tasks_pool": [
      "Follow up on {service} pricing",
      "Send {industry_term} case studies",
      "Schedule technical deep-dive",
      "Review proposal",
      "Draft contract"
    ],
    "calls_pool": [
      {"title": "Discovery call", "body": "{firstname} explained their current setup; pain is {pain_point}. Walked through {service}; they want a follow-up demo."},
      {"title": "Pricing discussion", "body": "Reviewed the {service} package; {firstname} asked about {pricing_objection}. Sent the spec sheet."},
      {"title": "Technical questions", "body": "Customer wanted to confirm compatibility with {existing_setup}. Confirmed; offered an on-site survey."}
    ],
    "meetings_pool": [
      {"title": "Demo session", "body": "Walked {firstname} through the {service} workflow live. Decision-maker on the call."},
      {"title": "Solutioning workshop", "body": "Mapped {firstname}'s current process to our solution; identified 3 quick wins."}
    ],
    "emails_pool": [
      {"subject": "Re: {service} consult — next steps", "body": "Hi {firstname}, here's the proposal as discussed. Available for questions any time."},
      {"subject": "Quick question on the {industry_term} option", "body": "Following up on the {industry_term} you asked about — see attached spec."},
      {"subject": "Demo recap + next steps", "body": "Great to walk through {service} with you. Recapping next steps below."}
    ],
    // Per-contact unique engagements (preferred; falls back to pool if absent)
    "per_contact_engagements": {
      "<contact_email>": [
        {"type": "note", "body": "...specific to this contact and deal...", "ts_offset_days": 12},
        {"type": "call", "title": "...", "body": "...", "duration_ms": 1200000, "ts_offset_days": 8},
        {"type": "meeting", "title": "...", "body": "...", "ts_offset_days": 5},
        {"type": "email", "subject": "...", "body": "...", "ts_offset_days": 2}
      ]
    },
    // Lead config (replaces hardcoded labels/sources)
    "lead_label_template": "{industry_noun} inquiry",  // default: "demo inquiry"
    "lead_labels": ["WARM", "HOT", "COLD"],            // override allowed
    "lead_sources": ["Web form", "Inbound call", "Referral", "Trade show", "Cold email", "LinkedIn outreach"]
  },

  // NEW — quote line items (builder default: see fallback below)
  "quote_catalog": [
    {"name": "{service or product line item}", "price": "<usd>", "description": "<optional>"},
    // ... 5-7 items appropriate to industry
  ],

  // EXTENDED — marketing email
  "marketing_email": {
    "name": "...",
    "subject": "...",
    "from_name": "...",
    "hero_image_path": "...",      // existing — populated by image-gen helper (item 1)
    "hero_image_url": "...",       // existing
    // NEW
    "body_html": "<full inline-styled HTML body>",  // if absent, builder uses generic fallback
    "cta_text": "Schedule a consult",
    "cta_url": "https://example.com/contact",
    "cta_color": "#3B82F6",
    "footer_tagline": "{company_name}",  // builder default: company_name only (no industry suffix)
    "steps": [                            // optional structured "what happens next" list
      {"timing": "Within 1 hour", "detail": "..."},
      {"timing": "Within 24 hours", "detail": "..."},
      {"timing": "Day of {key_event}", "detail": "..."}
    ]
  },

  // NEW — marketing campaign (replaces hardcoded Snowbird Season)
  "marketing_campaign": {
    "name": "{company}: {seasonal_or_topical_campaign_name}",
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "notes": "{free-text rationale, prospect-specific}",
    "audience": "{prospect-specific audience description}",
    "utm_campaign": "{slug-shaped utm string}"
  },

  // EXTENDED — forms (NPS form support)
  // NOTE (verified 2026-04-27): the v3 Forms API authoritative field-type list
  // is [datepicker, dropdown, email, file, mobile_phone, multi_line_text,
  // multiple_checkboxes, number, payment_link_radio, phone, radio,
  // single_checkbox, single_line_text]. The previous schema listed
  // `dropdown_select` — that value is silently rejected by the API. Use
  // `dropdown` instead. Each dropdown option MUST include a `displayOrder`
  // integer (builder.py auto-injects this if omitted, but plans should set it
  // explicitly to control ordering).
  //
  // RECOMMENDED for NPS scales (Fix E1, 2026-04-26): use `field_type: "radio"`
  // with 10 options (values "1" through "10"). The `number` field type forces
  // free-text entry, which looks unprofessional in a demo. `radio` renders a
  // horizontal button-row UX that matches industry NPS form convention.
  // builder.py auto-populates the 1-10 ladder for any radio field named
  // `nps_score` (or any radio field with `min:1, max:10`) when `options` is
  // omitted, so plans don't have to enumerate ten dicts inline.
  "forms": [
    {
      "name": "...",
      "fields": [
        {"name": "...", "label": "...", "field_type": "single_line_text|email|phone|mobile_phone|dropdown|radio|multi_line_text|number|datepicker|multiple_checkboxes|single_checkbox|file", "required": true,
         "options": [{"label": "1", "value": "1", "displayOrder": 1}],   // required for dropdown + radio; displayOrder is 1-indexed
         "min": 1, "max": 10                            // for number OR radio types when modeling 1-10 NPS (radio auto-populates ladder)
        }
      ],
      "submit_text": "...",
      "test_submissions": 5,
      "theme": {                                      // NEW — for branded NPS form
        "submit_button_color": "{primary_hex}",
        "submit_text_color": "#FFFFFF"
      },
      "test_submission_data": {                       // NEW — replaces hardcoded Alex/Jordan/Taylor pool
        "first_names": ["..."],
        "last_names": ["..."],
        "score_distribution": {"9-10": 0.5, "7-8": 0.3, "1-6": 0.2},  // for NPS
        "feedback_pool": ["Great service.", "Quick turnaround.", "..."]
      }
    }
  ],

  // NEW — recommendation_text override (prevents phantom-number bugs)
  "recommendation_text": "Lead with the timeline on {sample_contact_name}. Highlight {agenda_item_1}, then {custom_object_or_event}, close on {marketing_or_lead_scoring}.",
  // If absent, doc_generator's _recommendation_text falls back to a templated default that ONLY references manifest values.

  // NEW — playwright dashboard config (item 9 / agent 3)
  "playwright_dashboard": {
    "name": "{company_name} Daily Snapshot",
    "filter_pipeline_name": "{actual_pipeline_name_from_plan}",
    "filter_stages": ["{prospect-specific stages here}"]
  },

  // NEW — playwright_phases.py (main file) consumption (FIX-1, post-Codex review)
  "seo_targets": [
    "{primary keyword for prospect, e.g. 'marine audio installation Merrimack NH'}",
    "{secondary keyword}"
    // builder fallback: research["industry"] → skip SEO step gracefully
  ],
  "outbound_sequence": {
    "name": "{customer_name} Q{N} outbound prospecting",
    "steps": [
      {"subject": "{neutral subject — no industry leak from prior runs}",
       "body": "{1-2 sentence neutral opener tied to prospect's pain}"}
    ]
    // builder fallback: f"{customer_name} - Outbound" + neutral copy
  },
  "quote_template": {
    "intro_copy": "Thanks for requesting a quote with {company_name}. Here's what happens next: 1. We confirm your details. 2. You receive a personalized proposal. 3. We hand-off to your dedicated rep."
    // builder fallback: this exact neutral copy with {company_name} substitution
  },

  // NEW — doc-replacement explicit opt-in (FIX-2 B, post-Codex security review)
  "doc_replacement_id": "{drive_doc_id_to_overwrite}",
  "doc_replacement_acknowledged_slug": "{slug}",  // MUST match self.slug or replacement is refused
}
```

## Builder fallback rules (when Phase 2 omits a field)

| Field | Fallback |
|-------|----------|
| `branding.secondary_color` | `"#1A1A1A"` (near-black, brand-neutral) |
| `branding.accent_color` | `"#3B82F6"` (slate blue) |
| `branding.logo_path` | Read from `research.branding.logo_path` (Playwright capture). If still absent, builder skips the logo strip (no broken image). |
| `branding.logo_url` | Set by builder.py after HubSpot Files upload. |
| `branding.logo_hubspot_file_id` | Set by builder.py for cleanup. |
| `property_group.name/label` | `f"{slug}_demo_properties"` / `f"Demo ({company_name})"` |
| `activity_content.lead_label_template` | `"demo inquiry"` |
| `activity_content.lead_labels` | `["WARM","HOT","COLD"]` |
| `activity_content.lead_sources` | `["Web form","Inbound call","Referral","Trade show","Cold email","LinkedIn outreach"]` |
| `activity_content.notes_pool` | `["Touchpoint with {firstname}.","Discovery call notes.","Follow-up summary."]` |
| `activity_content.calls_pool` | `[{"title":"Discovery call","body":"Discussed needs."},{"title":"Pricing discussion","body":"Walked through pricing."}]` |
| `activity_content.meetings_pool` | `[{"title":"Demo session","body":"Walked through capabilities."}]` |
| `activity_content.emails_pool` | `[{"subject":"Re: Following up","body":"Following up on our conversation."}]` |
| `activity_content.per_contact_engagements` | If absent, builder selects randomly from pools (current behavior). |
| `quote_catalog` | Generic neutral 5-item: `[{"name":"Initial consultation","price":"250"},{"name":"Standard service tier","price":"850"},{"name":"Premium service tier","price":"2400"},{"name":"Premium add-on","price":"450"},{"name":"Extended support","price":"150"}]` |
| `marketing_email.body_html` | Generic neutral templated body — NO transport-specific copy |
| `marketing_email.cta_color` | `branding.primary_color` |
| `marketing_email.footer_tagline` | `company_name` only |
| `marketing_email.steps` | `[{"timing":"Within 1 hour","detail":"We confirm your details."},{"timing":"Within 24 hours","detail":"You receive a personalized proposal."},{"timing":"Next step","detail":"Hand-off to your dedicated rep."}]` |
| `marketing_campaign` | `{name: f"{company}: {current_quarter} Campaign", start_date: today, end_date: today+90d, notes: "Quarterly nurture campaign.", audience: "Active prospects.", utm_campaign: f"{slug}_{current_quarter}"}` |
| `forms[].theme` | `{submit_button_color: branding.primary_color}` |
| `forms[].test_submission_data.first_names/last_names` | Current generic pool (Alex/Jordan/etc) |
| `recommendation_text` | Computed from manifest — strips any `$<number>` not in `manifest["deals"]` |
| `playwright_dashboard.name` | `f"{company_name} Daily Snapshot"` |
| `playwright_dashboard.filter_pipeline_name` | `manifest["pipeline"]["name"]` |
| `playwright_dashboard.filter_stages` | `manifest["pipeline"]["stages"]` (first 3) |

## Removals (no longer hardcoded; deleted entirely)
- `SHIPPERZ_ORANGE`, `SHIPPERZ_DARK` constant names → `BRAND_ACCENT_ORANGE`, `DARK_TEXT`
- `"shipperz_demo_properties"` literal
- `"Shipperz Demo"` literal
- `if (self.slug == "shipperzinc" and locked_id)` Shipperz-specific Doc branching → generalize via `plan["doc_replacement_id"]` or remove
- `"shipperz-banner.png"` slug check → already replaced by `f"{slug}-banner.png"` at L201
- `"Shipperz Daily Snapshot"` in playwright_phases_extras.py
- `pipeline = Shipperz` filter literal
- Any `"auto transport"`, `"snowbird"`, `"vehicle and route"` strings in builder.py
