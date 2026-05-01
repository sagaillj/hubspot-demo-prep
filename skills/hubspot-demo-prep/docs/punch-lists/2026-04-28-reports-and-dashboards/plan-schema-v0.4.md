# build-plan.json schema additions for v0.4 — Reports & Dashboards

This document extends the v0.3.0 schema (`../2026-04-26-post-test-tweaks/plan-schema.md`) with the fields v0.4 introduces for funnel-ordered custom events and report/dashboard generation. The v0.3.0 schema remains canonical for everything it defines; v0.4 only adds the blocks below.

**API/UI reality check (verified 2026-04-28):** HubSpot exposes **no public API** for creating reports, dashboards, custom funnel reports, journey reports, or attribution reports. Custom Events have a complete API (define + fire + backdate). So:

- `custom_event_flows` → consumed by `builder.py` Phase 7 (extended). Pure API.
- `playwright_reports` → consumed by the builder's v0.4 reports phase, which delegates to `playwright_phases_extras.py::create_reports_and_dashboards` when that UI automation exists. Until live selectors are captured, the phase records `reports_status: blocked` plus a manual step instead of silently pretending dashboards were built.

Every consumer must continue to implement industry-neutral fallbacks per v0.3.0's contract.

## Top-level fields (additions for v0.4)

```jsonc
{
  // ... existing v0.3.0 fields ...

  // NEW — funnel-ordered custom event flows.
  // Replaces the v0.3.0 random-fire pattern (3 events × first-5 contacts).
  // The orchestrator emits one or more flows; builder.py Phase 7 fires
  // each flow with realistic drop-off across a backdate window.
  //
  // The legacy v0.3.0 `custom_events` array (flat list, no ordering) is
  // still supported for backward compatibility — Phase 7 detects which
  // shape was provided and dispatches accordingly. New plans should use
  // `custom_event_flows` exclusively.
  "custom_event_flows": [
    {
      "name": "saas_acquisition_funnel",       // unique within plan
      "label": "SaaS Acquisition Funnel",      // human-readable
      "events": [
        {
          "step": 1,                            // 1-indexed; defines firing order
          "name": "landing_viewed",
          "label": "Landing page viewed",
          "description": "Visitor hit a marketing landing page",
          "primary_object": "CONTACT",
          "properties": [
            {"name": "page_url", "label": "Page URL", "type": "string"}
          ],
          "demo_property_values": {            // builder uses these as the firing payload
            "page_url": "https://example.com/pricing"
          }
        },
        {"step": 2, "name": "signup_started", "label": "Signup started", "primary_object": "CONTACT", "properties": []},
        {"step": 3, "name": "signup_completed", "label": "Signup completed", "primary_object": "CONTACT", "properties": []},
        {"step": 4, "name": "activation_completed", "label": "Activation completed", "primary_object": "CONTACT", "properties": []},
        {"step": 5, "name": "first_value_action", "label": "First value action", "primary_object": "CONTACT", "properties": []},
        {"step": 6, "name": "upgrade_clicked", "label": "Upgrade clicked", "primary_object": "CONTACT", "properties": []}
      ],
      "firing_strategy": {
        "contact_count": 30,                    // how many distinct contacts to fire through
        "drop_off_rates": [0.60, 0.70, 0.65, 0.55, 0.25],
                                                // % of prior step's contacts who reach this step
                                                // length = events.length - 1; first step is implicit 100%
                                                // example above: 30 → 18 → 12 → 8 → 4 → 1 contacts reach each step
        "date_range_days": 60,                  // backdate spread (occurredAt = now - rand(1, N) days)
        "later_steps_recent": true,             // bias later steps to more-recent dates (momentum)
        "validate_via_get": true                // re-GET each event definition after fire to confirm
                                                // schemas are reachable; HubSpot exposes no read API
                                                // for historical custom-event occurrence counts
      }
    }
  ],

  // NEW — report + dashboard config consumed by Playwright (UI-only).
  // The orchestrator picks 1-3 dashboards from references/best-reports-catalog.md
  // based on prospect signals; each dashboard is 8-12 reports.
  "playwright_reports": {
    "dashboards": [
      {
        "name": "{Company} — Acquisition Funnel",  // audience + outcome naming, not "Sales Dashboard"
        "audience": "VP Marketing",                // for the doc's section header
        "tier_required": "marketing_enterprise",   // gates Sankey/journey reports
        "share_with": "team",                      // "team" | "everyone" | "specific_users" (Enterprise)
        "color_dictionary": {                      // pre-defined stage colors used across every report
          "lead": "#3B82F6",
          "mql": "#06B6D4",
          "sql": "#10B981",
          "customer": "#F59E0B"
        },
        "reports": [
          {
            "name": "Acquisition Funnel (Journey)",      // dashboard tile title — short, action-oriented
            "viz_type": "sankey",                        // see viz_type enum below
            "data_source": "custom_events",
            "events_in_order": [                         // names from custom_event_flows
              "landing_viewed", "signup_started", "signup_completed",
              "activation_completed", "first_value_action"
            ],
            "date_range": "last_60_days",
            "tier_required": "marketing_enterprise"
          },
          {
            "name": "Weekly Signups",
            "viz_type": "line",
            "data_source": "contacts",
            "metric": "contact_count",
            "filter": {"lifecyclestage": "lead"},
            "group_by": "createdate",
            "interval": "week",
            "date_range": "last_12_weeks"
          },
          {
            "name": "Signups This Week",
            "viz_type": "kpi",
            "data_source": "contacts",
            "metric": "contact_count",
            "filter": {"lifecyclestage": "lead", "createdate": "this_week"},
            "comparison": "previous_period"            // adds the delta arrow
          },
          {
            "name": "Signups vs Goal",
            "viz_type": "gauge",
            "data_source": "contacts",
            "metric": "contact_count",
            "goal": 200,
            "palette": "alert_green_to_red"             // HubSpot built-in
          },
          {
            "name": "Signup Source Breakdown",
            "viz_type": "donut",
            "data_source": "contacts",
            "group_by": "hs_analytics_source",
            "date_range": "last_30_days"
          },
          {
            "name": "Trial-to-Paid by Cohort",
            "viz_type": "combination",                  // bars + line dual-axis
            "data_source": "deals",
            "metrics": [
              {"name": "deal_count", "viz": "bar"},
              {"name": "won_rate_pct", "viz": "line"}
            ],
            "group_by": "createdate",
            "interval": "week"
          }
        ]
      }
    ]
  },

  // NEW — feature-showcase helper block for Jordan-style campaign attribution
  // stories. This is a planning contract first: builder.py already creates
  // campaigns, campaign-linked assets, contacts, deals, custom properties,
  // custom events, reports_status/manual steps, and doc links. If a requested
  // campaign/deal association is UI-only or unavailable in the public API, the
  // builder/doc must surface a manual_step rather than pretending it is built.
  //
  // For public-safe Feature Showcase runs, pair this with
  // `feature_showcase.public_safe: true` and use fictional contacts, deals,
  // campaigns, domains, and company names. Do not use real customer data just
  // because the story came from a real Slack/customer example.
  "campaign_attribution_showcase": {
    "story": "Show how deals can be reported by campaign after campaign influence is associated to deals.",
    "campaigns": [
      {
        "name": "Spring Webinar",
        "utm_campaign": "spring-webinar",
        "source": "marketing_email",
        "asset_paths": ["marketing_email", "form"],
        "role": "first_touch"
      },
      {
        "name": "Pricing Page Retargeting",
        "utm_campaign": "pricing-retargeting",
        "source": "paid_social",
        "asset_paths": ["landing_page", "form"],
        "role": "last_touch"
      },
      {
        "name": "Partner Newsletter",
        "utm_campaign": "partner-newsletter",
        "source": "referral",
        "asset_paths": ["marketing_email"],
        "role": "influenced"
      }
    ],
    "contact_paths": [
      {
        "contact_email": "jamie.rivera@example.com",
        "first_touch_campaign": "Spring Webinar",
        "last_touch_campaign": "Pricing Page Retargeting",
        "source_path": ["marketing_email", "landing_page", "form_fill"],
        "deal_name": "Growth Ops Renewal",
        "revenue": 48000
      }
    ],
    "deal_campaign_rollup": {
      "method": "workflow",
      "workflow_name": "Copy contact campaign influence to associated deal",
      "deal_properties": [
        "first_touch_campaign",
        "last_touch_campaign",
        "campaign_influenced_revenue"
      ],
      "manual_step_when_ui_required": true
    },
    "reports": [
      "Deal count by first-touch campaign",
      "Revenue by last-touch campaign",
      "First touch vs last touch comparison",
      "Campaign influenced revenue table"
    ]
  }
}
```

## Field reference

### `custom_event_flows[].firing_strategy`

| Key | Type | Default | Notes |
|---|---|---|---|
| `contact_count` | int | 30 | Funnel renders thin below ~20; 30 produces a visually-meaningful Sankey |
| `drop_off_rates` | array<float 0-1> | varied default `[0.72, 0.61, 0.54, 0.47, 0.39]` repeated as needed | Length = `events.length - 1`. Each value is the retention from the previous step. Builder pads/truncates length mismatches and clamps values outside 0..1, but Phase 2 should emit valid, varied values. |
| `date_range_days` | int | 60 | Spread of backdated `occurredAt` timestamps |
| `later_steps_recent` | bool | true | Step 1 spread evenly; final step biased into the last 30% of the window |
| `validate_via_get` | bool | true | GET event definitions after fire. This confirms schemas exist; HubSpot does not expose a per-occurrence readback endpoint for historical custom-event fires. |

### `playwright_reports.dashboards[].reports[].viz_type` enum

`kpi`, `gauge`, `vertical_bar`, `horizontal_bar`, `line`, `area`, `donut`, `pie`, `summary`, `table`, `pivot_table`, `combination`, `scatter`, `funnel_vertical`, `funnel_horizontal`, `sankey`

`sankey`, `funnel_vertical`, `funnel_horizontal` route to HubSpot's funnel/journey report builders (Sankey requires Marketing Enterprise). Everything else uses the standard custom report builder. The Playwright phase reads this enum and dispatches to the right UI flow.

### `playwright_reports.dashboards[].reports[].data_source` enum

`contacts`, `companies`, `deals`, `tickets`, `engagements`, `custom_events`, `attribution`, `feedback_submissions`, `marketing_emails`, `landing_pages`, plus any `<custom_object_id>` from `manifest["custom_object"]["object_type_id"]`.

### `playwright_reports.dashboards[].reports[].date_range` enum

`today`, `yesterday`, `this_week`, `last_week`, `this_month`, `last_month`, `last_7_days`, `last_30_days`, `last_60_days`, `last_90_days`, `last_12_weeks`, `this_quarter`, `last_quarter`, `this_year`, `last_year`, `all_time`, plus literal ISO ranges `{"start": "2026-01-01", "end": "2026-04-28"}`.

### `playwright_reports.dashboards[].reports[].comparison` enum

`previous_period`, `previous_year`, `none`. Drives the delta arrow on KPI tiles.

## Builder fallback rules (when Phase 2 omits a field)

| Field | Fallback |
|---|---|
| `custom_event_flows` | If absent but legacy `custom_events` is present, fall back to v0.3.0 random-fire behavior. If both absent, skip Phase 7 (current behavior). |
| `custom_event_flows[].firing_strategy.contact_count` | 30 |
| `custom_event_flows[].firing_strategy.drop_off_rates` | Varied retention defaults `[0.72, 0.61, 0.54, 0.47, 0.39]` repeated to length. Avoids the single-line Sankey tell. |
| `custom_event_flows[].firing_strategy.date_range_days` | 60 |
| `custom_event_flows[].firing_strategy.validate_via_get` | true |
| `playwright_reports` | If absent, skip the new Playwright reports phase entirely (no dashboards beyond the v0.3.0 starter dashboard) |
| `playwright_reports.dashboards[].name` | `f"{company_name} — Demo Dashboard"` |
| `playwright_reports.dashboards[].audience` | `"Demo Dashboard"` |
| `playwright_reports.dashboards[].share_with` | `"team"` |
| `playwright_reports.dashboards[].color_dictionary` | `{"lead": branding.primary_color, "customer": "#10B981", ...}` derived from branding |
| `playwright_reports.dashboards[].reports[].date_range` | `last_30_days` |
| `playwright_reports.dashboards[].reports[].comparison` | `previous_period` for KPI tiles, `none` otherwise |
| `playwright_reports.dashboards[].reports[].tier_required` | `marketing_pro` |
| `campaign_attribution_showcase` | If absent, no special attribution story is rendered; use normal `marketing_campaign`, `custom_event_flows`, and `playwright_reports` blocks. |

## Tier degradation rules

When the sandbox tier is below a report's `tier_required`:

| Required | Sandbox actual | Behavior |
|---|---|---|
| `marketing_enterprise` (Sankey, journey) | `marketing_pro` | Substitute with `viz_type: "funnel_vertical"` on the same ordered event sequence. This preserves step-to-step conversion semantics but loses path-branching semantics; record `tier_substituted: true` and add a manual_step explaining the downgrade. |
| `marketing_enterprise` (revenue attribution) | `marketing_pro` | Substitute with `viz_type: "horizontal_bar"` on `data_source: "contacts"` grouped by `hs_analytics_source` (contact-create attribution proxy). |
| `marketing_pro` | `marketing_starter` | Skip report; record manual_step. |

`builder.py` probes tier at startup and writes `manifest["sandbox_tier"]` so the Playwright phase can degrade rather than crash.

## Manifest extensions

After the new Playwright phase runs, manifest gains:

```jsonc
{
  // ... existing manifest keys ...
  "custom_event_flows": {
    "<flow_name>": {
      "events_declared": ["landing_viewed", "signup_started", ...],
      "events_defined": ["landing_viewed", "signup_started", ...],
      "missing_event_schemas": [],
      "fires_per_step": [30, 18, 12, 8, 4, 1],     // attempted per-step survivor counts
      "fires_attempted": 73,
      "fires_succeeded": 73,
      "date_range_days": 60,
      "recency_bias": true,
      "validate_via_get_passed": true,
      "occurred_at_range": ["2026-02-28", "2026-04-28"]
    }
  },
  "reports": {
    "<dashboard_name>::<report_name>": {
      "report_id": "...",                            // from URL after creation
      "url": "https://app.hubspot.com/reports/{portal}/report/{report_id}",
      "viz_type": "sankey",
      "tier_actual": "marketing_enterprise",
      "tier_substituted": false                      // true if degraded from Enterprise → Pro
    }
  },
  "dashboards_v04": {
    "<dashboard_name>": {
      "dashboard_id": "...",
      "url": "https://app.hubspot.com/dashboard/{portal}/{dashboard_id}",
      "report_count": 8,
      "share_with": "team"
    }
  },
  "reports_status": {
    "status": "ok|blocked|error",
    "planned_dashboard_count": 2,
    "planned_report_count": 16,
    "reason": "present when blocked/error"
  },
  "campaign_attribution_showcase": {
    "campaign_count": 3,
    "contact_paths_planned": 10,
    "contacts_patched": 10,
    "deals_patched": 4,
    "missing": [],
    "workflow_manual_step": true
  },
  "sandbox_tier": "marketing_enterprise"             // probed at startup
}
```

The doc generator reads `dashboards_v04` + `reports` and renders a new "Reporting" section with clickable dashboard URLs.

## Removals / migrations

- `manifest["custom_events"]` (the simple dict of event-name → fully-qualified-name from v0.3.0) remains for backward compatibility but is now superseded by `manifest["custom_event_flows"]` for any flow-ordered events.
- v0.3.0's `playwright_dashboard` block (single starter dashboard) is preserved; `playwright_reports.dashboards[]` is additive. A future v0.5 may consolidate them.
