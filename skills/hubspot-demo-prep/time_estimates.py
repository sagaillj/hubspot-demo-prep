#!/usr/bin/env python3
"""
time_estimates.py — compute "time saved vs manual build" for a demo run.

Each phase the builder executes has a per-unit minute estimate (conservative
side of "competent HubSpot admin"). compute_time_saved() multiplies counts
read off the manifest by these estimates and returns the breakdown plus a
formatted total.

Wired into builder.py after Phase 17 (writes manifest["time_saved"]) and
rendered by doc_generator.py (hero stat at top + breakdown table at bottom).

Pure-Python, no external deps. Designed to never raise on a partial manifest:
unknown counts default to 0 and zero-count rows are omitted from the breakdown.
"""
from __future__ import annotations

import re
from typing import Any


# Minutes per unit, sourced from the punch-list item 14 spec table.
MINUTES_PER_UNIT: dict[str, float] = {
    "company": 2,
    "contacts": 3,
    "deals": 3,
    "tickets": 2,
    "engagements": 1,
    "custom_object_schema": 15,
    "custom_object_records": 2,
    "custom_event_def": 8,
    "custom_event_fire": 0.5,
    "form": 6,
    "form_submission": 0.5,
    "lead_score_property": 5,
    "lead_score_backfill_per_contact": 0.5,
    "list": 4,
    "marketing_email": 60,
    "marketing_email_branded_with_hero": 90,
    "workflow_simple": 8,
    "workflow_branching": 15,
    "quote_per_deal": 3,
    "line_item": 1,
    "invoice": 3,
    "marketing_campaign": 8,
    "demo_doc": 30,
    "sandbox_setup": 15,
}


def _len(value: Any) -> int:
    """Best-effort length count for dict/list/None — anything else is 0."""
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return 0


def _classify_workflow(name: str) -> str:
    """Return 'workflow_branching' if the name suggests a multi-branch flow,
    else 'workflow_simple'. Matches the punch-list keywords."""
    n = (name or "").lower()
    for marker in ("branching", "routing", "nps", "detractor"):
        if marker in n:
            return "workflow_branching"
    return "workflow_simple"


def _format_minutes(total_min: int) -> str:
    """Render a total-minutes number in the punch-list display format.

    Brackets:
      <60m       -> '~Xm'
      60-119m    -> '~1h' or '~1h Ym'
      120-299m   -> '~Xh' or '~Xh Ym'  (2h-5h: keep minutes for precision)
      >=300m     -> '~Xh'              (5h+: drop minutes for cleanliness)
    """
    total_min = max(0, int(round(total_min)))
    if total_min < 60:
        return f"~{total_min}m"
    if total_min < 120:
        rem = total_min - 60
        if rem == 0:
            return "~1h"
        return f"~1h {rem}m"
    if total_min < 300:
        hours, rem = divmod(total_min, 60)
        if rem == 0:
            return f"~{hours}h"
        return f"~{hours}h {rem}m"
    return f"~{total_min // 60}h"


def _row(label: str, count: int, minutes_each: float, *, force: bool = False) -> dict | None:
    """Build a breakdown row. Returns None when count is 0 and force=False."""
    if count <= 0 and not force:
        return None
    subtotal = count * minutes_each
    return {
        "label": label,
        "count": count,
        "minutes_each": minutes_each,
        "subtotal_minutes": subtotal,
        "subtotal_pretty": _format_minutes(subtotal),
    }


def compute_time_saved(manifest: dict, plan: dict) -> dict:
    """Compute total time saved vs a manual HubSpot build.

    Reads counts from manifest with safe fallbacks; multiplies by the
    per-unit minute estimates in MINUTES_PER_UNIT. Returns:
        {
          "total_minutes": int,
          "total_pretty": str,           # e.g. "~9h" / "~1h 12m" / "~45m"
          "breakdown": [
            {label, count, minutes_each, subtotal_minutes, subtotal_pretty},
            ...
          ],
        }

    Missing/None manifest fields are treated as zero and their rows are
    omitted (we don't surface "0 invoices · 0 min"). Always-on rows
    (sandbox setup, demo doc, company) are included regardless.
    """
    manifest = manifest or {}
    plan = plan or {}
    M = MINUTES_PER_UNIT

    breakdown: list[dict] = []

    # Always-on: sandbox setup (one-time) and the demo doc itself.
    breakdown.append(_row("Sandbox setup + integration check", 1, M["sandbox_setup"], force=True))
    breakdown.append(_row("Company record", 1, M["company"], force=True))

    # CRM counts.
    n_contacts = _len(manifest.get("contacts"))
    if n_contacts:
        breakdown.append(_row(f"Contacts ({n_contacts})", n_contacts, M["contacts"]))

    n_deals = _len(manifest.get("deals"))
    if n_deals:
        breakdown.append(_row(f"Deals ({n_deals})", n_deals, M["deals"]))

    n_tickets = _len(manifest.get("tickets"))
    if n_tickets:
        breakdown.append(_row(f"Tickets ({n_tickets})", n_tickets, M["tickets"]))

    n_engagements = manifest.get("engagements_count") or 0
    if n_engagements:
        breakdown.append(_row(
            f"Timeline engagements ({n_engagements})",
            int(n_engagements), M["engagements"],
        ))

    # Custom object schema + records.
    co = manifest.get("custom_object") or {}
    if co.get("object_type_id") or co.get("name"):
        breakdown.append(_row("Custom object schema", 1, M["custom_object_schema"], force=True))
        n_records = _len((plan.get("custom_object") or {}).get("records"))
        if n_records:
            breakdown.append(_row(
                f"Custom object records ({n_records})",
                n_records, M["custom_object_records"],
            ))

    # Custom events: definitions + fires.
    n_events = _len(manifest.get("custom_events"))
    if n_events:
        breakdown.append(_row(
            f"Custom event definitions ({n_events})",
            n_events, M["custom_event_def"],
        ))
        # Fires: prefer manifest['custom_events_fired_count'] if present,
        # else infer from plan["custom_events"]["fires"] / similar shapes.
        n_fires = manifest.get("custom_events_fired_count") or 0
        if not n_fires:
            cev = plan.get("custom_events") or {}
            fires = cev.get("fires") if isinstance(cev, dict) else None
            n_fires = _len(fires)
        if n_fires:
            breakdown.append(_row(
                f"Custom event fires ({n_fires})",
                int(n_fires), M["custom_event_fire"],
            ))

    # Forms + submissions.
    n_forms = _len(manifest.get("forms"))
    if n_forms:
        breakdown.append(_row(f"Forms ({n_forms})", n_forms, M["form"]))
    n_subs = manifest.get("form_submissions_count") or 0
    if n_subs:
        breakdown.append(_row(
            f"Form test submissions ({n_subs})",
            int(n_subs), M["form_submission"],
        ))

    # Lead scoring (property + backfill per contact).
    ls = manifest.get("lead_scoring") or {}
    backfilled = ls.get("backfilled") or 0
    if backfilled or ls.get("property"):
        breakdown.append(_row(
            "Lead scoring property", 1, M["lead_score_property"], force=True,
        ))
    if backfilled:
        breakdown.append(_row(
            f"Lead score backfill ({int(backfilled)} contacts)",
            int(backfilled), M["lead_score_backfill_per_contact"],
        ))

    # Lists (segments).
    n_lists = _len(manifest.get("lists"))
    if n_lists:
        breakdown.append(_row(f"Lists / segments ({n_lists})", n_lists, M["list"]))

    # Marketing email (branded-with-hero vs plain).
    me = manifest.get("marketing_email") or {}
    if me.get("id") or me.get("name") or me.get("html_path"):
        if me.get("hero_image_url") or me.get("hero_image_path"):
            breakdown.append(_row(
                "Marketing email (branded, with hero)", 1,
                M["marketing_email_branded_with_hero"], force=True,
            ))
        else:
            breakdown.append(_row(
                "Marketing email", 1, M["marketing_email"], force=True,
            ))

    # Workflows: API-built + manual_steps that describe a workflow.
    # Dedupe across both sources so an API-built workflow with a "Add gap
    # action" manual step doesn't get counted twice.
    workflows = manifest.get("workflows") or {}
    counted_workflow_keys: set[str] = set()
    for wf_name in workflows.keys():
        key = (wf_name or "").strip().lower()
        if key in counted_workflow_keys:
            continue
        counted_workflow_keys.add(key)
        kind = _classify_workflow(wf_name)
        breakdown.append(_row(
            f"Workflow: {wf_name}", 1, M[kind], force=True,
        ))
    for step in (manifest.get("manual_steps") or []):
        item = (step or {}).get("item") or ""
        if "workflow" not in item.lower():
            continue
        # Skip "Add X action to 'name'" follow-ups when the named workflow is
        # already counted from manifest["workflows"]. Same for the bare
        # "Workflow: name" manual step that fires when the API call failed.
        # Extract any quoted name in the item, plus the trailing ": <name>"
        # form, and check both against counted_workflow_keys.
        candidates: list[str] = []
        m_quote = re.findall(r"'([^']+)'", item)
        candidates.extend(c.strip().lower() for c in m_quote)
        if ":" in item:
            tail = item.split(":", 1)[1].strip().lower()
            candidates.append(tail)
        if any(c in counted_workflow_keys for c in candidates if c):
            continue
        # Otherwise count this as a fresh manual workflow.
        kind = _classify_workflow(item)
        breakdown.append(_row(
            f"Workflow (manual): {item[:60]}", 1, M[kind], force=True,
        ))
        for c in candidates:
            if c:
                counted_workflow_keys.add(c)

    # Quotes per deal + line items per quote.
    n_quotes = _len(manifest.get("quotes"))
    if n_quotes:
        breakdown.append(_row(
            f"Quotes ({n_quotes})", n_quotes, M["quote_per_deal"],
        ))
    line_items = manifest.get("line_items") or {}
    n_line_items = sum(_len(v) for v in (line_items.values() if isinstance(line_items, dict) else []))
    if n_line_items:
        breakdown.append(_row(
            f"Quote line items ({n_line_items})",
            n_line_items, M["line_item"],
        ))

    # Invoices.
    n_invoices = _len(manifest.get("invoices"))
    if n_invoices:
        breakdown.append(_row(f"Invoices ({n_invoices})", n_invoices, M["invoice"]))

    # Marketing campaign.
    if manifest.get("campaign_id") or manifest.get("marketing_campaign"):
        breakdown.append(_row(
            "Marketing campaign", 1, M["marketing_campaign"], force=True,
        ))

    # Demo doc itself.
    breakdown.append(_row("Demo doc (writing + linking)", 1, M["demo_doc"], force=True))

    # Filter Nones (zero-count rows).
    breakdown = [row for row in breakdown if row is not None]

    total_minutes = int(round(sum(row["subtotal_minutes"] for row in breakdown)))
    return {
        "total_minutes": total_minutes,
        "total_pretty": _format_minutes(total_minutes),
        "breakdown": breakdown,
    }
