#!/usr/bin/env python3
"""
hubspot-demo-prep — production builder

Replaces the bash helpers with a single Python module that runs the entire
build phase. Reads /tmp/demo-prep-<slug>/{build-plan.json, research.json}
and writes manifest.json. Designed to be invoked from the SKILL.md
orchestration layer or directly:

    python3 builder.py <slug>

All HubSpot API calls go through HubSpotClient with proper status checks.
Engagement creation runs in parallel (ThreadPoolExecutor) within HubSpot's
rate limits. Workflow API uses correct v4 body shape. Marketing email
includes AI-generated hero image via Recraft (when available).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import random
import datetime
import urllib.request
import urllib.error
import urllib.parse
import base64
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# Optional UI-automation phases (no public API). Installed lazily.
try:
    import playwright_phases  # type: ignore
    PLAYWRIGHT_PHASES_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_PHASES_AVAILABLE = False

try:
    import playwright_phases_extras  # type: ignore
    PLAYWRIGHT_EXTRAS_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_EXTRAS_AVAILABLE = False

# ---- Constants ----

# Validated against HubSpot's industry enum (2026-04-26).
VALID_INDUSTRIES = {
    "ACCOUNTING", "AIRLINES_AVIATION", "ALTERNATIVE_DISPUTE_RESOLUTION",
    "ALTERNATIVE_MEDICINE", "ANIMATION", "APPAREL_FASHION",
    "ARCHITECTURE_PLANNING", "ARTS_AND_CRAFTS", "AUTOMOTIVE",
    "AVIATION_AEROSPACE", "BANKING", "BIOTECHNOLOGY", "BROADCAST_MEDIA",
    "BUILDING_MATERIALS", "BUSINESS_SUPPLIES_AND_EQUIPMENT",
    "CAPITAL_MARKETS", "CHEMICALS", "CIVIC_SOCIAL_ORGANIZATION",
    "CIVIL_ENGINEERING", "COMMERCIAL_REAL_ESTATE",
    "COMPUTER_NETWORK_SECURITY", "COMPUTER_GAMES", "COMPUTER_HARDWARE",
    "COMPUTER_NETWORKING", "COMPUTER_SOFTWARE", "INTERNET",
    "CONSTRUCTION", "CONSUMER_ELECTRONICS", "CONSUMER_GOODS",
    "CONSUMER_SERVICES", "COSMETICS", "DAIRY", "DEFENSE_SPACE", "DESIGN",
    "EDUCATION_MANAGEMENT", "E_LEARNING",
    "ELECTRICAL_ELECTRONIC_MANUFACTURING", "ENTERTAINMENT",
    "ENVIRONMENTAL_SERVICES", "EVENTS_SERVICES", "EXECUTIVE_OFFICE",
    "FACILITIES_SERVICES", "FARMING", "FINANCIAL_SERVICES", "FINE_ART",
    "FISHERY", "FOOD_BEVERAGES", "FOOD_PRODUCTION", "FUND_RAISING",
    "FURNITURE", "GAMBLING_CASINOS", "GLASS_CERAMICS_CONCRETE",
    "GOVERNMENT_ADMINISTRATION", "GOVERNMENT_RELATIONS", "GRAPHIC_DESIGN",
    "HEALTH_WELLNESS_AND_FITNESS", "HIGHER_EDUCATION",
    "HOSPITAL_HEALTH_CARE", "HOSPITALITY", "HUMAN_RESOURCES",
    "IMPORT_AND_EXPORT", "INDIVIDUAL_FAMILY_SERVICES",
    "INDUSTRIAL_AUTOMATION", "INFORMATION_SERVICES",
    "INFORMATION_TECHNOLOGY_AND_SERVICES", "INSURANCE",
    "INTERNATIONAL_AFFAIRS", "INTERNATIONAL_TRADE_AND_DEVELOPMENT",
    "INVESTMENT_BANKING", "INVESTMENT_MANAGEMENT", "JUDICIARY",
    "LAW_ENFORCEMENT", "LAW_PRACTICE", "LEGAL_SERVICES",
    "LEGISLATIVE_OFFICE", "LEISURE_TRAVEL_TOURISM", "LIBRARIES",
    "LOGISTICS_AND_SUPPLY_CHAIN", "LUXURY_GOODS_JEWELRY", "MACHINERY",
    "MANAGEMENT_CONSULTING", "MARITIME", "MARKET_RESEARCH",
    "MARKETING_AND_ADVERTISING", "MECHANICAL_OR_INDUSTRIAL_ENGINEERING",
    "MEDIA_PRODUCTION", "MEDICAL_DEVICES", "MEDICAL_PRACTICE",
    "MENTAL_HEALTH_CARE", "MILITARY", "MINING_METALS",
    "MOTION_PICTURES_AND_FILM", "MUSEUMS_AND_INSTITUTIONS", "MUSIC",
    "NANOTECHNOLOGY", "NEWSPAPERS", "NON_PROFIT_ORGANIZATION_MANAGEMENT",
    "OIL_ENERGY", "ONLINE_MEDIA", "OUTSOURCING_OFFSHORING",
    "PACKAGE_FREIGHT_DELIVERY", "PACKAGING_AND_CONTAINERS",
    "PAPER_FOREST_PRODUCTS", "PERFORMING_ARTS", "PHARMACEUTICALS",
    "PHILANTHROPY", "PHOTOGRAPHY", "PLASTICS", "POLITICAL_ORGANIZATION",
    "PRIMARY_SECONDARY_EDUCATION", "PRINTING",
    "PROFESSIONAL_TRAINING_COACHING", "PROGRAM_DEVELOPMENT",
    "PUBLIC_POLICY", "PUBLIC_RELATIONS_AND_COMMUNICATIONS",
    "PUBLIC_SAFETY", "PUBLISHING", "RAILROAD_MANUFACTURE", "RANCHING",
    "REAL_ESTATE", "RECREATIONAL_FACILITIES_AND_SERVICES",
    "RELIGIOUS_INSTITUTIONS", "RENEWABLES_ENVIRONMENT", "RESEARCH",
    "RESTAURANTS", "RETAIL", "SECURITY_AND_INVESTIGATIONS",
    "SEMICONDUCTORS", "SHIPBUILDING", "SPORTING_GOODS", "SPORTS",
    "STAFFING_AND_RECRUITING", "SUPERMARKETS", "TELECOMMUNICATIONS",
    "TEXTILES", "THINK_TANKS", "TOBACCO",
    "TRANSLATION_AND_LOCALIZATION", "TRANSPORTATION_TRUCKING_RAILROAD",
    "UTILITIES", "VENTURE_CAPITAL_PRIVATE_EQUITY", "VETERINARY",
    "WAREHOUSING", "WHOLESALE", "WINE_AND_SPIRITS", "WIRELESS",
    "WRITING_AND_EDITING", "MOBILE_GAMES",
}

# Association type IDs (HubSpot-defined). https://developers.hubspot.com/docs/api/crm/associations
ASSOC = {
    "contact_to_company": 1,
    "deal_to_contact": 3,
    "deal_to_company": 5,
    "ticket_to_contact": 16,
    "ticket_to_company": 26,
    "note_to_contact": 202,
    "task_to_contact": 204,
    "call_to_contact": 194,
    "meeting_to_contact": 200,
    "email_to_contact": 198,
    # v2 additions
    "lead_to_contact": 578,
    "quote_to_deal": 64,
    "quote_to_contact": 69,        # was 71 — 71 is a company-side type, caused INVALID_FROM_OBJECT
    "quote_to_line_item": 67,
    "quote_to_template": 286,
    "invoice_to_contact": 177,
    "invoice_to_line_item": 409,   # was 181 — 181 is a company-side type, caused INVALID_FROM_OBJECT
}

# HubSpot rate limits per tier (Enterprise = 190 req / 10s)
RATE_LIMIT_PER_10S = 150  # leave headroom

# Private App scopes the v2 builder needs end-to-end. Verified at startup
# against POST /oauth/v2/private-apps/get/access-token-info so missing scopes
# fail fast with a re-auth deep link rather than silently 403'ing mid-run.
REQUIRED_SCOPES = {
    # Core CRM objects
    "crm.objects.contacts.write",
    "crm.objects.companies.write",
    "crm.objects.deals.write",
    "tickets",  # HubSpot's tickets scope is the legacy short form
    # Custom objects + property schemas
    "crm.objects.custom.write",
    "crm.schemas.custom.write",
    "crm.schemas.contacts.write",
    "crm.schemas.companies.write",
    # v2 phases
    "crm.objects.quotes.write",
    "crm.objects.line_items.write",
    "analytics.behavioral_events.send",
    # Marketing + automation
    "forms",
    "automation",
    "content",  # marketing email + landing pages
    # Lists for marketing campaign association
    "crm.lists.write",
}

# Scopes the v2 builder *requires* but the token may legitimately lack on
# older private apps. We surface these as actionable but do not hard-fail
# unless the corresponding phase is actually planned for this build.
OPTIONAL_SCOPES_BY_PHASE = {
    "marketing.campaigns.write": "marketing campaign phase",
    "crm.objects.leads.write": "Sales Workspace leads phase",
    "crm.objects.invoices.write": "invoices phase",
    "crm.schemas.deals.write": "calc property + property group phase",
    "crm.schemas.tickets.write": "demo_customer property on tickets",
}

# ---- Tiny color helpers ----

def log(msg: str) -> None:
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)
def ok(msg: str) -> None:    log(f"  ✓ {msg}")
def warn(msg: str) -> None:  log(f"  ⚠ {msg}")
def fail(msg: str) -> None:  log(f"  ✗ {msg}")


# ---- Manual-step reason hygiene ----
#
# `add_manual_step` reasons render in the prospect-facing demo doc. Raw API
# strings ("API returned 500", "v4 flows API rejected actions", "Forms API
# rejected", "INVALID_OPTION", etc.) make us look broken to the buyer.
# `_sanitize_reason` rewrites any raw-error reason into professional rationale
# the rep can defend in the room. The original string is preserved on the
# manual_step entry under `internal_reason` for debugging.

# Tokens that indicate a raw API error leaked into the reason field. Lowercase
# match — see `_sanitize_reason`. Sourced from SKILL.md Phase 3.
FORBIDDEN_REASON_TOKENS = (
    "api returned", "500", "rejected", "blocked", "validation",
    "invalid_", "401", "403", "429", "v4 flows", "forms api",
)

# Map manual-step item keywords to a polished public-facing reason. Order
# matters — "workflow" is checked before "email" so a manual step like
# "Add send_email action to '<workflow name>'" maps to the workflow phrase,
# not the email phrase.
_REASON_REPHRASE = (
    ("workflow", "Built manually for finer control over branching/timing"),
    ("quote",    "Built in UI for richer template handling"),
    ("invoice",  "Built in UI for richer template handling"),
    ("campaign", "Built in UI for finer control"),
    ("form",     "Configured by hand for advanced field validation"),
    ("email",    "Configured by hand for advanced field validation"),
)


def _sanitize_reason(raw_reason: str | None, item_label: str = "") -> str:
    """Return a public-safe rephrase if `raw_reason` contains any forbidden
    API-error token; otherwise return it unchanged. `item_label` lets us pick
    a domain-appropriate fallback (workflow → branching, form → validation, etc).

    The match is also raw-reason-aware: a reason mentioning "v4 flows" forces
    the workflow phrasing even when the item label is ambiguous (e.g. a gap
    step like "Add send_email action to '<workflow name>'").
    """
    raw = (raw_reason or "").strip()
    low = raw.lower()
    if not any(tok in low for tok in FORBIDDEN_REASON_TOKENS):
        return raw
    item_low = (item_label or "").lower()
    # Hint the workflow phrasing for any step whose RAW reason mentioned
    # workflow / v4 flows / branching, even when the item label says "email".
    if "v4 flows" in low or "workflow" in low or "workflow" in item_low:
        return _REASON_REPHRASE[0][1]  # workflow phrasing
    # Otherwise fall back to whichever marker first matches the item label.
    for marker, rephrase in _REASON_REPHRASE:
        if marker in item_low:
            return rephrase
    return "Built in UI for finer control"

# ---- HTTP client ----

class HubSpotClient:
    def __init__(self, token: str, portal: str, max_workers: int = 10):
        self.token = token
        self.portal = portal
        self._lock = threading.Lock()
        self._call_log: list[float] = []  # timestamps of recent calls

    def _throttle(self) -> None:
        """Ensure we stay under HubSpot rate limits."""
        with self._lock:
            now = time.time()
            self._call_log = [t for t in self._call_log if now - t < 10]
            if len(self._call_log) >= RATE_LIMIT_PER_10S:
                sleep = 10 - (now - self._call_log[0]) + 0.1
                time.sleep(max(sleep, 0))
            self._call_log.append(time.time())

    def request(self, method: str, path: str, body: Any = None, query: dict | None = None) -> tuple[int, dict]:
        self._throttle()
        url = "https://api.hubapi.com" + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                try:
                    return r.status, json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    return r.status, {"_raw": raw.decode("utf-8", "replace")}
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return e.code, {"_raw": raw.decode("utf-8", "replace")}
        except Exception as e:
            return 0, {"_error": str(e)}

    def is_ok(self, status: int) -> bool:
        return 200 <= status < 300

    def send_event_batch(self, inputs: list[dict]) -> tuple[int, dict]:
        """Send custom event occurrences in one batch request.

        HubSpot's latest custom event occurrence API uses
        `/events/2026-03/send/batch`; the legacy v3 batch endpoint is still
        available in older docs. Try latest first, then fall back to v3 if this
        portal has not enabled the newer route yet.
        """
        if len(inputs) > 500:
            return 400, {"_error": "event batch accepts at most 500 inputs"}
        status, body = self.request(
            "POST", "/events/2026-03/send/batch", {"inputs": inputs}
        )
        if status in (404, 405):
            status, body = self.request(
                "POST", "/events/v3/send/batch", {"inputs": inputs}
            )
        return status, body

    def form_submit(self, form_guid: str, body: dict) -> tuple[int, str]:
        """Unauthenticated form submission endpoint.

        Bug fix (2026-04-27): the v3 form-submission endpoint lives on
        `api.hsforms.com`, not `api.hubapi.com`. Hitting api.hubapi.com
        returns a 404 HTML page (not even a JSON error), which silently
        zeroes out form_submissions_count for every demo run.
        """
        self._throttle()
        url = f"https://api.hsforms.com/submissions/v3/integration/submit/{self.portal}/{form_guid}"
        headers = {"Content-Type": "application/json"}
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:
            return 0, str(e)


# ---- Builder ----

class Builder:
    def __init__(self, slug: str, work_dir: str | None = None, env_path: str | None = None):
        self.slug = slug
        self.work_dir = work_dir or f"/tmp/demo-prep-{slug}"
        os.makedirs(self.work_dir, exist_ok=True)
        os.makedirs(f"{self.work_dir}/screenshots", exist_ok=True)

        # Env
        env_path = env_path or os.path.expanduser("~/.claude/api-keys.env")
        env = {}
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k] = v
        self.env = env
        token = env.get("HUBSPOT_DEMOPREP_SANDBOX_TOKEN")
        portal = env.get("HUBSPOT_DEMOPREP_SANDBOX_PORTAL_ID", "51393541")
        if not token:
            raise SystemExit("HUBSPOT_DEMOPREP_SANDBOX_TOKEN missing in env")
        self.client = HubSpotClient(token, portal)
        self.portal = portal
        self.token = token

        # State
        self.plan = json.load(open(f"{self.work_dir}/build-plan.json"))
        self.research = json.load(open(f"{self.work_dir}/research.json"))
        self.manifest: dict[str, Any] = {
            "company": {}, "contacts": {}, "deals": {}, "tickets": {},
            "pipeline": {}, "custom_object": {}, "custom_events": {},
            "forms": {}, "marketing_email": {}, "landing_page": {},
            "workflows": {}, "workflow_urls": {}, "lead_scoring": {},
            "engagements_count": 0, "form_submissions_count": 0,
            "manual_steps": [], "errors": [],
            # v2 additions
            "leads": {},               # {hs_lead_name: lead_id}
            "quotes": {},              # {deal_name: quote_id}
            "line_items": {},          # {deal_id: [line_item_id, ...]}
            "invoices": {},            # {deal_name: invoice_id}
            "quote_template_id": None,
            "calc_property": {},       # {name, group}
            "campaign_id": None,
            "campaign_url": None,
            "campaigns": {},           # {campaign_name: {id, url, utm_campaign, role, source}}
            "campaign_attribution_showcase": {},
            # v0.4 reports/dashboard contract
            "sandbox_tier": None,
            "reports": {},
            "dashboards_v04": {},
            "reports_status": {},
            # phase_name -> {verified: bool, retried: bool, message: str}
            "verifications": {},
        }
        random.seed(42)

    # ---- Utility ----

    def save_manifest(self) -> None:
        with open(f"{self.work_dir}/manifest.json", "w") as f:
            json.dump(self.manifest, f, indent=2, default=str)

    def url(self, *parts: str) -> str:
        return f"https://app.hubspot.com/{'/'.join(parts)}"

    def ms_ago(self, days: int) -> int:
        return int((time.time() - days * 86400) * 1000)

    def add_manual_step(self, item: str, ui_url: str, instructions: str, reason: str) -> None:
        # Public `reason` is sanitized (no raw API errors leak to the prospect).
        # Original raw reason stays on `internal_reason` so the rep + post-mortem
        # tooling still see the actual API status / message.
        key = (item or "", ui_url or "", instructions or "")
        for existing in self.manifest.get("manual_steps", []):
            existing_key = (
                existing.get("item", ""),
                existing.get("ui_url", ""),
                existing.get("instructions", ""),
            )
            if existing_key == key:
                return
        public_reason = _sanitize_reason(reason, item_label=item)
        self.manifest["manual_steps"].append({
            "item": item, "ui_url": ui_url,
            "instructions": instructions,
            "reason": public_reason,
            "internal_reason": reason or "",
        })

    def add_error(self, where: str, status: int, body: Any) -> None:
        self.manifest["errors"].append({"where": where, "status": status, "body": str(body)[:500]})

    def preflight_scopes(self, *, strict: bool = True) -> dict:
        """Verify the Private App token has every scope this build needs.

        Hard-fails on missing required scopes when strict=True. Returns a
        dict describing the result so cleanup() and other callers can run
        in non-strict mode."""
        body = {"tokenKey": self.token}
        s, r = self.client.request(
            "POST", "/oauth/v2/private-apps/get/access-token-info", body
        )
        result = {"ok": False, "scopes": [], "missing_required": [],
                  "missing_optional": [], "app_id": None}
        if not self.client.is_ok(s):
            warn(f"preflight: introspection failed ({s}); skipping scope check")
            self.add_error("preflight.introspect", s, r)
            result["ok"] = True  # don't block the build on a probe failure
            return result

        scopes = set(r.get("scopes") or [])
        app_id = r.get("appId")
        result["scopes"] = sorted(scopes)
        result["app_id"] = app_id

        missing_required = sorted(REQUIRED_SCOPES - scopes)
        missing_optional = []
        for scope, phase_label in OPTIONAL_SCOPES_BY_PHASE.items():
            if scope not in scopes:
                missing_optional.append((scope, phase_label))
        result["missing_required"] = missing_required
        result["missing_optional"] = missing_optional

        reauth_url = (f"https://app.hubspot.com/private-apps/{self.portal}/{app_id}"
                      if app_id else f"https://app.hubspot.com/private-apps/{self.portal}")

        if missing_required and strict:
            log("✗ Pre-flight: missing required scopes")
            for sc in missing_required:
                fail(f"  {sc}")
            log("")
            log("Re-authorize the Private App and add the scopes above:")
            log(f"  {reauth_url}")
            log("Then refresh HUBSPOT_DEMOPREP_SANDBOX_TOKEN in ~/.claude/api-keys.env.")
            raise SystemExit(2)

        if missing_optional:
            log("⚠ Pre-flight: optional scopes missing — phases will degrade")
            for sc, label in missing_optional:
                warn(f"  {sc}  ({label})")
            log(f"  Add scopes here: {reauth_url}")

        if not missing_required:
            ok(f"pre-flight: {len(scopes)} scopes verified (app {app_id})")

        result["ok"] = not missing_required
        return result

    def probe_sandbox_tier(self) -> str:
        """Populate manifest["sandbox_tier"] before report planning.

        HubSpot does not expose a public "Marketing Hub tier" endpoint for
        report/dashboard feature gates. The demo sandbox ID is known and
        configured as Marketing Hub Enterprise; all other portals degrade to
        unknown unless the operator explicitly provides an override.
        """
        configured = (
            self.env.get("HUBSPOT_DEMOPREP_SANDBOX_TIER")
            or self.plan.get("sandbox_tier")
        )
        if configured:
            tier = str(configured).strip().lower()
            source = "configured"
        elif str(self.portal) == "51393541":
            tier = "marketing_enterprise"
            source = "known_sandbox_51393541"
        else:
            tier = "unknown"
            source = "unavailable_public_api"

        self.manifest["sandbox_tier"] = tier
        self.manifest["sandbox_tier_source"] = source
        if tier == "unknown" and self.plan.get("playwright_reports"):
            self.add_manual_step(
                "Reports & dashboards tier check",
                self.url("reports-dashboard", self.portal),
                "Confirm the portal's reporting tier before building advanced reports; degrade Sankey/journey/attribution tiles if Enterprise menus are unavailable.",
                "Tier endpoint unavailable publicly; manual confirmation keeps dashboard build accurate.",
            )
            warn("sandbox tier unknown; reports phase will degrade advanced charts")
        else:
            ok(f"sandbox tier: {tier} ({source})")
        return tier

    # ---- Phase 1: Properties ----

    def ensure_properties(self) -> None:
        log("Phase 1: Properties")
        # CRM core objects use the default {object}information groups.
        # Engagement objects (notes/tasks/calls/meetings/emails) use the
        # default-engagement group name HubSpot pre-creates.
        groups = {"contacts": "contactinformation", "companies": "companyinformation",
                  "deals": "dealinformation", "tickets": "ticketinformation",
                  "notes": "note", "tasks": "task", "calls": "call",
                  "meetings": "meeting", "emails": "email"}
        for obj, group in groups.items():
            body = {"name": "demo_customer", "label": "Demo Customer Slug",
                    "type": "string", "fieldType": "text", "groupName": group,
                    "description": "Tags demo data created by hubspot-demo-prep skill."}
            s, r = self.client.request("POST", f"/crm/v3/properties/{obj}", body)
            if s in (201, 409):
                ok(f"property demo_customer on {obj}")
            elif s == 400 and "groupName" in str(r):
                # Engagement group names vary by portal — retry without groupName.
                body.pop("groupName")
                s2, r2 = self.client.request("POST", f"/crm/v3/properties/{obj}", body)
                if s2 in (201, 409):
                    ok(f"property demo_customer on {obj} (default group)")
                else:
                    warn(f"property {obj}: {s2}")
                    self.add_error(f"property:{obj}", s2, r2)
            else:
                warn(f"property {obj}: {s}")
                self.add_error(f"property:{obj}", s, r)
        # Lead score
        body = {"name": "demo_lead_score", "label": "Demo Lead Score",
                "type": "number", "fieldType": "number", "groupName": "contactinformation",
                "description": "Lead score generated by hubspot-demo-prep skill"}
        s, _ = self.client.request("POST", "/crm/v3/properties/contacts", body)
        ok(f"demo_lead_score property: {s}")
        self._ensure_campaign_attribution_properties()

    def _ensure_crm_property(
        self,
        object_type: str,
        *,
        name: str,
        label: str,
        prop_type: str = "string",
        field_type: str = "text",
        group_name: str | None = None,
        description: str = "",
    ) -> bool:
        body = {
            "name": name,
            "label": label,
            "type": prop_type,
            "fieldType": field_type,
            "description": description,
        }
        if group_name:
            body["groupName"] = group_name
        s, r = self.client.request("POST", f"/crm/v3/properties/{object_type}", body)
        if s in (201, 409):
            ok(f"property {name} on {object_type}")
            return True
        if group_name and s == 400 and "groupName" in str(r):
            body.pop("groupName", None)
            s2, r2 = self.client.request("POST", f"/crm/v3/properties/{object_type}", body)
            if s2 in (201, 409):
                ok(f"property {name} on {object_type} (default group)")
                return True
            warn(f"property {object_type}.{name}: {s2}")
            self.add_error(f"property:{object_type}.{name}", s2, r2)
            return False
        warn(f"property {object_type}.{name}: {s}")
        self.add_error(f"property:{object_type}.{name}", s, r)
        return False

    def _ensure_campaign_attribution_properties(self) -> None:
        """Create safe custom fields for feature-showcase attribution stories.

        These avoid writing HubSpot's read-only analytics/source properties
        directly while still giving Jordan-style demos visible first-touch,
        last-touch, and influenced-revenue fields on records.
        """
        block = self.plan.get("campaign_attribution_showcase") or {}
        if not block:
            return
        log("Phase 1b: Campaign attribution showcase properties")
        for name, label in (
            ("first_touch_campaign", "First Touch Campaign"),
            ("last_touch_campaign", "Last Touch Campaign"),
            ("campaign_source_path", "Campaign Source Path"),
        ):
            self._ensure_crm_property(
                "contacts",
                name=name,
                label=label,
                group_name="contactinformation",
                description="Demo-prep attribution showcase field.",
            )
        for name, label, prop_type, field_type in (
            ("first_touch_campaign", "First Touch Campaign", "string", "text"),
            ("last_touch_campaign", "Last Touch Campaign", "string", "text"),
            ("campaign_source_path", "Campaign Source Path", "string", "text"),
            ("campaign_influenced_revenue", "Campaign Influenced Revenue", "number", "number"),
        ):
            self._ensure_crm_property(
                "deals",
                name=name,
                label=label,
                prop_type=prop_type,
                field_type=field_type,
                group_name="dealinformation",
                description="Demo-prep attribution showcase field.",
            )

    # ---- Phase 2: Company ----

    def create_company(self) -> None:
        log("Phase 2: Company")
        co = self.plan["company"]
        industry = co.get("industry", "OTHER").upper().replace(" ", "_").replace("-", "_")
        if industry not in VALID_INDUSTRIES:
            warn(f"industry {industry} not valid, falling back to OTHER")
            industry = "OTHER"
        body = {"properties": {
            "name": co["name"], "domain": co["domain"],
            "industry": industry, "description": co.get("description", ""),
            "demo_customer": self.slug,
        }}
        s, r = self.client.request("POST", "/crm/v3/objects/companies", body)
        if not self.client.is_ok(s):
            self.add_error("company.create", s, r)
            raise SystemExit(f"Company create failed: {s} {r}")
        cid = r["id"]
        self.manifest["company"] = {
            "id": cid, "name": co["name"],
            "url": self.url("contacts", self.portal, "record/0-2", cid),
        }
        ok(f"company {co['name']} → {cid}")

    # ---- Phase 3: Contacts ----

    def create_contacts(self) -> None:
        log("Phase 3: Contacts")
        company_id = self.manifest["company"]["id"]
        # HubSpot rejects .test TLD; rewrite to RFC-2606 reserved example.com prefix
        # so the demo never collides with a real registered domain.
        # We also persist `original -> rewritten` in self._email_rewrite_map
        # because activity_content.per_contact_engagements is keyed by the
        # ORIGINAL email (orchestrator-supplied) but the manifest is keyed by
        # the REWRITTEN one. The engagement lookup checks both.
        if not hasattr(self, "_email_rewrite_map"):
            self._email_rewrite_map: dict[str, str] = {}
        for c in self.plan["contacts"]:
            original_email = c["email"]
            # .test is reserved per RFC 2606 but HubSpot rejects it.
            # Use the slug-prefixed example.com to avoid colliding with a real domain.
            if c["email"].endswith(".test"):
                c["email"] = c["email"].replace(
                    "@", f"@demo-{self.slug}.").replace(".test", ".example.com")
                # Idempotent: if email already had @demo-{slug}, the second
                # replace turns the artifact into a single demo prefix.
                while c["email"].count(f"@demo-{self.slug}.") > 1:
                    c["email"] = c["email"].replace(
                        f"@demo-{self.slug}.@demo-{self.slug}.", f"@demo-{self.slug}."
                    )
            if original_email != c["email"]:
                self._email_rewrite_map[original_email] = c["email"]

        # Per-contact create (avoids batch 207 partial-failure ambiguity)
        for c in self.plan["contacts"]:
            body = {"properties": {**c, "demo_customer": self.slug}}
            s, r = self.client.request("POST", "/crm/v3/objects/contacts", body)
            if self.client.is_ok(s):
                self.manifest["contacts"][c["email"]] = r["id"]
                ok(f"contact {c['email']} → {r['id']}")
            elif s == 409:
                # Duplicate — find by email and reuse
                search_body = {"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": c["email"]}]}]}
                s2, r2 = self.client.request("POST", "/crm/v3/objects/contacts/search", search_body)
                if self.client.is_ok(s2) and r2.get("results"):
                    cid = r2["results"][0]["id"]
                    self.manifest["contacts"][c["email"]] = cid
                    ok(f"contact {c['email']} (existing) → {cid}")
            else:
                warn(f"contact {c['email']}: {s} {str(r)[:200]}")
                self.add_error(f"contact.create:{c['email']}", s, r)

        # Associate to company — DEDUPED (parallel, but throttled by client).
        #
        # Fix D (2026-04-26): the v3 PUT association endpoint is *not* fully
        # idempotent across re-runs in HubSpot's UI. When `_run_with_verify`
        # retries `create_contacts` (because verify briefly returned False), or
        # when the orchestrator re-runs `python3 builder.py <slug>` to repair a
        # partial build (e.g. 1800LAW1010 was run 4 times), every execution of
        # the loop below re-PUT the association — causing the contact record
        # in HubSpot to show 4 separate "associated company" rows for what
        # should be a single Primary association.
        #
        # Defense: GET the contact's existing company associations first; only
        # PUT if the target `company_id` is NOT already in the result set.
        # The same pattern applies anywhere we associate a contact to a
        # company (currently only this site — see grep of associations/companies).
        ok_count = 0
        skip_count = 0
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {}
            for cid in self.manifest["contacts"].values():
                futures[ex.submit(self._associate_contact_to_company_idempotent,
                                  cid, company_id)] = cid
            for fut in as_completed(futures):
                result = fut.result()
                if result == "ok":
                    ok_count += 1
                elif result == "skip":
                    skip_count += 1
        ok(f"contact-company associations: {ok_count} created, {skip_count} already existed "
           f"(total contacts: {len(self.manifest['contacts'])})")

    def _associate_contact_to_company_idempotent(
        self, contact_id: str, company_id: str
    ) -> str:
        """PUT contact→company association only when it doesn't already exist.

        Returns one of:
          - "skip"  — association already present; nothing PUT
          - "ok"    — PUT succeeded
          - "fail"  — PUT failed or pre-check raised

        See Fix D commentary in `create_contacts` for why this matters.
        """
        try:
            s, r = self.client.request(
                "GET", f"/crm/v3/objects/contacts/{contact_id}/associations/companies"
            )
            if self.client.is_ok(s):
                results = r.get("results", []) if isinstance(r, dict) else []
                for assoc in results:
                    # The v3 association payload returns `id` (string) for the
                    # associated record; older shapes use `toObjectId`. Check both.
                    target_id = str(assoc.get("id") or assoc.get("toObjectId") or "")
                    if target_id == str(company_id):
                        return "skip"
            # Either GET failed (we PUT defensively) or association is missing.
            ps, _ = self.client.request(
                "PUT",
                f"/crm/v3/objects/contacts/{contact_id}/associations/companies/{company_id}/{ASSOC['contact_to_company']}",
            )
            return "ok" if self.client.is_ok(ps) else "fail"
        except Exception:  # noqa: BLE001 — never crash the parallel association loop
            return "fail"

    # ---- Phase 4: Pipeline + deals + tickets ----

    def create_pipeline_and_deals(self) -> None:
        log("Phase 4: Pipeline + deals")
        pipeline_plan = self.plan["deal_pipeline"]

        # Defensive coercion: plan stages should be `[{label, probability}, ...]`
        # but older or hand-written plans sometimes pass bare strings. Coerce so
        # the builder doesn't crash with `TypeError: string indices must be
        # integers` when indexing s["label"] below. The schema doc at
        # docs/punch-lists/.../plan-schema.md is authoritative — see fix #4.
        raw_stages = pipeline_plan.get("stages") or []
        coerced_stages = []
        for i, st in enumerate(raw_stages):
            if isinstance(st, str):
                warn(f"Phase 4: pipeline stage {i} is a bare string ({st!r}); "
                     f"coercing to {{label: ..., probability: 0.5}}. Plan should "
                     f"emit objects per plan-schema.md.")
                coerced_stages.append({"label": st, "probability": 0.5})
            else:
                coerced_stages.append(st)
        pipeline_plan["stages"] = coerced_stages

        # Check for existing pipeline by label
        s, r = self.client.request("GET", "/crm/v3/pipelines/deals")
        existing_id = None
        if self.client.is_ok(s):
            for p in r.get("results", []):
                if p.get("label") == pipeline_plan["name"]:
                    existing_id = p["id"]
                    break
        if existing_id:
            pipeline_id = existing_id
            ok(f"reusing pipeline ({pipeline_id})")
        else:
            body = {"label": pipeline_plan["name"], "displayOrder": 99,
                    "stages": [{"label": s["label"], "displayOrder": i,
                                "metadata": {"probability": str(s["probability"])}}
                               for i, s in enumerate(pipeline_plan["stages"])]}
            s, r = self.client.request("POST", "/crm/v3/pipelines/deals", body)
            if not self.client.is_ok(s):
                self.add_error("pipeline.create", s, r)
                return
            pipeline_id = r["id"]
            ok(f"pipeline {pipeline_plan['name']} → {pipeline_id}")

        # Fetch the pipeline so we have authoritative stage labels (stage map +
        # the playwright dashboard's "open quotes" filter both consume this).
        s, r = self.client.request("GET", f"/crm/v3/pipelines/deals/{pipeline_id}")
        stages_list = [{"label": st["label"], "id": st["id"]} for st in r.get("stages", [])]
        stage_map = {st["label"]: st["id"] for st in r.get("stages", [])}

        # Pipeline board URL.
        #
        # v0.3.0 fix tried `?pipeline={id}` on the modern object-records URL.
        # v0.3.1 walkthrough caught that this STILL doesn't auto-switch the
        # board view — HubSpot's UI honors the user's last-viewed pipeline
        # cookie and ignores the bare `?pipeline=` query string. The fix:
        # use HubSpot's internal `pipelineId` query name (matches what the
        # board's pipeline-picker writes when a user switches manually).
        # Belt-and-suspenders: include both `?pipeline=` AND `?pipelineId=`
        # so we hit whichever HubSpot's URL parser is currently honoring.
        board_url = (f"https://app.hubspot.com/contacts/{self.portal}"
                     f"/objects/0-3/views/all/board"
                     f"?pipeline={pipeline_id}&pipelineId={pipeline_id}")
        self.manifest["pipeline"] = {
            "id": pipeline_id, "name": pipeline_plan["name"],
            "url": board_url,
            "stages": stages_list,  # [{label, id}] — read by playwright_phases_extras saved-views builder
        }

        # Deals (sequential to avoid race on associations)
        company_id = self.manifest["company"]["id"]
        contact_ids = list(self.manifest["contacts"].values())
        for i, d in enumerate(self.plan["deals"]):
            stage_id = stage_map.get(d["stage"])
            if not stage_id:
                # Loud warning + actionable manual step. If `stage_map` is
                # missing the planned stage label, the deal silently never
                # gets created — which is precisely what made 1800LAW1010
                # appear to have an "empty pipeline" on review even though
                # the verifier passed (Fix C).
                warn(f"deal {d['name']}: planned stage {d['stage']!r} not found "
                     f"in pipeline {pipeline_plan['name']!r}; available stages: "
                     f"{list(stage_map.keys())}")
                self.add_error(
                    f"deal.create:{d['name']}",
                    0,
                    f"unknown stage {d['stage']!r}; pipeline only offers "
                    f"{list(stage_map.keys())}",
                )
                continue
            body = {"properties": {
                "dealname": d["name"], "amount": str(d.get("amount", 5000)),
                "pipeline": pipeline_id, "dealstage": stage_id,
                "closedate": d.get("closedate", ""),
                "demo_customer": self.slug,
            }}
            s, r = self.client.request("POST", "/crm/v3/objects/deals", body)
            if not self.client.is_ok(s):
                warn(f"deal {d['name']}: {s}")
                self.add_error(f"deal.create:{d['name']}", s, r)
                continue
            did = r["id"]
            self.manifest["deals"][d["name"]] = did
            self.client.request("PUT", f"/crm/v3/objects/deals/{did}/associations/companies/{company_id}/{ASSOC['deal_to_company']}")
            if contact_ids:
                self.client.request("PUT", f"/crm/v3/objects/deals/{did}/associations/contacts/{contact_ids[i % len(contact_ids)]}/{ASSOC['deal_to_contact']}")
            ok(f"deal {d['name']} → {did}")

        # Post-build verification: GET each deal and confirm `pipeline` matches
        # `pipeline_id`. If any deal slipped onto the default pipeline (rare,
        # but caught the 1800LAW1010 walkthrough), PATCH it to the correct
        # pipeline + first stage so the board view isn't empty. Fix C.
        mismatches = []
        for deal_name, did in list(self.manifest["deals"].items()):
            sg, rg = self.client.request(
                "GET", f"/crm/v3/objects/deals/{did}",
                query={"properties": "pipeline,dealstage"},
            )
            if not self.client.is_ok(sg):
                continue
            actual_pipeline = (rg.get("properties") or {}).get("pipeline")
            if actual_pipeline and str(actual_pipeline) != str(pipeline_id):
                mismatches.append((deal_name, did, actual_pipeline))
        if mismatches:
            # First stage of the custom pipeline as the safe landing slot.
            first_stage = stages_list[0]["id"] if stages_list else None
            for deal_name, did, wrong_pipeline in mismatches:
                warn(f"deal {deal_name} landed on pipeline {wrong_pipeline} "
                     f"(expected {pipeline_id}); patching to {pipeline_id}")
                patch_body = {"properties": {"pipeline": pipeline_id}}
                if first_stage:
                    patch_body["properties"]["dealstage"] = first_stage
                ps, pr = self.client.request(
                    "PATCH", f"/crm/v3/objects/deals/{did}", patch_body,
                )
                if not self.client.is_ok(ps):
                    self.add_error(f"deal.repipeline:{deal_name}", ps, pr)
            ok(f"repaired {len(mismatches)} deals onto pipeline {pipeline_id}")

    def apply_campaign_attribution_showcase(self) -> None:
        """Patch attribution-showcase fields onto sample contacts and deals.

        The real HubSpot attribution reports are still UI/report-builder work,
        but this gives the content/demo presenter concrete records to open:
        contact first touch, contact last touch, source path, and associated
        deal influenced revenue all line up with the story.
        """
        block = self.plan.get("campaign_attribution_showcase") or {}
        if not block:
            return
        log("Phase 4c: Campaign attribution showcase data")

        contact_paths = block.get("contact_paths") or []
        contacts_patched = 0
        deals_patched = 0
        missing: list[str] = []
        email_rewrite = getattr(self, "_email_rewrite_map", {}) or {}

        for path in contact_paths:
            if not isinstance(path, dict):
                continue
            email = path.get("contact_email") or path.get("email")
            rewritten_email = email_rewrite.get(email, email)
            contact_id = (
                self.manifest.get("contacts", {}).get(rewritten_email)
                or self.manifest.get("contacts", {}).get(email)
            )
            first = path.get("first_touch_campaign") or ""
            last = path.get("last_touch_campaign") or ""
            source_path_raw = path.get("source_path") or []
            source_path = (
                " → ".join(str(x) for x in source_path_raw)
                if isinstance(source_path_raw, list)
                else str(source_path_raw or "")
            )

            if contact_id:
                props = {
                    "first_touch_campaign": first,
                    "last_touch_campaign": last,
                    "campaign_source_path": source_path,
                }
                props = {k: v for k, v in props.items() if v not in (None, "")}
                if props:
                    s, r = self.client.request(
                        "PATCH",
                        f"/crm/v3/objects/contacts/{contact_id}",
                        {"properties": props},
                    )
                    if self.client.is_ok(s):
                        contacts_patched += 1
                    else:
                        self.add_error(f"campaign_attribution.contact:{email}", s, r)
            elif email:
                missing.append(f"contact:{email}")

            deal_name = path.get("deal_name")
            deal_id = self.manifest.get("deals", {}).get(deal_name)
            if deal_id:
                revenue = path.get("revenue")
                if revenue is None:
                    for d in self.plan.get("deals") or []:
                        if d.get("name") == deal_name:
                            revenue = d.get("amount")
                            break
                props = {
                    "first_touch_campaign": first,
                    "last_touch_campaign": last,
                    "campaign_source_path": source_path,
                }
                if revenue not in (None, ""):
                    props["campaign_influenced_revenue"] = str(revenue)
                props = {k: v for k, v in props.items() if v not in (None, "")}
                if props:
                    s, r = self.client.request(
                        "PATCH",
                        f"/crm/v3/objects/deals/{deal_id}",
                        {"properties": props},
                    )
                    if self.client.is_ok(s):
                        deals_patched += 1
                    else:
                        self.add_error(f"campaign_attribution.deal:{deal_name}", s, r)
            elif deal_name:
                missing.append(f"deal:{deal_name}")

        rollup = block.get("deal_campaign_rollup") or {}
        if isinstance(rollup, dict) and rollup.get("manual_step_when_ui_required"):
            workflow_name = rollup.get("workflow_name") or "Copy campaign influence to associated deals"
            self.add_manual_step(
                workflow_name,
                self.url("workflows", self.portal, "view/all-workflows"),
                (
                    "Create or review the workflow that copies first-touch, last-touch, "
                    "and campaign-influenced revenue fields from contacts to associated deals."
                ),
                "Configured in UI so the association logic matches the showcase story.",
            )

        self.manifest["campaign_attribution_showcase"] = {
            "campaign_count": len(block.get("campaigns") or []),
            "contact_paths_planned": len(contact_paths),
            "contacts_patched": contacts_patched,
            "deals_patched": deals_patched,
            "missing": missing[:20],
            "workflow_manual_step": bool(
                isinstance(rollup, dict) and rollup.get("manual_step_when_ui_required")
            ),
        }
        ok(
            "campaign attribution showcase: "
            f"{contacts_patched} contact(s), {deals_patched} deal(s) patched"
        )

    def verify_campaign_attribution_showcase(self) -> tuple[bool, str]:
        block = self.plan.get("campaign_attribution_showcase") or {}
        if not block:
            return True, "not requested"
        info = self.manifest.get("campaign_attribution_showcase") or {}
        planned = int(info.get("contact_paths_planned") or len(block.get("contact_paths") or []))
        if planned == 0:
            return True, "campaign attribution story recorded; no contact paths requested"
        contacts_patched = int(info.get("contacts_patched") or 0)
        deals_patched = int(info.get("deals_patched") or 0)
        if contacts_patched > 0 and deals_patched > 0:
            return True, f"patched {contacts_patched} contact(s), {deals_patched} deal(s)"
        missing = ", ".join(info.get("missing") or [])
        return False, f"expected contact/deal attribution patches; missing={missing or 'unknown'}"

    def create_tickets(self) -> None:
        if not self.plan.get("tickets"):
            return
        log("Phase 4b: Tickets")
        company_id = self.manifest["company"]["id"]
        s, r = self.client.request("GET", "/crm/v3/pipelines/tickets")
        if not self.client.is_ok(s) or not r.get("results"):
            warn("ticket pipeline lookup failed")
            return
        tp = r["results"][0]
        tp_id = tp["id"]
        tp_first_stage = tp["stages"][0]["id"] if tp.get("stages") else ""
        for t in self.plan["tickets"]:
            body = {"properties": {
                "subject": t["subject"], "content": t.get("content", ""),
                "hs_pipeline": tp_id, "hs_pipeline_stage": tp_first_stage,
                "hs_ticket_priority": t.get("priority", "MEDIUM"),
                "demo_customer": self.slug,
            }}
            s, r = self.client.request("POST", "/crm/v3/objects/tickets", body)
            if self.client.is_ok(s):
                tid = r["id"]
                self.manifest["tickets"][t["subject"]] = tid
                self.client.request("PUT", f"/crm/v3/objects/tickets/{tid}/associations/companies/{company_id}/{ASSOC['ticket_to_company']}")
                ok(f"ticket {t['subject']} → {tid}")
            else:
                warn(f"ticket: {s}")
                self.add_error(f"ticket.create:{t['subject']}", s, r)

    # ---- Phase 5: Engagements (parallel) ----

    def create_engagements(self) -> None:
        log("Phase 5: Engagements (parallel)")
        days_back = self.plan.get("activity", {}).get("backdate_days", 120)
        level = self.plan.get("activity", {}).get("level", "full")
        counts = {
            "light": (1, 1, 1, 0, 2),
            "medium": (3, 2, 2, 1, 4),
            "full": (5, 3, 3, 2, 8),
        }.get(level, (3, 2, 2, 1, 4))
        n_notes, n_tasks, n_calls, n_meetings, n_emails = counts

        # Pools: pull from plan["activity_content"]; fall back to industry-NEUTRAL
        # defaults from plan-schema.md. Notes are strings; tasks are strings;
        # calls/meetings/emails are objects ({title|subject, body}).
        ac = self.plan.get("activity_content", {}) or {}
        notes_pool = ac.get("notes_pool") or ac.get("notes") or [
            "Touchpoint with prospect.",
            "Discovery call notes.",
            "Follow-up email summary.",
        ]
        tasks_pool = ac.get("tasks_pool") or [
            "Follow up on pricing", "Send case studies",
            "Schedule technical deep-dive", "Review contract", "Draft proposal",
        ]
        calls_pool = ac.get("calls_pool") or [
            {"title": "Discovery call", "body": "Discussed needs."},
            {"title": "Pricing discussion", "body": "Walked through pricing."},
        ]
        meetings_pool = ac.get("meetings_pool") or [
            {"title": "Demo session", "body": "Walked through capabilities."},
        ]
        emails_pool = ac.get("emails_pool") or [
            {"subject": "Re: Following up", "body": "Following up on our conversation."},
        ]

        # Per-contact engagements (preferred path). Keyed by email or contact id.
        per_contact_map = ac.get("per_contact_engagements") or {}

        # Pre-generate engagement payloads. Every engagement is tagged
        # demo_customer=<slug> so cleanup's search-by-property loop finds them.
        tag = {"demo_customer": self.slug}
        payloads: list[tuple[str, dict]] = []

        def _pool_obj(pool: list, key_title: str) -> dict:
            """Pull one entry from a pool of {title|subject, body} objects.
            Tolerates string entries by promoting them to {key_title: str, body: ''}.
            """
            choice = random.choice(pool)
            if isinstance(choice, str):
                return {key_title: choice, "body": ""}
            return choice

        def _build_explicit_payload(eng: dict, cid: str, ts_default: int) -> tuple[str, dict] | None:
            """Build a single payload from a per-contact engagement entry.
            eng schema: {type, body, optional title|subject, optional duration_ms,
                         optional ts_offset_days}.
            """
            etype = (eng.get("type") or "").lower()
            offset = eng.get("ts_offset_days")
            ts = self.ms_ago(int(offset)) if offset is not None else ts_default
            body_text = eng.get("body", "")
            if etype == "note":
                return ("/crm/v3/objects/notes", {
                    "properties": {"hs_note_body": body_text, "hs_timestamp": ts, **tag},
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["note_to_contact"]}]}],
                })
            if etype == "task":
                return ("/crm/v3/objects/tasks", {
                    "properties": {
                        "hs_task_subject": eng.get("title") or eng.get("subject") or body_text[:80] or "Task",
                        "hs_task_body": body_text,
                        "hs_task_status": "COMPLETED",
                        "hs_task_priority": "MEDIUM",
                        "hs_timestamp": ts, **tag,
                    },
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["task_to_contact"]}]}],
                })
            if etype == "call":
                return ("/crm/v3/objects/calls", {
                    "properties": {
                        "hs_call_title": eng.get("title") or "Call",
                        "hs_call_body": body_text,
                        "hs_call_duration": int(eng.get("duration_ms") or random.randint(600000, 1800000)),
                        "hs_call_direction": "OUTBOUND",
                        "hs_call_status": "COMPLETED",
                        "hs_timestamp": ts, **tag,
                    },
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["call_to_contact"]}]}],
                })
            if etype == "meeting":
                duration = int(eng.get("duration_ms") or 1800000)
                return ("/crm/v3/objects/meetings", {
                    "properties": {
                        "hs_meeting_title": eng.get("title") or "Meeting",
                        "hs_meeting_body": body_text,
                        "hs_meeting_start_time": ts,
                        "hs_meeting_end_time": ts + duration,
                        "hs_meeting_outcome": "COMPLETED",
                        "hs_timestamp": ts, **tag,
                    },
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["meeting_to_contact"]}]}],
                })
            if etype == "email":
                return ("/crm/v3/objects/emails", {
                    "properties": {
                        "hs_email_subject": eng.get("subject") or eng.get("title") or "Email",
                        "hs_email_text": body_text,
                        "hs_email_direction": eng.get("direction")
                            or random.choice(["INCOMING_EMAIL", "EMAIL"]),
                        "hs_email_status": "SENT",
                        "hs_timestamp": ts, **tag,
                    },
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["email_to_contact"]}]}],
                })
            return None

        # Reverse map: rewritten -> original. Used so per_contact_engagements
        # keys (which Phase 2 wrote against the original email) still match
        # after create_contacts rewrote .test addresses.
        rewrite_reverse = {v: k for k, v in getattr(self, "_email_rewrite_map", {}).items()}

        for email, cid in self.manifest["contacts"].items():
            # Per-contact override path: try keyed by current email, original
            # (pre-rewrite) email, or by contact id as a string. Belt-and-
            # suspenders so both orchestrator-supplied keying schemes work.
            original_email = rewrite_reverse.get(email)
            entries = (
                per_contact_map.get(email)
                or (per_contact_map.get(original_email) if original_email else None)
                or per_contact_map.get(str(cid))
            )
            if entries:
                ts_default = self.ms_ago(random.randint(1, days_back))
                for eng in entries:
                    built = _build_explicit_payload(eng, cid, ts_default)
                    if built:
                        payloads.append(built)
                continue

            # Pool-based path
            for _ in range(n_notes):
                ts = self.ms_ago(random.randint(1, days_back))
                payloads.append(("/crm/v3/objects/notes", {
                    "properties": {"hs_note_body": random.choice(notes_pool), "hs_timestamp": ts, **tag},
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["note_to_contact"]}]}],
                }))
            for _ in range(n_tasks):
                ts = self.ms_ago(random.randint(1, days_back))
                payloads.append(("/crm/v3/objects/tasks", {
                    "properties": {"hs_task_subject": random.choice(tasks_pool),
                                   "hs_task_status": "COMPLETED", "hs_task_priority": "MEDIUM",
                                   "hs_timestamp": ts, **tag},
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["task_to_contact"]}]}],
                }))
            for _ in range(n_calls):
                ts = self.ms_ago(random.randint(1, days_back))
                call = _pool_obj(calls_pool, "title")
                payloads.append(("/crm/v3/objects/calls", {
                    "properties": {"hs_call_title": call.get("title", "Call"),
                                   "hs_call_body": call.get("body", ""),
                                   "hs_call_duration": random.randint(600000, 1800000),
                                   "hs_call_direction": "OUTBOUND", "hs_call_status": "COMPLETED",
                                   "hs_timestamp": ts, **tag},
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["call_to_contact"]}]}],
                }))
            for _ in range(n_meetings):
                start = self.ms_ago(random.randint(1, days_back))
                meeting = _pool_obj(meetings_pool, "title")
                payloads.append(("/crm/v3/objects/meetings", {
                    "properties": {"hs_meeting_title": meeting.get("title", "Meeting"),
                                   "hs_meeting_body": meeting.get("body", ""),
                                   "hs_meeting_start_time": start,
                                   "hs_meeting_end_time": start + 1800000,
                                   "hs_meeting_outcome": "COMPLETED", "hs_timestamp": start, **tag},
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["meeting_to_contact"]}]}],
                }))
            for _ in range(n_emails):
                ts = self.ms_ago(random.randint(1, days_back))
                direction = random.choice(["INCOMING_EMAIL", "EMAIL"])
                em = _pool_obj(emails_pool, "subject")
                payloads.append(("/crm/v3/objects/emails", {
                    "properties": {"hs_email_subject": em.get("subject") or em.get("title") or "Email",
                                   "hs_email_text": em.get("body", ""),
                                   "hs_email_direction": direction,
                                   "hs_email_status": "SENT", "hs_timestamp": ts, **tag},
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["email_to_contact"]}]}],
                }))

        # Parallel POSTs
        ok_count = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(self.client.request, "POST", path, body) for path, body in payloads]
            for fut in as_completed(futures):
                s, _ = fut.result()
                if self.client.is_ok(s):
                    ok_count += 1
        self.manifest["engagements_count"] = ok_count
        ok(f"engagements: {ok_count}/{len(payloads)}")

    # ---- Phase 6: Custom object ----

    def create_custom_object(self) -> None:
        if not self.plan.get("custom_object"):
            return
        log("Phase 6: Custom object")
        co = self.plan["custom_object"]
        s, r = self.client.request("GET", "/crm/v3/schemas")
        oid = None
        if self.client.is_ok(s):
            for sch in r.get("results", []):
                if sch.get("name") == co["name"]:
                    oid = sch["objectTypeId"]
                    break
        if not oid:
            secondary_display = list(co.get("secondary_display", []))[:2]
            if len(co.get("secondary_display", []) or []) > 2:
                warn(
                    f"custom object {co['name']}: HubSpot allows at most 2 "
                    "secondary display properties; truncating extras"
                )
            body = {"name": co["name"], "labels": co["labels"],
                    "primaryDisplayProperty": co["primary_display"],
                    "secondaryDisplayProperties": secondary_display,
                    "requiredProperties": co.get("required", [co["primary_display"]]),
                    "searchableProperties": co.get("searchable", [co["primary_display"]]),
                    "properties": co["properties"],
                    "associatedObjects": co.get("associated_objects", ["CONTACT"])}
            s, r = self.client.request("POST", "/crm/v3/schemas", body)
            if self.client.is_ok(s):
                oid = r["objectTypeId"]
                ok(f"custom object schema {co['name']} → {oid}")
            else:
                warn(f"custom object schema: {s}")
                self.add_error("custom_object.schema", s, r)
                return
        else:
            ok(f"reusing custom object {co['name']} ({oid})")

        # NOTE: We deliberately skip tagging custom-object records with demo_customer.
        # Custom-object schemas don't reliably propagate new properties fast enough,
        # and HubSpot rejects records that reference non-existent properties. Cleanup
        # finds these via hs_object_source_label="INTEGRATION" + objectTypeId filter.

        # Records (parallel) — no demo_customer tag
        records = co.get("records", [])
        if records:
            created_ids = []
            with ThreadPoolExecutor(max_workers=4) as ex:
                futures = []
                for rec in records:
                    body = {"properties": rec}
                    futures.append(ex.submit(self.client.request, "POST", f"/crm/v3/objects/{oid}", body))
                for f in as_completed(futures):
                    s, r = f.result()
                    if self.client.is_ok(s):
                        created_ids.append(r.get("id"))
            ok(f"custom records: {len(created_ids)}/{len(records)}")
            # Associate each record to the company (so cleanup can find them via association)
            company_id = self.manifest["company"].get("id")
            if company_id and created_ids:
                # Custom-object → company association: use generic associations endpoint
                for rid in created_ids:
                    # Try common association type IDs; sandbox may need specific ones
                    self.client.request(
                        "PUT",
                        f"/crm/v3/objects/{oid}/{rid}/associations/companies/{company_id}/1",
                    )
        self.manifest["custom_object"] = {
            "name": co["name"], "object_type_id": oid,
            "url": self.url("contacts", self.portal, "objects", oid),
        }

    # ---- Phase 7: Custom events ----

    def create_custom_events(self) -> None:
        """Phase 7: Custom events.

        v0.4 (2026-04-28): Dispatches to funnel-ordered firing when
        plan["custom_event_flows"] is present (renders meaningful Sankey/
        funnel reports). Falls back to v0.3.0 random-fire when only the
        flat plan["custom_events"] list is present.
        """
        has_flows = bool(self.plan.get("custom_event_flows"))
        has_legacy = bool(self.plan.get("custom_events"))
        if not has_flows and not has_legacy:
            return
        log("Phase 7: Custom events")

        if has_flows:
            self._create_custom_event_flows()
        else:
            self._create_custom_events_legacy()

    def _define_event_schema(self, evt: dict) -> str | None:
        """Create or fetch a custom event definition.

        Returns the fullyQualifiedName needed for /events/v3/send, or None on
        failure. Idempotent — handles the 409 case by GETing the existing
        definition.
        """
        body = {
            "label": evt.get("label", evt["name"]),
            "name": evt["name"],
            "description": evt.get("description", ""),
            "primaryObject": evt.get("primary_object", "CONTACT"),
            "propertyDefinitions": [
                {"name": p["name"], "label": p["label"], "type": p["type"]}
                for p in evt.get("properties", [])
            ],
        }
        s, r = self.client.request("POST", "/events/v3/event-definitions", body)
        if self.client.is_ok(s):
            full_name = r.get("fullyQualifiedName") or r.get("name", evt["name"])
            self.manifest["custom_events"][evt["name"]] = full_name
            ok(f"event def {evt['name']} → {full_name}")
            return full_name
        if s == 409:
            s2, r2 = self.client.request(
                "GET", f"/events/v3/event-definitions/{evt['name']}"
            )
            if self.client.is_ok(s2):
                full_name = r2.get("fullyQualifiedName") or evt["name"]
                self.manifest["custom_events"][evt["name"]] = full_name
                ok(f"event def {evt['name']} (existing)")
                return full_name
        warn(f"event def {evt['name']}: {s}")
        self.add_error(f"event.def:{evt['name']}", s, r)
        return None

    def _send_event_occurrences(self, sends: list[dict], label: str) -> int:
        """Send custom event occurrences, batching where possible.

        The batch endpoint accepts up to 500 occurrences. If a batch fails, fall
        back to single sends for that chunk so an API-version mismatch degrades
        to the known v0.3 behavior instead of dropping the whole flow.
        """
        if not sends:
            return 0
        sent = 0
        for i in range(0, len(sends), 500):
            chunk = sends[i:i + 500]
            status, body = self.client.send_event_batch(chunk)
            if self.client.is_ok(status):
                sent += len(chunk)
                continue

            warn(f"{label}: batch send failed ({status}); falling back to singles")
            self.add_error(f"event.batch:{label}", status, body)
            with ThreadPoolExecutor(max_workers=4) as ex:
                futures = [
                    ex.submit(self.client.request, "POST", "/events/v3/send", one)
                    for one in chunk
                ]
                sent += sum(
                    1 for fut in as_completed(futures)
                    if self.client.is_ok(fut.result()[0])
                )
        return sent

    def _create_custom_events_legacy(self) -> None:
        """v0.3.0 random-fire behavior preserved for plans without flows."""
        days_back = self.plan.get("activity", {}).get("backdate_days", 120)
        for evt in self.plan["custom_events"]:
            self._define_event_schema(evt)

        emails = list(self.manifest["contacts"].keys())[:5]
        sends: list[dict] = []
        for email in emails:
            for evt in self.plan["custom_events"]:
                full_name = self.manifest["custom_events"].get(evt["name"])
                if not full_name:
                    continue
                for _ in range(3):
                    days_ago = random.randint(1, days_back)
                    occurred = (datetime.datetime.utcnow() - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    props = {p["name"]: p.get("demo_value", "sample") for p in evt.get("properties", [])}
                    sends.append({"eventName": full_name, "email": email, "properties": props, "occurredAt": occurred})
        fires = self._send_event_occurrences(sends, "legacy")
        # Persist for time_estimates: lets the post-run estimator weigh in fires
        # even though there's no GET endpoint to recover this count later.
        self.manifest["custom_events_fired_count"] = (
            int(self.manifest.get("custom_events_fired_count") or 0) + fires
        )
        ok(f"event fires (legacy): {fires}/{len(sends)}")

    def _create_custom_event_flows(self) -> None:
        """v0.4: funnel-ordered event firing with realistic drop-off.

        Each flow defines events in `step` order; firing_strategy specifies
        how many contacts to walk through and what fraction survives each
        step. The resulting per-step survivor counts produce a Sankey/funnel
        with visible drop-off rather than a single straight line.

        HubSpot reality: there is no public API to query event completion
        counts after firing, so post-fire validation is limited to GETing
        each event definition (confirms schema exists). The 204 response
        from /events/v3/send is the strongest write-side guarantee available.
        """
        flows = self.plan["custom_event_flows"]
        all_contacts = list(self.manifest["contacts"].keys())
        if not all_contacts:
            warn("custom_event_flows: no contacts in manifest, skipping fires")
            return

        self.manifest.setdefault("custom_event_flows", {})
        grand_total_fires = 0

        for flow in flows:
            flow_name = flow.get("name", "unnamed_flow")
            events = sorted(flow.get("events", []), key=lambda e: e.get("step", 0))
            if not events:
                warn(f"flow {flow_name}: no events declared, skipping")
                continue

            # Define each event schema (idempotent on 409). Definitions are
            # independent, and HubSpotClient throttles the shared request stream.
            with ThreadPoolExecutor(max_workers=min(6, len(events))) as ex:
                full_names: list[str | None] = list(
                    ex.map(self._define_event_schema, events)
                )
            missing_schemas = [
                evt["name"] for evt, full_name in zip(events, full_names)
                if not full_name
            ]

            strat = flow.get("firing_strategy") or {}
            requested_contact_count = max(1, int(strat.get("contact_count", 30)))
            contact_count = min(requested_contact_count, len(all_contacts))
            if contact_count < requested_contact_count:
                warn(
                    f"flow {flow_name}: requested {requested_contact_count} contacts "
                    f"but only {len(all_contacts)} exist"
                )
            if contact_count < 20:
                warn(
                    f"flow {flow_name}: only {contact_count} contacts available; "
                    "Sankey/funnel may render thin"
                )
            drop_offs = strat.get("drop_off_rates")
            if not drop_offs:
                # Varied default avoids the "single straight line" Sankey tell.
                defaults = [0.72, 0.61, 0.54, 0.47, 0.39]
                drop_offs = [defaults[i % len(defaults)] for i in range(len(events) - 1)]
            if len(drop_offs) != len(events) - 1:
                warn(
                    f"flow {flow_name}: drop_off_rates length "
                    f"{len(drop_offs)} != events-1 {len(events)-1}; "
                    f"padding/truncating with 0.6"
                )
                drop_offs = (list(drop_offs) + [0.6] * len(events))[: len(events) - 1]
            clean_drop_offs: list[float] = []
            for raw in drop_offs:
                try:
                    retention = float(raw)
                except (TypeError, ValueError):
                    warn(f"flow {flow_name}: invalid retention {raw!r}; using 0.6")
                    retention = 0.6
                if retention < 0 or retention > 1:
                    warn(
                        f"flow {flow_name}: retention {raw!r} outside 0..1; "
                        "clamping"
                    )
                    retention = min(1.0, max(0.0, retention))
                clean_drop_offs.append(retention)
            date_range_days = max(7, int(strat.get("date_range_days", 60)))
            recency_bias = bool(strat.get("later_steps_recent", True))

            # Compute per-step survivor lists.
            survivors = list(random.sample(all_contacts, contact_count))
            per_step_survivors: list[list[str]] = [survivors]
            current = survivors
            for retention in clean_drop_offs:
                keep = int(round(len(current) * retention))
                if retention > 0 and current:
                    keep = max(1, keep)
                current = random.sample(current, min(keep, len(current)))
                per_step_survivors.append(current)

            # Build the send batch with backdated occurredAt timestamps.
            sends: list[dict] = []
            now = datetime.datetime.utcnow()
            n_steps = len(events)
            occurred_values: list[str] = []
            for step_idx, (evt, full_name) in enumerate(zip(events, full_names)):
                if not full_name:
                    continue
                for email in per_step_survivors[step_idx]:
                    if recency_bias and n_steps > 1:
                        # Step 0 (first) spans full window; final step compressed
                        # into the most-recent ~30% of the window for momentum.
                        bias = step_idx / (n_steps - 1)
                        max_age = max(1.0, date_range_days * (1.0 - bias * 0.7))
                        days_ago = random.uniform(1.0, max_age)
                    else:
                        days_ago = random.uniform(1.0, float(date_range_days))
                    occurred = (now - datetime.timedelta(days=days_ago)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    occurred_values.append(occurred)
                    props_src = evt.get("demo_property_values") or {
                        p["name"]: p.get("demo_value", "sample")
                        for p in evt.get("properties", [])
                    }
                    sends.append({
                        "eventName": full_name,
                        "email": email,
                        "properties": props_src,
                        "occurredAt": occurred,
                    })

            fires = self._send_event_occurrences(sends, flow_name)
            grand_total_fires += fires

            # Optional schema-existence validation. The events API does not
            # expose a queryable per-completion count, so we can't validate
            # that backdated occurredAt timestamps actually landed. GETing
            # each definition at least confirms the schemas are reachable.
            validate_passed = None
            if strat.get("validate_via_get", True):
                validate_passed = True
                for evt in events:
                    status, _ = self.client.request(
                        "GET", f"/events/v3/event-definitions/{evt['name']}"
                    )
                    if not self.client.is_ok(status):
                        validate_passed = False

            self.manifest["custom_event_flows"][flow_name] = {
                "events_declared": [e["name"] for e in events],
                "events_defined": [
                    e["name"] for e, full_name in zip(events, full_names) if full_name
                ],
                "missing_event_schemas": missing_schemas,
                "fires_per_step": [len(s) for s in per_step_survivors],
                "fires_attempted": len(sends),
                "fires_succeeded": fires,
                "date_range_days": date_range_days,
                "recency_bias": recency_bias,
                "validate_via_get_passed": validate_passed,
                "occurred_at_range": (
                    [min(occurred_values), max(occurred_values)]
                    if occurred_values else []
                ),
            }
            ok(
                f"flow {flow_name}: {fires}/{len(sends)} fires across "
                f"{n_steps} steps (survivors: {[len(s) for s in per_step_survivors]})"
            )

        self.manifest["custom_events_fired_count"] = (
            int(self.manifest.get("custom_events_fired_count") or 0)
            + grand_total_fires
        )

    # ---- Phase 8: Forms ----

    # Default HubSpot contact properties — never auto-created. Anything outside
    # this set that a plan references in `plan["forms"][i]["fields"]` must be
    # pre-created on the contacts object, otherwise the form POST 400s with a
    # generic "internal error" (verified on 1800LAW1010 production run
    # 2026-04-27 — `practice_area`, `nps_score`, `nps_feedback` all hit this).
    HUBSPOT_DEFAULT_CONTACT_PROPS = frozenset({
        "email", "firstname", "lastname", "phone", "mobilephone", "fax",
        "website", "company", "jobtitle",
    })

    def _ensure_form_field_properties(self) -> None:
        """Pre-flight check that runs BEFORE create_forms (Phase 8).

        Walks every `plan["forms"][i]["fields"]` entry and ensures any field
        whose name isn't a default HubSpot contact property exists on the
        contacts object. If it doesn't exist, creates it with the right
        HubSpot property type derived from the form field's type. If it exists
        but is in the wrong group (cross-prospect contamination from a prior
        run), PATCHes the groupName to match the current prospect's group.

        Uses the same group-naming convention as Phase 15
        (`property_group.name` from plan, or `f"{slug}_demo_properties"`).

        Failures degrade gracefully: a manual_step is added rather than
        crashing the build, so the rep can pre-create the property by hand
        and re-run.
        """
        forms = self.plan.get("forms") or []
        if not forms:
            return
        log("Phase 8 pre-flight: ensure form field properties exist on contacts")

        # Match Phase 15's group-naming convention.
        company_label = (self.manifest.get("company") or {}).get("name") or self.slug
        pg = self.plan.get("property_group", {}) or {}
        group_name = pg.get("name", f"{self.slug}_demo_properties")
        group_label = pg.get("label", f"Demo ({company_label})")

        # Ensure the property group exists on the CONTACTS object too. Phase 15
        # only creates it on deals; forms reference contact properties.
        gbody = {"name": group_name, "label": group_label, "displayOrder": 1}
        sg, rg = self.client.request("POST",
                                     "/crm/v3/properties/contacts/groups", gbody)
        if sg == 409:
            ok(f"  contact property group {group_name} already exists")
        elif self.client.is_ok(sg):
            ok(f"  contact property group {group_name} created")
        else:
            warn(f"  contact property group: {sg} {str(rg)[:200]}")
            # Don't bail — POST property below may still succeed in default group.

        # Collect unique non-default field names referenced across all forms.
        seen: dict[str, dict] = {}  # name -> first field dict that referenced it
        for fp in forms:
            for fld in fp.get("fields", []):
                fname = fld.get("name")
                if not fname:
                    continue
                if fname in self.HUBSPOT_DEFAULT_CONTACT_PROPS:
                    continue
                if fname not in seen:
                    seen[fname] = fld

        if not seen:
            ok("  no custom form-field properties to ensure")
            return

        for fname, fld in seen.items():
            # Check if it already exists.
            sx, rx = self.client.request(
                "GET", f"/crm/v3/properties/contacts/{fname}")
            if self.client.is_ok(sx):
                # Already exists. PATCH groupName if it doesn't match
                # (cross-prospect contamination protection — same pattern as
                # fix #2 for deal_age_days).
                self._regroup_property_to_match("contacts", fname, group_name)
                continue
            if sx not in (404,):
                warn(f"  GET contacts.{fname}: {sx} {str(rx)[:200]}")

            # Doesn't exist → create. Map form field_type → HubSpot property type.
            declared = (fld.get("field_type") or "single_line_text").lower()
            if declared == "dropdown":
                opts = fld.get("options") or []
                norm_opts = []
                for idx, o in enumerate(opts):
                    if isinstance(o, dict):
                        norm_opts.append({
                            "label": str(o.get("label", o.get("value", ""))),
                            "value": str(o.get("value", o.get("label", ""))),
                            "displayOrder": idx + 1,
                        })
                    else:
                        norm_opts.append({
                            "label": str(o), "value": str(o),
                            "displayOrder": idx + 1,
                        })
                prop_body = {
                    "name": fname, "label": fld.get("label", fname),
                    "type": "enumeration", "fieldType": "select",
                    "groupName": group_name, "options": norm_opts,
                    "description": f"Demo property for {fname}.",
                }
            elif declared == "multi_line_text":
                prop_body = {
                    "name": fname, "label": fld.get("label", fname),
                    "type": "string", "fieldType": "textarea",
                    "groupName": group_name,
                    "description": f"Demo property for {fname}.",
                }
            elif declared == "number":
                prop_body = {
                    "name": fname, "label": fld.get("label", fname),
                    "type": "number", "fieldType": "number",
                    "groupName": group_name,
                    "description": f"Demo property for {fname}.",
                }
            elif declared == "datepicker":
                prop_body = {
                    "name": fname, "label": fld.get("label", fname),
                    "type": "date", "fieldType": "date",
                    "groupName": group_name,
                    "description": f"Demo property for {fname}.",
                }
            elif declared == "single_checkbox":
                prop_body = {
                    "name": fname, "label": fld.get("label", fname),
                    "type": "bool", "fieldType": "booleancheckbox",
                    "groupName": group_name,
                    "options": [
                        {"label": "Yes", "value": "true", "displayOrder": 1},
                        {"label": "No",  "value": "false", "displayOrder": 2},
                    ],
                    "description": f"Demo property for {fname}.",
                }
            else:
                # single_line_text, email, phone, mobile_phone, file, radio,
                # multiple_checkboxes — fall back to a string text property.
                # The HubSpot built-in `email` property already exists so this
                # branch shouldn't fire for `email` itself.
                prop_body = {
                    "name": fname, "label": fld.get("label", fname),
                    "type": "string", "fieldType": "text",
                    "groupName": group_name,
                    "description": f"Demo property for {fname}.",
                }

            sc, rc = self.client.request(
                "POST", "/crm/v3/properties/contacts", prop_body)
            if self.client.is_ok(sc):
                ok(f"  contacts.{fname} created (group={group_name})")
            elif sc == 409:
                # Race condition — created between our GET and POST. Regroup.
                self._regroup_property_to_match("contacts", fname, group_name)
            else:
                warn(f"  contacts.{fname} create: {sc} {str(rc)[:200]}")
                self.add_manual_step(
                    f"contacts.{fname}",
                    self.url("contacts", self.portal, "property-settings"),
                    f"Pre-create contact property {fname!r} (type derived "
                    f"from form field_type={declared!r}) under group "
                    f"{group_name!r}, then re-run the build to create forms.",
                    f"POST /crm/v3/properties/contacts returned {sc}: {str(rc)[:200]}",
                )

    def create_forms(self) -> None:
        if not self.plan.get("forms"):
            return
        log("Phase 8: Forms")
        # HubSpot's Forms v3 API rejects forms where a default contact property
        # is mapped with the wrong field type. The plan often declares phone/email
        # as "single_line_text"; HubSpot requires the type to match the underlying
        # property (phone = "phone", email = "email"). Auto-correct here.
        DEFAULT_CONTACT_FIELD_TYPES = {
            "email": "email",
            "phone": "phone",
            "mobilephone": "phone",
            "fax": "phone",
            "website": "single_line_text",
            "firstname": "single_line_text",
            "lastname": "single_line_text",
            "company": "single_line_text",
            "jobtitle": "single_line_text",
        }
        # Field types that are valid HubSpot Forms v3 fieldType values.
        # The plan can declare any of these via field["field_type"].
        # NOTE (verified 2026-04-27 via 400-error probe of v3 Forms endpoint):
        # The authoritative list of known type ids returned by HubSpot is:
        #   datepicker, dropdown, email, file, mobile_phone, multi_line_text,
        #   multiple_checkboxes, number, payment_link_radio, phone, radio,
        #   single_checkbox, single_line_text
        # `dropdown` is the v3 API value (not `dropdown_select`); each option
        # must include a `displayOrder` integer. The previous `dropdown_select`
        # alias was rejected silently — verified on 1800LAW1010 production run.
        SUPPORTED_FIELD_TYPES = {
            "single_line_text", "multi_line_text", "email", "phone_number",
            "phone", "mobile_phone", "number", "dropdown",
            "datepicker", "radio", "multiple_checkboxes", "single_checkbox",
            "file",
        }

        # Plan branding for theming (used when form has a `theme` block, AND
        # — per fix J — as the always-applied default when the plan omits one).
        plan_brand = self.plan.get("branding", {}) or {}
        research_brand = self.research.get("branding", {}) or {}
        plan_primary_color = (plan_brand.get("primary_color")
                              or research_brand.get("primary_color")
                              or plan_brand.get("accent_color")
                              or research_brand.get("accent_color")
                              or "#3B82F6")

        # HubSpot Forms v3 requires every field to carry a `validation` object.
        # Email fields use blocked-domain settings; number fields can carry
        # min/max range; everything else gets the no-op default.
        # NOTE (verified 2026-04-26): HubSpot's public docs are ambiguous on
        # the exact key names for numeric range validation in the v3 Forms API.
        # `minAllowedDigits` / `maxAllowedDigits` works for the validated
        # Boomer NPS form (1-10 scale) — leaving as-is until we hit a 4xx that
        # tells us otherwise. TODO: revisit if a POST 4xx mentions validation.
        def _validation(field_name: str, ftype: str, fld: dict) -> dict:
            if ftype == "email":
                return {
                    "blockedEmailDomains": [],
                    "useDefaultBlockList": False,
                }
            if ftype == "number":
                v: dict = {}
                if "min" in fld:
                    v["minAllowedDigits"] = fld["min"]
                if "max" in fld:
                    v["maxAllowedDigits"] = fld["max"]
                return v
            return {}

        def _build_form_body(fp: dict) -> tuple[dict, list[dict]]:
            """Return (body, all_fields) for a planned form. Pure builder —
            no API calls. Callers reuse this for both POST (create) and PUT
            (PATCH-on-existing) so the wire payload is identical."""
            all_fields = []
            for fld in fp["fields"]:
                declared = fld.get("field_type", "single_line_text")
                ftype = DEFAULT_CONTACT_FIELD_TYPES.get(fld["name"], declared)
                if ftype not in SUPPORTED_FIELD_TYPES:
                    warn(f"  unknown field_type {ftype!r} on {fld['name']}; coercing to single_line_text")
                    ftype = "single_line_text"
                field_obj = {
                    "objectTypeId": "0-1",
                    "name": fld["name"],
                    "label": fld["label"],
                    "required": fld.get("required", False),
                    "hidden": False,
                    "fieldType": ftype,
                    "validation": _validation(fld["name"], ftype, fld),
                }
                # `dropdown` and `radio` both require an `options` array in the
                # v3 Forms API. Each option needs `label`, `value`, and a
                # 1-indexed `displayOrder` integer (verified 2026-04-27).
                # `radio` is the recommended type for NPS scales (1-10) — it
                # surfaces a horizontal button-row UX that beats free-text
                # entry on a `number` field. See Fix E1 (2026-04-26) and
                # SKILL.md Phase 2 Quality Gate.
                if ftype in ("dropdown", "radio"):
                    opts = fld.get("options") or []
                    # NPS auto-population: if a radio field is named `nps_score`
                    # (or the form is an NPS form and the field shape calls
                    # for 1-10) and no options were provided, synthesize the
                    # canonical 1-10 ladder so plans don't have to enumerate
                    # ten dicts inline.
                    if not opts and ftype == "radio":
                        is_nps_field = (
                            fld["name"].lower() in ("nps_score", "score")
                            or (fld.get("min") == 1 and fld.get("max") == 10)
                        )
                        if is_nps_field:
                            opts = [{"label": str(n), "value": str(n)}
                                    for n in range(1, 11)]
                    norm_opts = []
                    for idx, o in enumerate(opts):
                        if isinstance(o, dict):
                            norm_opts.append({
                                "label": str(o.get("label", o.get("value", ""))),
                                "value": str(o.get("value", o.get("label", ""))),
                                "displayOrder": o.get("displayOrder", idx + 1),
                            })
                        else:
                            norm_opts.append({
                                "label": str(o), "value": str(o),
                                "displayOrder": idx + 1,
                            })
                    field_obj["options"] = norm_opts
                all_fields.append(field_obj)

            groups = [{"groupType": "default_group", "richTextType": "text",
                       "fields": all_fields[i:i+3]} for i in range(0, len(all_fields), 3)]
            now = datetime.datetime.utcnow().isoformat() + "Z"

            # Always synthesize a default style block from branding (fix J).
            # plan["forms"][i].theme overlays explicit values on top.
            display_options: dict = {
                "renderRawHtml": False,
                "theme": "default_style",
                "submitButtonText": fp.get("submit_text", "Submit"),
                "style": {
                    "submitColor": plan_primary_color,
                    "submitFontColor": "#FFFFFF",
                },
            }
            theme = fp.get("theme") or {}
            if theme:
                if theme.get("submit_button_color"):
                    display_options["style"]["submitColor"] = theme["submit_button_color"]
                if theme.get("submit_text_color"):
                    display_options["style"]["submitFontColor"] = theme["submit_text_color"]

            body = {"name": fp["name"], "formType": "hubspot",
                    "createdAt": now, "updatedAt": now, "archived": False,
                    "fieldGroups": groups,
                    "configuration": {"language": "en", "cloneable": True, "editable": True,
                                      "archivable": True, "recaptchaEnabled": False,
                                      "createNewContactForNewEmail": False,
                                      "allowLinkToResetKnownValues": False},
                    "displayOptions": display_options,
                    "legalConsentOptions": {"type": "none"}}
            return body, all_fields

        def _fingerprint(field_groups: list[dict]) -> tuple:
            """Stable signature for form schema drift detection. Tuple of
            (field_count, sorted (name, fieldType) pairs). If this tuple
            differs between an existing form and the planned form, we PATCH."""
            fields = []
            for g in (field_groups or []):
                for f in (g.get("fields") or []):
                    fields.append((f.get("name", ""), f.get("fieldType", "")))
            return (len(fields), tuple(sorted(fields)))

        for fp in self.plan["forms"]:
            manifest_form_name = fp["name"]
            # Find existing by listing all (HubSpot list endpoint doesn't filter by name)
            existing_guid = None
            existing_fingerprint = None
            s, r = self.client.request("GET", "/marketing/v3/forms", query={"limit": 100})
            if self.client.is_ok(s):
                for f in r.get("results", []):
                    if f.get("name") == fp["name"]:
                        existing_guid = f["id"]
                        existing_fingerprint = _fingerprint(f.get("fieldGroups", []) or [])
                        break

            body, all_fields = _build_form_body(fp)
            planned_fingerprint = _fingerprint(body["fieldGroups"])

            if existing_guid:
                if existing_fingerprint != planned_fingerprint:
                    # Schema drift: PATCH the form so the new fields/theme land.
                    # PUT is the v3 update verb. If HubSpot rejects (some
                    # hubspot-type forms can't be fully replaced via the API),
                    # we log a manual_step telling the rep to delete + recreate.
                    s2, r2 = self.client.request(
                        "PUT", f"/marketing/v3/forms/{existing_guid}", body)
                    if self.client.is_ok(s2):
                        self.manifest["forms"][fp["name"]] = existing_guid
                        ok(f"form {fp['name']} schema updated → {existing_guid} (PATCH)")
                    else:
                        warn(f"form {fp['name']}: PATCH rejected ({s2}); leaving stale schema in place")
                        self.add_error(f"form.patch:{fp['name']}", s2, r2)
                        # Stale forms survive across runs because HubSpot has
                        # historically been inconsistent about UI-only form
                        # cleanup. If update fails, create a fresh slug-scoped
                        # copy instead of reusing the stale schema and letting
                        # the demo doc point at the wrong questions.
                        fresh_body = json.loads(json.dumps(body))
                        fresh_name = f"{fp['name']} - {self.slug}"
                        fresh_body["name"] = fresh_name
                        s3, r3 = self.client.request("POST", "/marketing/v3/forms", fresh_body)
                        if self.client.is_ok(s3):
                            self.manifest["forms"][fresh_name] = r3["id"]
                            manifest_form_name = fresh_name
                            ok(f"form {fp['name']} recreated as {fresh_name} → {r3['id']}")
                        else:
                            self.manifest["forms"][fp["name"]] = existing_guid
                            self.add_error(f"form.recreate:{fp['name']}", s3, r3)
                            self.add_manual_step(
                                f"Refresh form schema: {fp['name']}",
                                self.url("forms", self.portal),
                                (f"The existing form {fp['name']!r} still has the old "
                                 f"field set. Delete it in the UI and re-run, or edit "
                                 f"by hand to add the planned fields."),
                                # Forbidden token "Forms API" forces sanitize.
                                f"Forms API rejected schema PATCH (status {s2}) and recreate returned {s3}",
                            )
                else:
                    self.manifest["forms"][fp["name"]] = existing_guid
                    ok(f"reusing form {fp['name']} (schema matches)")
            else:
                s, r = self.client.request("POST", "/marketing/v3/forms", body)
                if self.client.is_ok(s):
                    self.manifest["forms"][fp["name"]] = r["id"]
                    ok(f"form {fp['name']} → {r['id']}")
                else:
                    warn(f"form {fp['name']}: {s} {str(r)[:200]}")
                    self.add_error(f"form.create:{fp['name']}", s, r)
                    if "fieldType" in str(r) or "fieldtype" in str(r).lower():
                        warn(f"  TODO: spot-check the form preview in HubSpot — "
                             f"the v3 fieldType values may need adjustment.")
                    continue

            form_guid = self.manifest["forms"][manifest_form_name]
            # Submit test fills (parallel) — value generation branches on
            # field TYPE (not field name), so dropdowns get a valid option,
            # numbers get a number, etc.
            n = fp.get("test_submissions", 5)
            tsd = fp.get("test_submission_data", {}) or {}
            first_names = tsd.get("first_names") or [
                "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Sam", "Drew",
            ]
            last_names = tsd.get("last_names") or [
                "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Davis", "Miller",
            ]
            values_by_field = tsd.get("values_by_field") or {}

            # NPS detection: form name contains "NPS" or any field is named nps_score.
            field_names_lower = {fld["name"].lower() for fld in fp["fields"]}
            is_nps = ("nps" in fp["name"].lower()) or ("nps_score" in field_names_lower)
            score_dist = tsd.get("score_distribution") or {"9-10": 0.5, "7-8": 0.3, "1-6": 0.2}
            feedback_pool = tsd.get("feedback_pool") or [
                "Great service.", "Quick turnaround.", "Helpful team.",
                "Could be better.", "Met expectations.",
            ]

            def _nps_bucket() -> str:
                # Pick a bucket per the configured weights; default safe distribution.
                buckets = list(score_dist.keys())
                weights = [float(score_dist.get(b, 0)) for b in buckets]
                if sum(weights) <= 0:
                    return random.choice(["9-10", "7-8", "1-6"])
                return random.choices(buckets, weights=weights, k=1)[0]

            def _nps_score_from_bucket(bucket: str) -> int:
                if bucket == "9-10":
                    return random.choice([9, 10])
                if bucket == "7-8":
                    return random.choice([7, 8])
                if bucket == "1-6":
                    return random.randint(1, 6)
                # Custom bucket of form "lo-hi"
                try:
                    lo, hi = bucket.split("-")
                    return random.randint(int(lo), int(hi))
                except (ValueError, AttributeError):
                    return random.randint(1, 10)

            def _value_for(fld: dict, i: int) -> str:
                """Generate a valid test-submission value for a field. Branches
                on field TYPE first (so dropdowns/numbers/multi-line text always
                produce valid input), then falls back to the legacy name-based
                special cases for email/firstname/lastname."""
                fname = fld["name"]
                # Plan-supplied per-field values win over everything.
                if fname in values_by_field and values_by_field[fname]:
                    return random.choice(values_by_field[fname])

                # Legacy name-based path (kept for email/name fields whose
                # values need realistic shape regardless of declared type).
                if fname == "email":
                    return f"demo-lead-{i}-{random.randint(1000,9999)}@demo{self.slug}.com"
                if fname == "firstname":
                    return random.choice(first_names)
                if fname == "lastname":
                    return random.choice(last_names)

                # NPS-specific name-based shortcuts (still type-correct).
                if is_nps and fname == "nps_score":
                    return str(_nps_score_from_bucket(_nps_bucket()))
                if is_nps and fname in ("nps_feedback", "feedback", "comments"):
                    return random.choice(feedback_pool)

                # Type-based generation — the big fix-E branch.
                declared = fld.get("field_type", "single_line_text")
                ftype = DEFAULT_CONTACT_FIELD_TYPES.get(fname, declared)

                # `dropdown` and `radio` both pick from `options` (verified
                # 2026-04-27). The radio branch is the NPS-friendly path —
                # see Fix E1 (2026-04-26): NPS forms now default to radio
                # (1-10) instead of free-text number entry.
                if ftype in ("dropdown", "radio"):
                    opts = fld.get("options") or []
                    # Mirror the auto-population in `_build_form_body`: an NPS
                    # radio field with no explicit options gets the 1-10 ladder.
                    if not opts and ftype == "radio":
                        is_nps_field = (
                            fname.lower() in ("nps_score", "score")
                            or (fld.get("min") == 1 and fld.get("max") == 10)
                        )
                        if is_nps_field:
                            opts = [{"value": str(n)} for n in range(1, 11)]
                    if opts:
                        # NPS bias: if the field is the NPS score field and we
                        # have 1-10 options, weight by score_distribution so
                        # the distribution looks realistic instead of uniform.
                        if (is_nps and fname.lower() in ("nps_score", "score")
                                and len(opts) == 10):
                            return str(_nps_score_from_bucket(_nps_bucket()))
                        choice = random.choice(opts)
                        if isinstance(choice, dict):
                            return str(choice.get("value", choice.get("label", "")))
                        return str(choice)
                    # Empty options on a dropdown/radio is a plan bug — submitting
                    # "sample" would 4xx and silently drop from form_submissions_count.
                    # Surface it and skip this field entirely (omit from the submission).
                    warn(f"form '{fp['name']}': {ftype} field '{fname}' has empty options; "
                         f"skipping this field in test submissions to avoid 4xx")
                    return None  # caller filters None values out

                if ftype == "number":
                    validation = fld.get("validation") or {}
                    lo = int(fld.get("min",
                              validation.get("min",
                              validation.get("minAllowedDigits", 1))))
                    hi = int(fld.get("max",
                              validation.get("max",
                              validation.get("maxAllowedDigits", 100))))
                    if hi < lo:
                        lo, hi = hi, lo
                    # If this is the NPS form's score field hit via a non-
                    # standard property name, weight by score_distribution.
                    if is_nps and lo == 1 and hi == 10:
                        return str(_nps_score_from_bucket(_nps_bucket()))
                    return str(random.randint(lo, hi))

                if ftype == "multi_line_text":
                    return random.choice(feedback_pool)

                if ftype in ("phone", "phone_number"):
                    return (f"({random.randint(200, 999)}) "
                            f"{random.randint(200, 999)}-{random.randint(1000, 9999)}")

                # single_line_text and anything else: return a sensible default.
                return "sample"

            submission_bodies = []
            for i in range(n):
                fields = []
                for fld in fp["fields"]:
                    val = _value_for(fld, i)
                    if val is None:
                        # _value_for returned None to signal "skip this field"
                        # (empty-options dropdown). Omit it from the submission.
                        continue
                    fields.append({"objectTypeId": "0-1", "name": fld["name"], "value": val})
                submission_bodies.append({
                    "fields": fields,
                    "context": {"pageUri": "https://example.com/demo", "pageName": fp["name"]},
                })
            with ThreadPoolExecutor(max_workers=3) as ex:
                futures = [ex.submit(self.client.form_submit, form_guid, b) for b in submission_bodies]
                ok_count = sum(1 for f in as_completed(futures) if 200 <= f.result()[0] < 300)
            # Per-form actual-vs-planned breakdown is recorded so the integrity
            # check can show which form fell short (fix D message).
            self.manifest.setdefault("form_submissions_per_form", {})[manifest_form_name] = {
                "actual": ok_count, "planned": n,
            }
            self.manifest["form_submissions_count"] += ok_count
            ok(f"  submissions: {ok_count}/{n}")

    # ---- Phase 9: Lead scoring + hot list ----

    def lead_scoring(self) -> None:
        log("Phase 9: Lead scoring")
        if not self.manifest["contacts"]:
            return
        # Backfill scores (parallel)
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = []
            for cid in self.manifest["contacts"].values():
                score = random.randint(20, 100)
                futures.append(ex.submit(
                    self.client.request, "PATCH", f"/crm/v3/objects/contacts/{cid}",
                    {"properties": {"demo_lead_score": str(score)}}
                ))
            ok_count = sum(1 for f in as_completed(futures) if self.client.is_ok(f.result()[0]))
        ok(f"scores set: {ok_count}/{len(self.manifest['contacts'])}")
        self.manifest["lead_scoring"] = {"property": "demo_lead_score", "backfilled": ok_count}

        # Hot list with dedup. Use HubSpot's GET-by-name endpoint (the list-all endpoint
        # response shape is inconsistent and the prior heuristic failed silently).
        list_name = f"Demo: Hot leads by score ({self.slug})"
        list_id = None
        encoded = urllib.parse.quote(list_name, safe="")
        s, r = self.client.request("GET", f"/crm/v3/lists/object-type-id/0-1/name/{encoded}")
        if self.client.is_ok(s):
            payload = r.get("list", r) or {}
            list_id = payload.get("listId") or payload.get("id")
        if not list_id:
            body = {"name": list_name, "objectTypeId": "0-1", "processingType": "MANUAL"}
            s, r = self.client.request("POST", "/crm/v3/lists", body)
            if self.client.is_ok(s):
                list_id = r.get("list", {}).get("listId") or r.get("listId") or r.get("id")
                ok(f"hot leads list → {list_id}")
            elif s == 400 and "already exist" in str(r).lower():
                # Race / stale state. Re-query by name to recover the existing id.
                s2, r2 = self.client.request("GET", f"/crm/v3/lists/object-type-id/0-1/name/{encoded}")
                if self.client.is_ok(s2):
                    payload = r2.get("list", r2) or {}
                    list_id = payload.get("listId") or payload.get("id")
                if list_id:
                    ok(f"hot leads list (reused existing) → {list_id}")
                else:
                    warn(f"hot leads list: 400 'already exists' but lookup failed: {str(r2)[:200]}")
                    self.add_error("hot_leads_list", s, r)
                    return
            else:
                warn(f"hot leads list: {s} {str(r)[:200]}")
                self.add_error("hot_leads_list", s, r)
                return
        # Add top 5
        top = list(self.manifest["contacts"].values())[:5]
        if list_id and top:
            self.client.request("PUT", f"/crm/v3/lists/{list_id}/memberships/add",
                                {"recordIdsToAdd": top})
        if list_id:
            self.manifest["lead_scoring"]["list_id"] = list_id
            self.manifest["lead_scoring"]["list_url"] = self.url(
                "contacts", self.portal, "objects/0-1/views", str(list_id), "list"
            )
        # Mirror every list this run produced into a top-level manifest["lists"]
        # so time_estimates can read len(manifest["lists"]) without knowing where
        # each list lives. Includes the hot-leads list + any other_lists the
        # plan added later.
        all_lists = []
        if list_id:
            all_lists.append(list_id)
        for lid in (self.manifest.get("lead_scoring", {}).get("other_lists") or []):
            if lid and lid not in all_lists:
                all_lists.append(lid)
        if all_lists:
            self.manifest["lists"] = all_lists

    # ---- Phase 10: AI marketing email ----

    def upload_hero_image(self, local_path: str, folder: str = "/demo-prep") -> str | None:
        """Upload an image to HubSpot Files via REST API. Returns CDN URL."""
        return self._upload_file_to_hubspot(local_path, folder, label="hero")

    def upload_logo_image(self, local_path: str, folder: str = "/demo-prep") -> str | None:
        """Upload the prospect's logo to HubSpot Files. Returns CDN URL.

        Used by `marketing_email` to render the prospect's logo in a small
        header strip above the hero image. See Fix F-builder (2026-04-26).
        Mirrors `upload_hero_image` so we keep the multipart upload code in
        a single helper and the two phases share one well-tested path.
        """
        return self._upload_file_to_hubspot(local_path, folder, label="logo")

    def _upload_file_to_hubspot(
        self, local_path: str, folder: str, label: str = "file",
    ) -> str | None:
        """Internal multipart upload helper. Returns CDN URL on success."""
        try:
            import mimetypes
            mime, _ = mimetypes.guess_type(local_path)
            mime = mime or "image/png"
            boundary = "----HubSpotDemoPrep" + str(int(time.time()))
            with open(local_path, "rb") as f:
                file_bytes = f.read()
            options_json = json.dumps({"access": "PUBLIC_INDEXABLE", "overwrite": True})
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(local_path)}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode() + file_bytes + (
                f"\r\n--{boundary}\r\n"
                f'Content-Disposition: form-data; name="options"\r\n'
                f"Content-Type: application/json\r\n\r\n{options_json}\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="folderPath"\r\n\r\n{folder}\r\n'
                f"--{boundary}--\r\n"
            ).encode()
            req = urllib.request.Request(
                "https://api.hubapi.com/files/v3/files",
                data=body,
                headers={
                    "Authorization": f"Bearer {self.client.token}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
                return data.get("url")
        except Exception as e:
            warn(f"{label} upload failed: {e}")
            return None

    def find_template_email_widgets(self) -> dict | None:
        """Find an existing email in the portal with the welcome_3 template
        whose widget structure we can clone (HubSpot ships these by default)."""
        s, r = self.client.request("GET", "/marketing/v3/emails", query={"limit": 50})
        if not self.client.is_ok(s):
            return None
        for e in r.get("results", []):
            tpath = (e.get("templatePath") or e.get("content", {}).get("templatePath") or "")
            if "welcome_3" in tpath or "Start_from_scratch" in tpath:
                # Fetch full body
                s2, full = self.client.request("GET", f"/marketing/v3/emails/{e['id']}")
                if self.client.is_ok(s2):
                    return full
        return None

    def marketing_email(self) -> None:
        if not self.plan.get("marketing_email"):
            return
        log("Phase 10: Marketing email (with AI hero image, in HubSpot)")
        me = self.plan["marketing_email"]
        bu_id = "0"  # HubSpot's default business unit on every portal
        # Find hero image we generated (path was saved by orchestrator at build-plan time)
        hero_b64 = None
        hero_path = self.plan.get("marketing_email", {}).get("hero_image_path")
        if hero_path and os.path.exists(hero_path):
            with open(hero_path, "rb") as f:
                hero_b64 = base64.b64encode(f.read()).decode()
        elif self.plan.get("marketing_email", {}).get("hero_image_url"):
            try:
                req = urllib.request.Request(self.plan["marketing_email"]["hero_image_url"],
                                             headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    hero_b64 = base64.b64encode(r.read()).decode()
            except Exception as e:
                warn(f"hero image fetch failed: {e}")

        # Logo image for the email header strip (Fix F-builder, 2026-04-26).
        # Always-on Playwright logo screenshot in Phase 1 lands at
        # `plan["branding"]["logo_path"]`. Upload it to HubSpot Files now so
        # both the hosted email and the saved local HTML can reference a CDN
        # URL. We inline it as base64 in the local HTML for offline preview;
        # the hosted email widget gets the CDN URL.
        plan_brand_for_logo = self.plan.get("branding", {}) or {}
        local_logo_path = (
            plan_brand_for_logo.get("logo_path")
            or (self.research.get("branding") or {}).get("logo_path")
        )
        logo_hubspot_url = None
        logo_b64 = None
        if local_logo_path and os.path.exists(local_logo_path):
            with open(local_logo_path, "rb") as f:
                logo_b64 = base64.b64encode(f.read()).decode()
            logo_hubspot_url = self.upload_logo_image(
                local_logo_path, folder=f"/demo-prep-{self.slug}"
            )
            if logo_hubspot_url:
                ok(f"logo uploaded to HubSpot: {logo_hubspot_url}")
                # Persist on the manifest so doc_generator + downstream
                # phases can reference it without re-uploading.
                self.manifest.setdefault("branding", {})["logo_url"] = logo_hubspot_url
                self.manifest["branding"]["logo_path"] = local_logo_path

        # Branding: prefer plan["branding"] (locked schema), then research["branding"] (legacy),
        # then industry-neutral defaults. The old #FF6B35 fallback was Shipperz transport orange
        # and bled into every demo regardless of prospect.
        plan_brand = self.plan.get("branding", {}) or {}
        research_brand = self.research.get("branding", {}) or {}
        primary = (plan_brand.get("primary_color")
                   or research_brand.get("primary_color")
                   or "#1a1a1a")
        secondary = (plan_brand.get("secondary_color")
                     or research_brand.get("secondary_color")
                     or "#1A1A1A")
        accent = (plan_brand.get("accent_color")
                  or research_brand.get("accent_color")
                  or "#3B82F6")
        company_name = self.manifest["company"]["name"]

        def _hex_luminance(hex_color: str) -> float:
            h = (hex_color or "").strip().lstrip("#")
            if len(h) == 3:
                h = "".join(ch * 2 for ch in h)
            if len(h) != 6:
                return 0.0
            try:
                r, g, b = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
            except ValueError:
                return 0.0
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        primary_is_bright = _hex_luminance(primary) > 0.70
        heading_color = secondary if primary_is_bright else primary
        footer_text_color = "#111111" if primary_is_bright else "#ffffff"

        hero_img_html = ""
        if hero_b64:
            hero_img_html = f'<img src="data:image/png;base64,{hero_b64}" alt="{company_name} hero" style="display:block;width:100%;height:auto;border-radius:8px;margin:0 0 24px 0">'

        # Logo header strip (Fix F-builder). When we have the prospect's logo,
        # render a centered top header above the hero image. This is the
        # "top 10% / brand-consistent" detail that makes a demo email stop
        # looking like a generic template. If no logo is available, we skip
        # the strip entirely — no broken-image placeholder, no empty box.
        logo_header_html = ""
        if logo_b64:
            logo_header_html = (
                f'<div style="text-align:center;padding:24px 0 16px;'
                f'border-bottom:1px solid #eee;">'
                f'<img src="data:image/png;base64,{logo_b64}" '
                f'alt="{company_name}" '
                f'style="max-height:48px;width:auto;display:inline-block;">'
                f'</div>'
            )

        # CTA color: plan field wins, else branding primary. The legacy hardcoded
        # #FF6B35 leaked Shipperz transport orange into every demo's button.
        cta_color = me.get("cta_color") or primary
        cta_text = me.get("cta_text", "Learn more")
        cta_url = me.get("cta_url") or f"https://www.{self.plan['company']['domain']}"
        footer_tagline = me.get("footer_tagline") or company_name

        # Standalone CTA block — always appended after body_html OR after the
        # fallback steps. The v0.3.1 walkthrough caught that body_html-authored
        # emails landed without a visible CTA because the CTA was only built
        # inside the fallback branch. Now CTA always renders.
        cta_block_html = (
            f'<p style="text-align:center;margin:32px 0 24px 0;">'
            f'<a href="{cta_url}" style="display:inline-block;background:{cta_color};color:#ffffff;'
            f'text-decoration:none;padding:14px 28px;border-radius:6px;font-weight:600;'
            f'font-size:16px;">{cta_text}</a>'
            f'</p>'
        )

        # Email body: prefer the LLM-authored body_html in the plan; else build a
        # generic, industry-neutral fallback from optional `steps`. The legacy
        # fallback hardcoded "vehicle and route" / "Day of pickup" / "auto transport".
        if me.get("body_html"):
            # body_html may not include its own CTA — always append the
            # standalone CTA block so the email has a visible action.
            body_inner_html = me["body_html"] + cta_block_html
        else:
            steps = me.get("steps") or [
                {"timing": "Within 1 hour", "detail": "We confirm your details."},
                {"timing": "Within 24 hours", "detail": "You receive a personalized proposal."},
                {"timing": "Next step", "detail": "Hand-off to your dedicated rep."},
            ]
            steps_html = "".join(
                f'<li><strong>{s.get("timing", "Next")}:</strong> {s.get("detail", "")}</li>'
                for s in steps
            )
            company_blurb = (self.plan.get("company") or {}).get("description", "")
            blurb_first = company_blurb.split(".")[0] + "." if company_blurb else ""
            body_inner_html = (
                f"<p>Thanks for getting in touch with {company_name}. Here's what happens next:</p>"
                f'<ol style="padding-left:20px;">{steps_html}</ol>'
                f'<p style="margin-top:24px;">'
                f'<a href="{cta_url}" style="display:inline-block;background:{cta_color};color:#ffffff;'
                f'text-decoration:none;padding:14px 28px;border-radius:6px;font-weight:600;">{cta_text}</a>'
                f"</p>"
                f'<p style="color:#666;font-size:13px;margin-top:32px;border-top:1px solid #eee;padding-top:16px;">'
                f"Questions? Reply to this email and we'll get back shortly.<br>"
                f"{company_name}{(' · ' + blurb_first) if blurb_first else ''}"
                f"</p>"
            )

        html_body = f"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{me['subject']}</title></head>
<body style="margin:0;padding:0;background:#f4f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<div style="max-width:640px;margin:0 auto;background:#ffffff;">
  {logo_header_html}
  <div style="padding:24px 32px 0 32px;border-top:6px solid {primary};">
	    <h1 style="margin:24px 0 8px 0;color:{heading_color};font-size:28px;line-height:1.2;font-weight:700;">{me['subject']}</h1>
    <p style="color:#666;font-size:14px;margin:0 0 24px 0;">From {me.get('from_name', company_name)}</p>
  </div>
  <div style="padding:0 32px;">{hero_img_html}</div>
  <div style="padding:0 32px 32px 32px;color:#1a1a1a;font-size:16px;line-height:1.6;">
    {body_inner_html}
  </div>
	  <div style="background:{primary};color:{footer_text_color};padding:16px 32px;text-align:center;font-size:12px;">
    {footer_tagline}
  </div>
</div>
</body></html>
""".strip()
        # Save to disk so user/Doc can reference
        email_html_path = f"{self.work_dir}/marketing-email.html"
        with open(email_html_path, "w") as f:
            f.write(html_body)
        ok(f"branded email HTML saved: {email_html_path}")
        self.manifest["marketing_email"]["html_path"] = email_html_path

        # Upload AI hero image to HubSpot File Manager so the email references a HubSpot CDN URL
        hubspot_image_url = None
        local_hero = me.get("hero_image_path")
        if local_hero and os.path.exists(local_hero):
            hubspot_image_url = self.upload_hero_image(local_hero, folder=f"/demo-prep-{self.slug}")
            if hubspot_image_url:
                ok(f"hero image uploaded to HubSpot: {hubspot_image_url}")

        # Clone widget structure from an existing welcome_3 template email
        source = self.find_template_email_widgets()
        if not source:
            warn("No clonable template email found; falling back to bare email")
            body = {"name": me["name"], "subject": me["subject"],
                    "fromName": me.get("from_name", company_name),
                    "state": "DRAFT",
                    "businessUnitId": bu_id,
                    "subscription": {"name": "Marketing Information"},
                    "content": {"templatePath": "@hubspot/email/dnd/Start_from_scratch.html"}}
        else:
            content = source.get("content", {})
            widgets = content.get("widgets", {})
            # Mutate widgets in place: image module and rich-text module
            for k, w in widgets.items():
                wbody = w.get("body", {})
                if wbody.get("path") == "@hubspot/image_email" and hubspot_image_url:
                    wbody["img"] = {
                        "alt": f"{company_name} hero image",
                        "height": 360, "width": 640,
                        "src": hubspot_image_url,
                    }
                    wbody["alignment"] = "center"
                elif wbody.get("path") == "@hubspot/rich_text":
                    # Logo header strip for the hosted email (Fix F-builder).
                    # The CDN-hosted logo URL goes in front of the title so
                    # the recipient sees the prospect's brand mark first. If
                    # we never got a logo, this string is empty — no broken
                    # image, no empty box.
                    widget_logo_header = ""
                    if logo_hubspot_url:
                        widget_logo_header = (
                            f'<div style="text-align:center;padding:24px 0 16px;'
                            f'border-bottom:1px solid #eeeeee;margin-bottom:24px;">'
                            f'<img src="{logo_hubspot_url}" alt="{company_name}" '
                            f'style="max-height:48px;width:auto;display:inline-block;">'
                            f'</div>'
                        )

                    # Use plan body_html verbatim if provided; else build a generic
                    # industry-neutral widget body from optional `steps`. The legacy
                    # widget hardcoded "vehicle/route", "Day of pickup", and a
                    # #FF6B35 transport-orange CTA — all leaked into non-transport demos.
                    # Same standalone-CTA fix as the local-HTML path above.
                    widget_cta_html = (
                        f'<p style="text-align:center;margin:32px 0 24px 0;">'
                        f'<a href="{cta_url}" '
                        f'style="display:inline-block;background:{cta_color};color:#fff;padding:14px 28px;'
                        f'border-radius:6px;text-decoration:none;font-weight:600;font-size:16px;">{cta_text}</a></p>'
                    )
                    if me.get("body_html"):
                        widget_html = (
                            f'{widget_logo_header}'
                            f'<h1 style="text-align:center;color:#1a1a1a;font-size:28px;line-height:1.2;">'
                            f'{me["subject"]}</h1>'
                            f'{me["body_html"]}'
                            f'{widget_cta_html}'
                        )
                    else:
                        steps = me.get("steps") or [
                            {"timing": "Within 1 hour", "detail": "We confirm your details."},
                            {"timing": "Within 24 hours", "detail": "You receive a personalized proposal."},
                            {"timing": "Next step", "detail": "Hand-off to your dedicated rep."},
                        ]
                        steps_html = "".join(
                            f'<li><strong>{s.get("timing", "Next")}:</strong> {s.get("detail", "")}</li>'
                            for s in steps
                        )
                        widget_html = (
                            f'{widget_logo_header}'
                            f'<h1 style="text-align:center;color:#1a1a1a;font-size:28px;line-height:1.2;">'
                            f'{me["subject"]}</h1>'
                            f'<p style="font-size:16px;line-height:1.6;color:#1a1a1a;">'
                            f'Hi {{{{contact.firstname}}}}, thanks for getting in touch with {company_name}. '
                            f"Here's what happens next:</p>"
                            f'<ol style="font-size:15px;line-height:1.65;color:#333;">'
                            f'{steps_html}'
                            f'</ol>'
                            f'<p style="text-align:center;margin-top:24px;">'
                            f'<a href="{cta_url}" '
                            f'style="display:inline-block;background:{cta_color};color:#fff;padding:14px 28px;'
                            f'border-radius:6px;text-decoration:none;font-weight:600;">{cta_text}</a></p>'
                        )
                    wbody["html"] = widget_html
            body = {
                "name": me["name"], "subject": me["subject"],
                "fromName": me.get("from_name", company_name),
                "state": "DRAFT",
                "businessUnitId": bu_id,
                "subscription": {"name": "Marketing Information"},
                "content": {
                    "templatePath": content.get("templatePath", "@hubspot/email/dnd/welcome_3.html"),
                    "widgets": widgets,
                    "flexAreas": content.get("flexAreas", {}),
                    "styleSettings": content.get("styleSettings", {}),
                },
            }

        s, r = self.client.request("POST", "/marketing/v3/emails", body)
        if self.client.is_ok(s):
            email_id = r.get("id")
            self.manifest["marketing_email"]["id"] = email_id
            self.manifest["marketing_email"]["name"] = me["name"]
            self.manifest["marketing_email"]["url"] = self.url("email", self.portal, "edit", str(email_id), "edit/content")
            self.manifest["marketing_email"]["hero_image_url"] = hubspot_image_url
            ok(f"marketing email → {email_id} (with AI hero image, in HubSpot)")
        else:
            warn(f"marketing email API: {s} {str(r)[:300]}")
            self.add_error("marketing_email.create", s, r)
            self.add_manual_step(
                "Marketing email", self.url("email", self.portal, "manage/state/all"),
                f"Create email '{me['name']}' with the saved branded HTML at {email_html_path}.",
                f"API returned {s}",
            )

    # ---- Phase 11: Workflows (correct v4 body shape) ----

    def workflows(self) -> None:
        # Strategy: API-first creates the workflow with every action it can
        # (set_property uses actionTypeId 0-2; delay uses 0-1). Actions the
        # v4 flows API can't express (send email, AI step, complex branching)
        # are recorded as manual_step gaps. The Playwright phase later opens
        # API-created workflows and appends the gap actions in the UI.
        # If the API call fails entirely, Playwright create_workflow falls
        # back to building the whole workflow via UI.
        if not self.plan.get("workflows"):
            return
        log("Phase 11: Workflows (v4)")
        for wf in self.plan["workflows"]:
            actions = []
            gaps = []
            next_id = 1
            for i, step in enumerate(wf.get("steps", [])):
                aid = str(next_id)
                next_id += 1
                next_action = str(next_id) if i + 1 < len(wf["steps"]) else None
                connection = {"edgeType": "STANDARD", "nextActionId": next_action} if next_action else None

                if step["type"] == "set_property":
                    actions.append({
                        "type": "SINGLE_CONNECTION",
                        "actionId": aid,
                        "actionTypeVersion": 0,
                        "actionTypeId": "0-2",  # Set Property action (v4 flows)
                        **({"connection": connection} if connection else {}),
                        "fields": {
                            "property_name": step["property"],
                            "association": {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 1},
                            "value": {"staticValue": step["value"]},
                        },
                    })
                elif step["type"] == "delay":
                    actions.append({
                        "type": "SINGLE_CONNECTION",
                        "actionId": aid,
                        "actionTypeVersion": 0,
                        "actionTypeId": "0-1",
                        **({"connection": connection} if connection else {}),
                        "fields": {"delta": step.get("seconds", 86400), "time_unit": "SECONDS"},
                    })
                else:
                    gaps.append({"step_index": i, "type": step["type"], "description": step.get("description", "")})

            body = {
                "type": "CONTACT_FLOW",
                "name": wf["name"],
                "isEnabled": False,
                "objectTypeId": "0-1",
                "flowType": "WORKFLOW",
                "actions": actions,
                "startActionId": actions[0]["actionId"] if actions else None,
                "nextAvailableActionId": str(next_id),
                "enrollmentCriteria": {
                    "shouldReEnroll": False,
                    "type": "EVENT_BASED",
                    "listFilterBranch": {
                        "filterBranchType": "OR",
                        "filters": [],
                        "filterBranches": [],
                        "filterBranchOperator": "OR",
                    },
                    "unEnrollObjectsNotMeetingCriteria": False,
                },
            }
            s, r = self.client.request("POST", "/automation/v4/flows", body)
            if self.client.is_ok(s):
                flow_id = r.get("id") or r.get("flowId")
                self.manifest["workflows"][wf["name"]] = flow_id
                self.manifest["workflow_urls"][wf["name"]] = self.url("workflows", self.portal, "platform/flow", str(flow_id), "edit")
                ok(f"workflow {wf['name']} → {flow_id}")
            else:
                warn(f"workflow {wf['name']}: {s} {str(r)[:300]}")
                self.add_error(f"workflow.create:{wf['name']}", s, r)
                # Fix F: send the rep to the workflow CREATE page, pre-tagged
                # with the planned name. The doc generator prefers
                # manifest["workflow_urls"][name] when set, so this fallback
                # only fires when the API call also failed entirely.
                create_url = (
                    f"{self.url('workflows', self.portal)}/create?source=demo-prep"
                    f"&template={urllib.parse.quote(wf['name'])}"
                )
                self.add_manual_step(
                    f"Workflow: {wf['name']}", create_url,
                    f"Build via UI. Steps: " + " → ".join([s["type"] for s in wf.get("steps", [])]),
                    f"API returned {s}",
                )

            for gap in gaps:
                wid = self.manifest["workflows"].get(wf["name"], "")
                if wid:
                    gap_url = self.url("workflows", self.portal, "platform/flow", str(wid), "edit")
                else:
                    gap_url = (
                        f"{self.url('workflows', self.portal)}/create?source=demo-prep"
                        f"&template={urllib.parse.quote(wf['name'])}"
                    )
                self.add_manual_step(
                    f"Add {gap['type']} action to '{wf['name']}'",
                    gap_url,
                    gap["description"] or f"Add {gap['type']} action at step {gap['step_index']}",
                    # Public reason already polished. Internal_reason on the
                    # manual_step still records the v4 limitation for debugging.
                    f"v4 flows API: {gap['type']} action requires UI build",
                )

    # ---- Phase 12: Sales Workspace Leads (object 0-136) ----

    def create_leads(self) -> None:
        """Create one lead per contact in Sales Workspace. Sales Hub Pro+
        gated — degrade gracefully on 403/404."""
        if not self.manifest["contacts"]:
            return
        log("Phase 12: Sales Workspace leads (0-136)")

        # Pre-flight: ensure demo_customer property exists on the leads object.
        # The Properties endpoint takes the friendly name "leads", not the type id "0-136".
        # The leads object's default group name varies by portal — discover it via GET first.
        skip_demo_customer = False
        group_name = None
        sg, rg = self.client.request("GET", "/crm/v3/properties/leads/groups")
        if self.client.is_ok(sg):
            groups = rg.get("results", []) or []
            preferred = ("leadinformation", "lead_information", "leads_information")
            for g in groups:
                if g.get("name") in preferred:
                    group_name = g["name"]
                    break
            if not group_name and groups:
                # Fall back to the first group with a name; prefer non-hidden if the field exists.
                visible = [g for g in groups if not g.get("hidden", False)]
                pool = visible or groups
                for g in pool:
                    if g.get("name"):
                        group_name = g["name"]
                        break
        elif sg == 404:
            warn("leads object not available (404) — Sales Hub Pro+ required, skipping phase")
            self.add_manual_step(
                "Sales Workspace leads",
                f"https://app.hubspot.com/sales-workspace/{self.portal}",
                "Sales Hub Pro+ required for the Leads object. Create leads manually if needed.",
                "Sales Hub Pro+ required for Leads object",
            )
            return

        prop_body = {
            "name": "demo_customer", "label": "Demo Customer Slug",
            "type": "string", "fieldType": "text",
            "description": "Tags demo data created by hubspot-demo-prep skill.",
        }
        if group_name:
            prop_body["groupName"] = group_name
        s, r = self.client.request("POST", "/crm/v3/properties/leads", prop_body)
        if s == 409:
            pass  # already exists — fine
        elif s == 404:
            warn("leads object not available (404) — Sales Hub Pro+ required, skipping phase")
            self.add_manual_step(
                "Sales Workspace leads",
                f"https://app.hubspot.com/sales-workspace/{self.portal}",
                "Sales Hub Pro+ required for the Leads object. Create leads manually if needed.",
                "Sales Hub Pro+ required for Leads object",
            )
            return
        elif s == 403:
            warn("leads property pre-flight 403 — likely missing crm.schemas.leads.write scope on the private app token")
            self.add_error("lead.property.preflight", s, r)
            skip_demo_customer = True
        elif not self.client.is_ok(s):
            warn(f"leads property pre-flight {s} (group={group_name!r}); leads will be created without demo_customer tag")
            self.add_error("lead.property.preflight", s, r)
            skip_demo_customer = True
        else:
            ok(f"leads demo_customer property created (group={group_name or 'default'})")

        # Lead labels/sources/template come from plan["activity_content"] so we don't
        # leak Shipperz "auto transport inquiry" into every demo. Industry-neutral
        # defaults match the schema fallback table.
        ac = self.plan.get("activity_content", {}) or {}
        labels = ac.get("lead_labels") or ["WARM", "HOT", "COLD"]
        sources = ac.get("lead_sources") or ["Web form", "Inbound call",
                                             "LinkedIn outreach", "Referral",
                                             "Trade show", "Cold email"]
        lead_label_template = ac.get("lead_label_template") or "demo inquiry"
        contact_items = list(self.manifest["contacts"].items())  # [(email, id), ...]

        ok_count = 0
        sales_pro_blocked = False
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {}
            for email, cid in contact_items:
                name_prefix = email.split("@")[0].replace(".", " ").title()
                src = random.choice(sources)
                props = {
                    "hs_lead_name": f"{name_prefix} — {lead_label_template} ({src})",
                    "hs_lead_label": random.choice(labels),
                }
                if not skip_demo_customer:
                    props["demo_customer"] = self.slug
                body = {
                    "properties": props,
                    "associations": [{
                        "to": {"id": cid},
                        "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                   "associationTypeId": ASSOC["lead_to_contact"]}],
                    }],
                }
                fut = ex.submit(self.client.request, "POST",
                                "/crm/v3/objects/0-136", body)
                futures[fut] = body["properties"]["hs_lead_name"]
            for fut in as_completed(futures):
                s, r = fut.result()
                lead_name = futures[fut]
                if self.client.is_ok(s):
                    self.manifest["leads"][lead_name] = r.get("id")
                    ok_count += 1
                elif s in (403, 404):
                    sales_pro_blocked = True
                else:
                    self.add_error(f"lead.create:{lead_name}", s, r)

        if sales_pro_blocked and not ok_count:
            self.add_manual_step(
                "Sales Workspace leads",
                f"https://app.hubspot.com/sales-workspace/{self.portal}",
                "Sales Hub Pro+ required for the Leads object.",
                "Sales Hub Pro+ required for Leads object",
            )
            return
        ok(f"leads: {ok_count}/{len(contact_items)}")

    # ---- Phase 13: Quotes (line items + branded template) ----

    def create_quotes(self) -> None:
        """For each deal, create 2-3 line items + one quote pinned to a portal
        quote template. Skips with manual_step if no template exists."""
        if not self.manifest.get("deals"):
            return
        log("Phase 13: Quotes (line items + branded template)")

        # Pre-flight: find an existing quote_template
        s, r = self.client.request("GET", "/crm/v3/objects/quote_templates",
                                   query={"limit": 1})
        template_id = None
        if self.client.is_ok(s):
            results = r.get("results", [])
            if results:
                template_id = results[0].get("id")
        if not template_id:
            warn("no quote template found — skipping quotes phase")
            self.add_manual_step(
                "Quote template",
                self.url("settings", self.portal, "sales/quote-templates"),
                "Create at least one quote template in Sales > Quotes > Templates, then re-run.",
                "No quote template found in portal; create one in Sales > Quotes > Templates",
            )
            return
        self.manifest["quote_template_id"] = template_id
        ok(f"using quote template {template_id}")

        # Ensure demo_customer property exists on line_items + quotes
        for obj, group in [("line_items", "lineiteminformation"),
                           ("quotes", "quoteinformation")]:
            body = {"name": "demo_customer", "label": "Demo Customer Slug",
                    "type": "string", "fieldType": "text", "groupName": group,
                    "description": "Tags demo data created by hubspot-demo-prep skill."}
            self.client.request("POST", f"/crm/v3/properties/{obj}", body)

        # Quote line-item catalog. The plan can supply industry-specific items via
        # plan["quote_catalog"]; otherwise fall back to a neutral 5-item catalog
        # (per plan-schema.md). The legacy hardcoded "Enclosed transport — coast to
        # coast" leaked Shipperz vocabulary into every demo.
        catalog = self.plan.get("quote_catalog") or [
            {"name": "Initial consultation", "price": "250"},
            {"name": "Standard service tier", "price": "850"},
            {"name": "Premium service tier", "price": "2400"},
            {"name": "Premium add-on", "price": "450"},
            {"name": "Extended support", "price": "150"},
        ]

        deal_items = list(self.manifest["deals"].items())
        contact_ids = list(self.manifest["contacts"].values())

        for i, (deal_name, deal_id) in enumerate(deal_items):
            # 1) Create 2-3 line items. Clamp n_items to catalog size — the
            # plan can supply a tiny industry-specific catalog (e.g. 1 SKU) and
            # random.sample(catalog, n) raises ValueError when n > len(catalog).
            if not catalog:
                warn(f"quote catalog empty; skipping {deal_name}")
                continue
            n_items = min(random.randint(2, 3), len(catalog))
            picks = random.sample(catalog, n_items)
            li_ids = []
            for li in picks:
                li_body = {"properties": {
                    "name": li["name"], "price": li["price"],
                    "quantity": "1", "demo_customer": self.slug,
                }}
                s, r = self.client.request("POST", "/crm/v3/objects/line_items", li_body)
                if self.client.is_ok(s):
                    li_ids.append(r["id"])
                else:
                    self.add_error(f"line_item.create:{deal_name}", s, r)
            if not li_ids:
                warn(f"no line items for {deal_name}; skipping quote")
                continue
            self.manifest["line_items"][deal_id] = li_ids

            # 2) Create quote with all 4 association types
            contact_id = contact_ids[i % len(contact_ids)] if contact_ids else None
            associations = [
                {"to": {"id": deal_id},
                 "types": [{"associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": ASSOC["quote_to_deal"]}]},
                {"to": {"id": template_id},
                 "types": [{"associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": ASSOC["quote_to_template"]}]},
            ]
            if contact_id:
                associations.append({
                    "to": {"id": contact_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED",
                               "associationTypeId": ASSOC["quote_to_contact"]}],
                })
            for li_id in li_ids:
                associations.append({
                    "to": {"id": li_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED",
                               "associationTypeId": ASSOC["quote_to_line_item"]}],
                })

            q_body = {
                "properties": {
                    "hs_title": f"{deal_name} — Quote",
                    "hs_expiration_date": (datetime.date.today()
                                           + datetime.timedelta(days=30)).isoformat(),
                    "hs_currency": "USD",
                    "demo_customer": self.slug,
                },
                "associations": associations,
            }
            s, r = self.client.request("POST", "/crm/v3/objects/quotes", q_body)
            if not self.client.is_ok(s):
                warn(f"quote {deal_name}: {s}")
                self.add_error(f"quote.create:{deal_name}", s, r)
                continue
            quote_id = r["id"]
            self.manifest["quotes"][deal_name] = quote_id

            # 3) Approve so it's "ready to send"
            s2, _ = self.client.request("PATCH", f"/crm/v3/objects/quotes/{quote_id}",
                                        {"properties": {"hs_status": "APPROVAL_NOT_NEEDED"}})
            if self.client.is_ok(s2):
                ok(f"quote {deal_name} → {quote_id} (approved, {len(li_ids)} line items)")
            else:
                ok(f"quote {deal_name} → {quote_id} (DRAFT — approval PATCH returned {s2})")

    # ---- Phase 14: Invoices ----

    def create_invoices(self) -> None:
        """Create 2 invoices reusing line items: first deal = open (current),
        second deal = paid (backdated 30 days)."""
        if not self.manifest.get("line_items") or not self.manifest.get("deals"):
            return
        log("Phase 14: Invoices")

        # Ensure demo_customer property on invoices
        body = {"name": "demo_customer", "label": "Demo Customer Slug",
                "type": "string", "fieldType": "text",
                "groupName": "invoiceinformation",
                "description": "Tags demo data created by hubspot-demo-prep skill."}
        self.client.request("POST", "/crm/v3/properties/invoices", body)

        deal_items = list(self.manifest["deals"].items())[:2]
        if not deal_items:
            return
        contact_ids = list(self.manifest["contacts"].values())

        inputs = []
        meta: list[tuple[str, str]] = []  # [(deal_name, status), ...]
        for idx, (deal_name, deal_id) in enumerate(deal_items):
            li_ids = self.manifest["line_items"].get(deal_id, [])
            if not li_ids:
                continue
            if idx == 0:
                inv_date = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                due_date = (datetime.datetime.utcnow()
                            + datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
                status = "open"
            else:
                inv_date = (datetime.datetime.utcnow()
                            - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
                due_date = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                status = "paid"

            contact_id = contact_ids[idx % len(contact_ids)] if contact_ids else None
            associations = []
            if contact_id:
                associations.append({
                    "to": {"id": contact_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED",
                               "associationTypeId": ASSOC["invoice_to_contact"]}],
                })
            for li_id in li_ids:
                associations.append({
                    "to": {"id": li_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED",
                               "associationTypeId": ASSOC["invoice_to_line_item"]}],
                })
            inputs.append({
                "properties": {
                    "hs_currency": "USD",
                    "hs_invoice_date": inv_date,
                    "hs_due_date": due_date,
                    "demo_customer": self.slug,
                },
                "associations": associations,
            })
            meta.append((deal_name, status))

        if not inputs:
            return

        s, r = self.client.request("POST", "/crm/v3/objects/invoices/batch/create",
                                   {"inputs": inputs})
        if not self.client.is_ok(s):
            warn(f"invoice batch create: {s}")
            self.add_error("invoice.batch_create", s, r)
            self.add_manual_step(
                "Invoices",
                self.url("contacts", self.portal, "objects/0-53/views/all/list"),
                "Batch invoice creation failed; create manually from the deals.",
                f"API returned {s}",
            )
            return

        results = r.get("results", [])
        for (deal_name, status), inv in zip(meta, results):
            inv_id = inv.get("id")
            if not inv_id:
                continue
            self.manifest["invoices"][deal_name] = inv_id
            s2, _ = self.client.request(
                "PATCH", f"/crm/v3/objects/invoices/{inv_id}",
                {"properties": {"hs_invoice_status": status}})
            if self.client.is_ok(s2):
                ok(f"invoice {deal_name} → {inv_id} ({status})")
            else:
                ok(f"invoice {deal_name} → {inv_id} (DRAFT — status PATCH returned {s2})")

    # ---- Phase 15: Calculation property + property group ----

    def _regroup_property_to_match(self, object_type: str, prop_name: str,
                                   expected_group: str) -> bool:
        """GET the existing property, compare groupName, PATCH if different.

        Eliminates cross-prospect contamination: when a property exists from a
        prior prospect's run, its groupName is whatever that prospect used
        (e.g. `shipperz_demo_properties`). Without this PATCH, subsequent
        prospects silently inherit the leaked group name. Caught by verify on
        2026-04-27.

        Returns True if the property is now correctly grouped (either it
        already was, or the PATCH succeeded). False on any failure — caller
        adds a manual step.
        """
        sg, rg = self.client.request(
            "GET", f"/crm/v3/properties/{object_type}/{prop_name}")
        if not self.client.is_ok(sg):
            warn(f"  regroup {object_type}.{prop_name}: GET {sg} {str(rg)[:200]}")
            self.add_manual_step(
                f"{object_type}.{prop_name} groupName",
                self.url("contacts", self.portal, "property-settings"),
                f"Verify {prop_name} is in group {expected_group!r}",
                f"GET returned {sg}",
            )
            return False
        current_group = (rg.get("groupName") or "").strip()
        if current_group == expected_group:
            ok(f"  {object_type}.{prop_name} already in group {expected_group}")
            return True
        sp, rp = self.client.request(
            "PATCH", f"/crm/v3/properties/{object_type}/{prop_name}",
            {"groupName": expected_group})
        if self.client.is_ok(sp):
            log(f"  ✓ Phase 15: PATCHed {prop_name} groupName from "
                f"{current_group!r} → {expected_group!r} (cross-prospect contamination)")
            return True
        warn(f"  regroup {object_type}.{prop_name}: PATCH {sp} {str(rp)[:200]}")
        self.add_manual_step(
            f"{object_type}.{prop_name} groupName",
            self.url("contacts", self.portal, "property-settings"),
            f"PATCH {prop_name} groupName from {current_group!r} to {expected_group!r}",
            f"PATCH returned {sp}",
        )
        return False

    def create_calc_property_and_group(self) -> None:
        """Create the demo property group on deals, register `deal_age_days` as
        a plain number property (not a calculated one — HubSpot's
        calculation_equation grammar has no NOW() function and time-since via
        API is poorly documented), then backfill realistic per-deal values."""
        log("Phase 15: Property group + deal_age_days backfill")
        # Industry-neutral defaults so the property admin doesn't show "Shipperz Demo"
        # for every prospect. Plan["property_group"] overrides when present.
        company_label = (self.manifest.get("company") or {}).get("name") or self.slug
        pg = self.plan.get("property_group", {}) or {}
        group_name = pg.get("name", f"{self.slug}_demo_properties")
        group_label = pg.get("label", f"Demo ({company_label})")

        # 1) Create or reuse the group
        body = {"name": group_name, "label": group_label, "displayOrder": 1}
        s, r = self.client.request("POST", "/crm/v3/properties/deals/groups", body)
        if s == 409:
            ok(f"property group {group_name} already exists; reusing")
        elif self.client.is_ok(s):
            ok(f"property group {group_name} created")
        else:
            warn(f"property group: {s}")
            self.add_error("property_group.create", s, r)

        # 2) Static number property: deal_age_days. Populated per-deal below.
        prop_body = {
            "name": "deal_age_days",
            "label": "Deal Age (days)",
            "type": "number",
            "fieldType": "number",
            "groupName": group_name,
            "description": "Days since the deal was created (demo-populated; not a live calc).",
        }
        s, r = self.client.request("POST", "/crm/v3/properties/deals", prop_body)
        if self.client.is_ok(s):
            self.manifest["calc_property"] = {
                "name": "deal_age_days", "group": group_name,
            }
            ok(f"deal_age_days property → {group_name}")
        elif s == 409:
            # 409 = property already exists from a prior prospect's run on the
            # same sandbox. The previous version skipped silently — meaning the
            # earlier prospect's groupName (e.g. `shipperz_demo_properties`)
            # leaked into every subsequent prospect's manifest. Cross-prospect
            # contamination, caught by verify on 2026-04-27.
            #
            # Fix: GET the existing property, compare groupName, and PATCH if
            # different. This is the same regroup pattern used for
            # `demo_customer` below — extended to deal_age_days.
            self._regroup_property_to_match("deals", "deal_age_days", group_name)
            self.manifest["calc_property"] = {
                "name": "deal_age_days", "group": group_name,
            }
        else:
            warn(f"deal_age_days property: {s} {str(r)[:200]}")
            self.add_error("calc_property.create", s, r)
            self.add_manual_step(
                "deal_age_days property",
                self.url("contacts", self.portal, "property-settings/0-3"),
                f"Create the deal_age_days property under group {group_name!r}",
                f"POST /crm/v3/properties/deals returned {s}: {str(r)[:200]}",
            )

        # 3) Backfill: each deal gets a plausible age (0-90 days).
        deal_ids = list(self.manifest.get("deals", {}).values())
        if deal_ids:
            with ThreadPoolExecutor(max_workers=5) as ex:
                futures = []
                for did in deal_ids:
                    age = random.randint(2, 90)
                    futures.append(ex.submit(
                        self.client.request, "PATCH", f"/crm/v3/objects/deals/{did}",
                        {"properties": {"deal_age_days": str(age)}}))
                ok_count = sum(1 for f in as_completed(futures) if self.client.is_ok(f.result()[0]))
            ok(f"deal_age_days backfilled: {ok_count}/{len(deal_ids)}")

        # 3) Re-group existing demo property on deals
        for prop_name in ("demo_customer",):
            patch_body = {"groupName": group_name}
            s, _ = self.client.request("PATCH",
                                       f"/crm/v3/properties/deals/{prop_name}",
                                       patch_body)
            if self.client.is_ok(s):
                ok(f"  re-grouped deals.{prop_name} → {group_name}")
            else:
                warn(f"  regroup deals.{prop_name}: {s}")

    # ---- Phase 16: Marketing campaign ----

    def _sanitize_campaign_name(self, raw_name: Any, fallback: str) -> str:
        campaign_name = re.sub(r"[()\[\]{}<>]", "", str(raw_name or fallback))
        campaign_name = re.sub(r"\s+", " ", campaign_name).strip()[:250]
        return campaign_name or fallback[:250]

    def _sanitize_utm_campaign(self, raw_utm: Any, fallback_utm: str) -> str:
        fallback = re.sub(r"[^a-z0-9-]+", "-", fallback_utm.lower()).strip("-")
        return (
            re.sub(r"[^a-z0-9-]+", "-", str(raw_utm or fallback).lower().strip())
            .strip("-")[:120]
            or fallback
        )

    def _create_or_reuse_campaign_record(
        self,
        *,
        campaign_name: str,
        start_date: str,
        end_date: str,
        notes: str,
        audience: str,
        utm_campaign: str,
        where: str = "campaign",
    ) -> tuple[str, str] | None:
        body = {"properties": {
            "hs_name": campaign_name,
            "hs_start_date": start_date,
            "hs_end_date": end_date,
            "hs_notes": notes,
            "hs_audience": audience,
            "hs_currency_code": "USD",
            "hs_campaign_status": "in_progress",
        }}

        s, r = self.client.request("POST", "/marketing/v3/campaigns", body)
        if s in (401, 403):
            warn(f"{where} blocked ({s}) — likely missing marketing.campaigns.write")
            self.add_manual_step(
                "Marketing campaign",
                self.url("marketing", self.portal, "campaigns"),
                f"Create campaign {campaign_name!r} manually and associate the marketing email + form.",
                "Token missing marketing.campaigns.write scope (enforced 2026-07-09)",
            )
            return None
        if s == 409 or (s == 400 and "already exist" in str(r).lower()):
            sl, rl = self.client.request("GET", "/marketing/v3/campaigns",
                                         query={"limit": 100, "name": campaign_name})
            existing = None
            if self.client.is_ok(sl):
                results = rl.get("results", []) or []
                if rl.get("total") == 1 and results:
                    existing = results[0]
                else:
                    for c in results:
                        cname = (c.get("properties") or {}).get("hs_name") or c.get("name")
                        if cname == campaign_name:
                            existing = c
                            break
            if existing:
                r = existing
                ok(f"campaign reused (already existed): {campaign_name!r}")
            else:
                warn(f"{where} create 409 but lookup failed: {str(rl)[:200]}")
                self.add_error(f"{where}.create", s, r)
                return None
        elif not self.client.is_ok(s):
            warn(f"{where} create: {s} {str(r)[:200]}")
            self.add_error(f"{where}.create", s, r)
            return None

        campaign_guid = r.get("id") or r.get("hs_object_id") or r.get("campaignGuid")
        if not campaign_guid:
            warn(f"{where}: no GUID in response: {str(r)[:200]}")
            self.add_error(f"{where}.create", s, r)
            return None

        if utm_campaign:
            su, ru = self.client.request(
                "PATCH",
                f"/marketing/v3/campaigns/{campaign_guid}",
                {"properties": {"hs_utm": utm_campaign}},
            )
            if self.client.is_ok(su):
                ok(f"campaign UTM → {utm_campaign}")
            else:
                warn(f"campaign UTM patch: {su} {str(ru)[:200]}")
                self.add_error(f"{where}.utm", su, ru)
        return str(campaign_guid), campaign_name

    def _link_assets_to_campaign(self, campaign_guid: str) -> tuple[int, int]:
        assets_to_link: list[tuple[str, str]] = []
        email_id = self.manifest.get("marketing_email", {}).get("id")
        if email_id:
            assets_to_link.append(("MARKETING_EMAIL", str(email_id)))
        for _, form_guid in (self.manifest.get("forms") or {}).items():
            assets_to_link.append(("FORM", form_guid))
        list_id = self.manifest.get("lead_scoring", {}).get("list_id")
        if list_id:
            assets_to_link.append(("OBJECT_LIST", str(list_id)))

        linked = 0
        for asset_type, asset_id in assets_to_link:
            if not asset_id:
                continue
            s2, r2 = self.client.request(
                "PUT",
                f"/marketing/v3/campaigns/{campaign_guid}/assets/{asset_type}/{asset_id}",
            )
            if self.client.is_ok(s2):
                linked += 1
                ok(f"  linked {asset_type}/{asset_id}")
            else:
                warn(f"  link {asset_type}/{asset_id}: {s2}")
                self.add_error(f"campaign.link:{asset_type}", s2, r2)
        return linked, len(assets_to_link)

    def create_marketing_campaign(self) -> None:
        """Create Marketing Campaign(s) and associate existing assets.

        Demo mode creates the normal single campaign. Feature Showcase
        attribution plans can request multiple campaigns so first-touch,
        last-touch, and influenced paths have real campaign records.
        """
        log("Phase 16: Marketing campaign")
        company_name = self.manifest["company"].get("name", "Demo")
        mc = self.plan.get("marketing_campaign") or {}
        today = datetime.date.today()
        quarter = f"Q{((today.month - 1) // 3) + 1} {today.year}"
        default_utm = f"{self.slug}_{quarter.lower().replace(' ', '_')}"
        fallback_name = f"{company_name} {quarter} Campaign"

        campaign_name = self._sanitize_campaign_name(mc.get("name"), fallback_name)
        start_date = mc.get("start_date", today.isoformat())
        end_date = mc.get("end_date",
                          (today + datetime.timedelta(days=90)).isoformat())
        notes = mc.get("notes", "Quarterly nurture campaign.")
        audience = mc.get("audience", "Active prospects.")
        utm_campaign = self._sanitize_utm_campaign(mc.get("utm_campaign"), default_utm)

        result = self._create_or_reuse_campaign_record(
            campaign_name=campaign_name,
            start_date=start_date,
            end_date=end_date,
            notes=notes,
            audience=audience,
            utm_campaign=utm_campaign,
            where="campaign",
        )
        if not result:
            return

        campaign_guid, campaign_name = result
        campaign_url = self.url("marketing", self.portal, "campaigns/details", campaign_guid)
        self.manifest["campaign_id"] = campaign_guid
        self.manifest["campaign_url"] = campaign_url
        self.manifest.setdefault("campaigns", {})[campaign_name] = {
            "id": campaign_guid,
            "url": campaign_url,
            "utm_campaign": utm_campaign,
            "role": "primary",
            "source": mc.get("source") or "",
        }
        ok(f"campaign → {campaign_guid}")

        linked, total = self._link_assets_to_campaign(campaign_guid)
        ok(f"campaign assets linked: {linked}/{total}")

        # Feature Showcase mode: Jordan-style attribution stories need more
        # than one campaign record so first-touch, last-touch, and influenced
        # paths do not all collapse into the same bucket.
        showcase = self.plan.get("campaign_attribution_showcase") or {}
        seen_campaign_ids = {campaign_guid}
        for i, extra in enumerate(showcase.get("campaigns") or [], 1):
            if not isinstance(extra, dict) or not extra.get("name"):
                continue
            extra_name = self._sanitize_campaign_name(
                extra.get("name"),
                f"{company_name} Attribution Campaign {i}",
            )
            if extra_name == campaign_name:
                continue
            extra_utm = self._sanitize_utm_campaign(
                extra.get("utm_campaign"),
                f"{self.slug}_{extra_name}",
            )
            extra_result = self._create_or_reuse_campaign_record(
                campaign_name=extra_name,
                start_date=extra.get("start_date") or start_date,
                end_date=extra.get("end_date") or end_date,
                notes=extra.get("notes") or f"Attribution showcase campaign: {extra_name}",
                audience=extra.get("audience") or audience,
                utm_campaign=extra_utm,
                where="campaign_attribution",
            )
            if not extra_result:
                continue
            extra_guid, extra_name = extra_result
            extra_url = self.url("marketing", self.portal, "campaigns/details", extra_guid)
            self.manifest.setdefault("campaigns", {})[extra_name] = {
                "id": extra_guid,
                "url": extra_url,
                "utm_campaign": extra_utm,
                "role": extra.get("role") or "",
                "source": extra.get("source") or "",
            }
            if extra_guid not in seen_campaign_ids:
                seen_campaign_ids.add(extra_guid)
                linked, total = self._link_assets_to_campaign(extra_guid)
                ok(f"campaign attribution assets linked for {extra_name}: {linked}/{total}")

    # ---- Phase 17: Reports & dashboards (v0.4) ----

    def create_reports_and_dashboards(self) -> None:
        """Build v0.4 report bundles via Playwright, or record an honest block.

        HubSpot has no public reports/dashboards creation API. This phase is
        therefore UI-only. Until the live selector capture lands in
        `playwright_phases_extras.create_reports_and_dashboards`, the builder
        records a concrete manual step and a machine-readable blocked status so
        the demo doc and verifiers cannot silently imply dashboards exist.
        """
        reports_plan = self.plan.get("playwright_reports") or {}
        dashboards_plan = reports_plan.get("dashboards") or []
        if not dashboards_plan:
            return

        log("Phase 17: Reports & dashboards (v0.4)")
        self.manifest.setdefault("reports", {})
        self.manifest.setdefault("dashboards_v04", {})
        self.manifest["reports_status"] = {
            "status": "started",
            "planned_dashboard_count": len(dashboards_plan),
            "planned_report_count": sum(
                len(d.get("reports") or []) for d in dashboards_plan
            ),
            "sandbox_tier": self.manifest.get("sandbox_tier") or self.probe_sandbox_tier(),
        }

        if (
            not PLAYWRIGHT_EXTRAS_AVAILABLE
            or not hasattr(playwright_phases_extras, "create_reports_and_dashboards")
        ):
            reason = (
                "create_reports_and_dashboards is not implemented in "
                "playwright_phases_extras.py; live HubSpot selectors still need "
                "a headed dry-run capture."
            )
            self.manifest["reports_status"].update({
                "status": "blocked",
                "reason": reason,
            })
            self.add_error("reports.create", 0, reason)
            self.add_manual_step(
                "Reports & dashboards",
                self.url("reports-dashboard", self.portal),
                (
                    "Create the planned v0.4 dashboard bundle from build-plan.json. "
                    "Use the dashboard names, audience labels, report list, "
                    "visualization types, and tier substitutions recorded there; "
                    "then paste dashboard URLs into manifest.dashboards_v04."
                ),
                "Configured in UI for high-quality dashboard layout control.",
            )
            warn("reports phase blocked: Playwright report builder not implemented")
            return

        try:
            result = playwright_phases_extras.create_reports_and_dashboards(
                slug=self.slug,
                portal_id=self.portal,
                work_dir=self.work_dir,
                plan=reports_plan,
                manifest=self.manifest,
                sandbox_tier=self.manifest.get("sandbox_tier"),
            )
        except Exception as exc:  # noqa: BLE001
            reason = f"Playwright reports phase raised {type(exc).__name__}: {exc}"
            self.manifest["reports_status"].update({
                "status": "error",
                "reason": reason,
            })
            self.add_error("reports.create", 0, reason)
            warn(f"reports phase exception: {exc}")
            return

        if not isinstance(result, dict):
            self.manifest["reports_status"].update({
                "status": "error",
                "reason": "Playwright reports phase returned no structured result.",
            })
            self.add_error("reports.create", 0, "unstructured Playwright reports result")
            return

        self.manifest["dashboards_v04"].update(result.get("dashboards_v04") or {})
        self.manifest["reports"].update(result.get("reports") or {})
        for ms in result.get("manual_steps") or []:
            self.add_manual_step(
                item=ms.get("item", "Reports & dashboards"),
                ui_url=ms.get("ui_url", self.url("reports-dashboard", self.portal)),
                instructions=ms.get("instructions", ""),
                reason=ms.get("reason", "Configured in UI for high-quality dashboard layout control."),
            )
        status = result.get("status") or (
            "ok" if self.manifest.get("dashboards_v04") else "error"
        )
        self.manifest["reports_status"].update({
            "status": status,
            "reason": result.get("reason"),
            "built_dashboard_count": len(self.manifest.get("dashboards_v04") or {}),
            "built_report_count": len(self.manifest.get("reports") or {}),
        })
        ok(
            f"reports dashboards: {len(self.manifest.get('dashboards_v04') or {})}/"
            f"{len(dashboards_plan)} dashboard(s)"
        )

    # ---- Output ----

    def _resolve_doc_replacement_id(self) -> str | None:
        """Resolve the Google Doc id to overwrite (if any). SECURITY-CRITICAL:
        every override path requires explicit per-prospect opt-in so a stale
        env var or plan field from another run can never overwrite the wrong
        prospect's doc.

        Two opt-in paths:
        1. Env: HUBSPOT_DEMOPREP_LOCKED_DOC_ID is honored ONLY when
           HUBSPOT_DEMOPREP_LOCKED_DOC_SLUG matches self.slug.
        2. Plan: plan["doc_replacement_id"] is honored ONLY when
           plan["doc_replacement_acknowledged_slug"] matches self.slug.
        Logs every overwrite decision so a regression is visible in the
        transcript.
        """
        # Env path
        env_id = self.env.get("HUBSPOT_DEMOPREP_LOCKED_DOC_ID")
        env_slug = self.env.get("HUBSPOT_DEMOPREP_LOCKED_DOC_SLUG")
        if env_id:
            if env_slug == self.slug:
                warn(f"WARN: Replacing existing Drive doc {env_id} per env opt-in (slug={self.slug})")
                return env_id
            else:
                warn(
                    f"HUBSPOT_DEMOPREP_LOCKED_DOC_ID set ({env_id}) but "
                    f"HUBSPOT_DEMOPREP_LOCKED_DOC_SLUG={env_slug!r} does not match "
                    f"current slug={self.slug!r}; ignoring."
                )

        # Plan path
        plan_id = self.plan.get("doc_replacement_id")
        plan_ack = self.plan.get("doc_replacement_acknowledged_slug")
        if plan_id:
            if plan_ack == self.slug:
                warn(f"WARN: Replacing existing Drive doc {plan_id} per plan opt-in (slug={self.slug})")
                return plan_id
            else:
                warn(
                    f"plan['doc_replacement_id']={plan_id} present but "
                    f"plan['doc_replacement_acknowledged_slug']={plan_ack!r} does not match "
                    f"current slug={self.slug!r}; ignoring (no overwrite)."
                )
        return None

    def generate_doc(self) -> dict:
        """Build the .docx demo/showcase runbook locally only. Drive upload is a
        separate step (`upload_doc_to_drive`) so verifiers can inspect the
        local file before the doc lands in front of the prospect."""
        from doc_generator import generate_docx
        mode = str(self.plan.get("mode") or "demo").strip().lower().replace("-", "_")
        doc_kind = "feature showcase doc" if mode in {"feature", "showcase", "feature_showcase"} else "demo doc"
        log(f"Phase 17: Generate {doc_kind} (local .docx)")
        docx_path = generate_docx(self.manifest, self.research, self.plan,
                                  slug=self.slug, work_dir=self.work_dir,
                                  portal=self.portal)
        self.manifest["demo_doc"] = {
            "docx_path": docx_path,
            # Drive fields populated later by upload_doc_to_drive().
            "gdoc_url": None,
            "doc_id": None,
            "pdf_path": None,
        }
        ok(f"{doc_kind} (local) → {docx_path}")
        return self.manifest["demo_doc"]

    def upload_doc_to_drive(self) -> dict:
        """Upload the locally-generated .docx to Google Drive. Runs AFTER
        verify_doc_urls so a broken-link doc never lands in front of the
        prospect."""
        from doc_generator import upload_to_drive
        demo_doc = self.manifest.get("demo_doc") or {}
        docx_path = demo_doc.get("docx_path")
        if not docx_path or not os.path.exists(docx_path):
            warn("upload_doc_to_drive: no local .docx to upload")
            return demo_doc

        company_name = (self.plan.get("company") or {}).get("name") or self.slug
        mode = str(self.plan.get("mode") or "demo").strip().lower().replace("-", "_")
        title_prefix = "HubSpot Feature Showcase" if mode in {"feature", "showcase", "feature_showcase"} else "HubSpot Demo Prep"
        title = f"{title_prefix} · {company_name}"
        replace_doc_id = self._resolve_doc_replacement_id()

        upload = upload_to_drive(docx_path, doc_title=title,
                                 replace_doc_id=replace_doc_id)
        demo_doc.update({
            "gdoc_url": upload.get("gdoc_url"),
            "doc_id": upload.get("doc_id"),
            "pdf_path": upload.get("pdf_path"),
        })
        self.manifest["demo_doc"] = demo_doc
        # Also persist into manifest["output"]["doc_url"] so downstream
        # consumers (and the verify-agent expectation) can read a single
        # canonical location. Previously this key was never set — the URL was
        # printed to stdout but only stored under demo_doc.gdoc_url. Fix #5.
        drive_url = upload.get("gdoc_url")
        if drive_url:
            self.manifest.setdefault("output", {})["doc_url"] = drive_url
            ok(f"demo doc → {drive_url}")
        else:
            ok(f"demo doc → {docx_path} (Drive upload skipped)")
        return demo_doc

    # ---- Verification loop ----
    # After each create_* phase, GET back at least one representative artifact
    # and confirm key fields are populated. If verification fails AND the phase
    # produced no artifacts at all, re-run the create once. Final result lands
    # in manifest["verifications"][<phase>] so the demo doc renders [NOT_BUILT]
    # for any phase that didn't actually land in HubSpot.

    def _record_verify(self, name: str, verified: bool, retried: bool, message: str) -> None:
        self.manifest["verifications"][name] = {
            "verified": verified, "retried": retried, "message": message,
        }
        if verified:
            ok(f"verify {name}: {message}")
        else:
            warn(f"verify {name} FAILED ({'retried' if retried else 'no retry'}): {message}")

    def _run_with_verify(self, name: str, create_fn, verify_fn, *,
                         is_empty_fn=None) -> None:
        """Run a create phase, then verify. Retry once if verify fails AND nothing
        was created (avoids duplicates from partially successful phases).

        verify_fn returns (verified: bool, message: str). Returning verified=True with
        a "skipped" message indicates the phase had nothing to build per the plan.
        """
        try:
            create_fn()
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 — outer safety net
            self._record_verify(name, False, False, f"create raised {type(exc).__name__}: {exc}")
            return
        try:
            verified, msg = verify_fn()
        except Exception as exc:  # noqa: BLE001
            verified, msg = False, f"verify raised {type(exc).__name__}: {exc}"
        if verified:
            self._record_verify(name, True, False, msg)
            return
        empty_ok_to_retry = is_empty_fn is None or is_empty_fn()
        if not empty_ok_to_retry:
            self._record_verify(name, False, False,
                                f"{msg}; partial artifacts present, not retrying")
            return
        log(f"  ↻ retrying {name} (verify failed, nothing created yet)")
        try:
            create_fn()
            verified, msg = verify_fn()
        except Exception as exc:  # noqa: BLE001
            verified, msg = False, f"retry raised {type(exc).__name__}: {exc}"
        self._record_verify(name, verified, True, msg)

    def _get_first(self, mapping: dict):
        for v in (mapping or {}).values():
            return v
        return None

    def verify_company(self) -> tuple[bool, str]:
        cid = (self.manifest.get("company") or {}).get("id")
        if not cid:
            return False, "no company id in manifest"
        s, r = self.client.request("GET", f"/crm/v3/objects/companies/{cid}",
                                   query={"properties": "name,domain,industry"})
        if not self.client.is_ok(s):
            return False, f"GET company {cid} returned {s}"
        name = (r.get("properties") or {}).get("name")
        return (bool(name), f"company id={cid} name={name!r}")

    def verify_contacts(self) -> tuple[bool, str]:
        cid = self._get_first(self.manifest.get("contacts"))
        if not cid:
            return False, "no contacts in manifest"
        s, r = self.client.request("GET", f"/crm/v3/objects/contacts/{cid}",
                                   query={"properties": "email,firstname,lastname"})
        if not self.client.is_ok(s):
            return False, f"GET contact {cid} returned {s}"
        email = (r.get("properties") or {}).get("email")
        return (bool(email), f"{len(self.manifest['contacts'])} contacts (sample {email!r})")

    def verify_leads(self) -> tuple[bool, str]:
        leads = self.manifest.get("leads") or {}
        if not leads:
            # Sales Hub Pro+ gating may legitimately yield zero leads.
            if any(ms.get("item") == "Sales Workspace leads"
                   for ms in self.manifest.get("manual_steps", [])):
                return True, "skipped — Sales Hub gating logged as manual_step"
            return False, "no leads created"
        lid = self._get_first(leads)
        s, r = self.client.request("GET", f"/crm/v3/objects/0-136/{lid}",
                                   query={"properties": "hs_lead_name,hs_lead_label"})
        if not self.client.is_ok(s):
            return False, f"GET lead {lid} returned {s}"
        return True, f"{len(leads)} leads (sample {(r.get('properties') or {}).get('hs_lead_name')!r})"

    def verify_pipeline_and_deals(self) -> tuple[bool, str]:
        deals = self.manifest.get("deals") or {}
        if not deals:
            return False, "no deals created"
        did = self._get_first(deals)
        s, r = self.client.request("GET", f"/crm/v3/objects/deals/{did}",
                                   query={"properties": "dealname,amount,pipeline,dealstage"})
        if not self.client.is_ok(s):
            return False, f"GET deal {did} returned {s}"
        props = r.get("properties") or {}
        return (bool(props.get("dealname") and props.get("pipeline")),
                f"{len(deals)} deals on pipeline {props.get('pipeline')}")

    def verify_tickets(self) -> tuple[bool, str]:
        if not self.plan.get("tickets"):
            return True, "skipped — no tickets in plan"
        tickets = self.manifest.get("tickets") or {}
        if not tickets:
            return False, "tickets in plan but none created"
        tid = self._get_first(tickets)
        s, r = self.client.request("GET", f"/crm/v3/objects/tickets/{tid}",
                                   query={"properties": "subject,hs_pipeline_stage"})
        if not self.client.is_ok(s):
            return False, f"GET ticket {tid} returned {s}"
        return True, f"{len(tickets)} tickets (sample {(r.get('properties') or {}).get('subject')!r})"

    def verify_engagements(self) -> tuple[bool, str]:
        n = self.manifest.get("engagements_count", 0)
        if n == 0:
            return False, "no engagements created"
        return True, f"{n} engagements logged"

    def verify_custom_object(self) -> tuple[bool, str]:
        co = self.manifest.get("custom_object") or {}
        type_id = co.get("object_type_id") or co.get("id")
        if not type_id:
            if not self.plan.get("custom_object"):
                return True, "skipped — not in plan"
            return False, "custom object missing from manifest"
        s, r = self.client.request("GET", f"/crm/v3/schemas/{type_id}")
        if not self.client.is_ok(s):
            return False, f"GET schema {type_id} returned {s}"
        return True, f"schema {co.get('name')} → {type_id}"

    def verify_custom_events(self) -> tuple[bool, str]:
        if self.plan.get("custom_event_flows"):
            flows = self.manifest.get("custom_event_flows") or {}
            if not flows:
                return False, "custom_event_flows in plan but none recorded"
            problems = []
            total_fires = 0
            for name, info in flows.items():
                attempted = int(info.get("fires_attempted") or 0)
                succeeded = int(info.get("fires_succeeded") or 0)
                total_fires += succeeded
                missing = info.get("missing_event_schemas") or []
                if missing:
                    problems.append(f"{name}: missing schemas {missing}")
                if attempted <= 0:
                    problems.append(f"{name}: no fire attempts")
                elif succeeded != attempted:
                    problems.append(f"{name}: fires {succeeded}/{attempted}")
                if info.get("validate_via_get_passed") is False:
                    problems.append(f"{name}: schema validation failed")
            if problems:
                return False, "; ".join(problems[:3])
            return True, f"{len(flows)} flow(s), {total_fires} event fire(s)"
        if not self.plan.get("custom_events"):
            return True, "skipped — not in plan"
        events = self.manifest.get("custom_events") or {}
        return (bool(events), f"{len(events)} event def(s) recorded" if events
                else "events in plan but none recorded")

    def verify_forms(self) -> tuple[bool, str]:
        if not self.plan.get("forms"):
            return True, "skipped — no forms in plan"
        forms = self.manifest.get("forms") or {}
        if not forms:
            return False, "forms in plan but none created"
        guid = self._get_first(forms)
        s, r = self.client.request("GET", f"/marketing/v3/forms/{guid}")
        if not self.client.is_ok(s):
            return False, f"GET form {guid} returned {s}"
        groups = r.get("fieldGroups", []) or []
        field_count = sum(len(g.get("fields", []) or []) for g in groups)
        return (field_count > 0, f"{len(forms)} form(s) (sample has {field_count} field(s))")

    def verify_lead_scoring(self) -> tuple[bool, str]:
        ls = self.manifest.get("lead_scoring") or {}
        if not ls.get("backfilled"):
            return False, "no lead scores backfilled"
        cid = self._get_first(self.manifest.get("contacts"))
        if not cid:
            return False, "no contact to spot-check"
        s, r = self.client.request("GET", f"/crm/v3/objects/contacts/{cid}",
                                   query={"properties": "demo_lead_score"})
        if not self.client.is_ok(s):
            return False, f"GET contact {cid} returned {s}"
        score = (r.get("properties") or {}).get("demo_lead_score")
        return (bool(score), f"{ls.get('backfilled')} scored (sample contact={score})")

    def verify_marketing_email(self) -> tuple[bool, str]:
        em = self.manifest.get("marketing_email") or {}
        eid = em.get("id")
        if not eid:
            return False, "no marketing email id"
        s, r = self.client.request("GET", f"/marketing/v3/emails/{eid}")
        if not self.client.is_ok(s):
            return False, f"GET email {eid} returned {s}"
        return (bool(r.get("subject") or r.get("name")),
                f"email {eid} subject={r.get('subject')!r}")

    def verify_workflows(self) -> tuple[bool, str]:
        wanted = self.plan.get("workflows") or []
        wf = self.manifest.get("workflows") or {}
        if not wanted:
            return True, "skipped — no workflows in plan"
        if not wf:
            manual_items = [
                ms for ms in self.manifest.get("manual_steps", [])
                if "workflow" in (ms.get("item") or "").lower()
                or any(
                    w.get("name") and w.get("name") in (ms.get("item") or "")
                    for w in wanted
                )
            ]
            if manual_items:
                return True, (
                    f"{len(wanted)} workflow(s) planned; "
                    f"{len(manual_items)} manual UI step(s) logged"
                )
            return False, f"{len(wanted)} workflow(s) in plan but none created"
        wid = self._get_first(wf)
        # v4 flows API: GET /automation/v4/flows/{id}
        s, r = self.client.request("GET", f"/automation/v4/flows/{wid}")
        if not self.client.is_ok(s):
            # v3 fallback
            s, r = self.client.request("GET", f"/automation/v3/workflows/{wid}")
        if not self.client.is_ok(s):
            return False, f"GET workflow {wid} returned {s}"
        return True, f"{len(wf)} workflow(s) (sample id={wid})"

    def verify_quotes(self) -> tuple[bool, str]:
        if not self.plan.get("quotes") and not self.manifest.get("quotes"):
            return True, "skipped — not in plan"
        quotes = self.manifest.get("quotes") or {}
        if not quotes:
            return False, "no quotes created"
        qid = self._get_first(quotes)
        s, r = self.client.request("GET", f"/crm/v3/objects/quotes/{qid}",
                                   query={"properties": "hs_title,hs_status"})
        if not self.client.is_ok(s):
            return False, f"GET quote {qid} returned {s}"
        return True, f"{len(quotes)} quote(s) (sample status={(r.get('properties') or {}).get('hs_status')})"

    def verify_invoices(self) -> tuple[bool, str]:
        if not self.plan.get("invoices") and not self.manifest.get("invoices"):
            return True, "skipped — not in plan"
        invs = self.manifest.get("invoices") or {}
        if not invs:
            return False, "no invoices created"
        iid = self._get_first(invs)
        s, r = self.client.request("GET", f"/crm/v3/objects/invoices/{iid}",
                                   query={"properties": "hs_status,hs_invoice_amount_due"})
        if not self.client.is_ok(s):
            return False, f"GET invoice {iid} returned {s}"
        return True, f"{len(invs)} invoice(s) (sample status={(r.get('properties') or {}).get('hs_status')})"

    def verify_calc_property_and_group(self) -> tuple[bool, str]:
        cp = self.manifest.get("calc_property") or {}
        prop_name = cp.get("name") or "deal_age_days"
        s, r = self.client.request("GET", f"/crm/v3/properties/deals/{prop_name}")
        if not self.client.is_ok(s):
            return False, f"GET property deals/{prop_name} returned {s}"
        return True, f"calc property {prop_name} present (group={r.get('groupName')})"

    def verify_marketing_campaign(self) -> tuple[bool, str]:
        cid = self.manifest.get("campaign_id")
        if not cid:
            # Defensive 403 fallback path may have logged manual_step.
            if any("campaign" in (ms.get("item", "").lower())
                   for ms in self.manifest.get("manual_steps", [])):
                return True, "skipped — campaigns scope unavailable, manual_step logged"
            return False, "no campaign id in manifest"
        s, r = self.client.request("GET", f"/marketing/v3/campaigns/{cid}")
        if not self.client.is_ok(s):
            return False, f"GET campaign {cid} returned {s}"
        return True, f"campaign {cid} name={r.get('properties', {}).get('hs_name') or r.get('name')!r}"

    def verify_reports_and_dashboards(self) -> tuple[bool, str]:
        reports_plan = self.plan.get("playwright_reports") or {}
        planned_dashboards = reports_plan.get("dashboards") or []
        if not planned_dashboards:
            return True, "skipped — no v0.4 reports in plan"

        dashboards = self.manifest.get("dashboards_v04") or {}
        reports = self.manifest.get("reports") or {}
        status = self.manifest.get("reports_status") or {}
        if not dashboards:
            if status.get("status") == "blocked":
                return False, (
                    "blocked — Playwright report builder not implemented; "
                    f"{len(planned_dashboards)} dashboard(s) planned"
                )
            return False, f"{len(planned_dashboards)} dashboard(s) planned but none recorded"

        planned_report_count = sum(len(d.get("reports") or []) for d in planned_dashboards)
        missing_report_mix = [
            name for name, info in dashboards.items()
            if int((info or {}).get("report_count") or 0) > 0 and not any(
                (r or {}).get("dashboard_name") == name
                or str(k).rsplit("::", 1)[0] == name
                for k, r in reports.items()
            )
        ]
        if missing_report_mix:
            return False, f"dashboard(s) missing report manifest entries: {missing_report_mix[:3]}"
        return True, (
            f"{len(dashboards)}/{len(planned_dashboards)} dashboard(s), "
            f"{len(reports)}/{planned_report_count} report(s) recorded"
        )

    def verify_doc_urls(self) -> tuple[bool, str]:
        """Open the generated demo-doc.docx, parse every hyperlink, then:
          1. For each link matching the HubSpot CRM contact-record pattern, GET the
             contact id; flag any 404s (broken links in a prospect-facing doc).
          2. Confirm every contact id in manifest["contacts"] appears as the target
             of at least one link in the doc (so the doc isn't missing a persona).
        Result is recorded in manifest["doc_url_verification"]. Returns
        (verified, message) and gracefully skips when python-docx isn't importable.
        """
        result: dict = {
            "checked": 0, "broken": [], "missing_contacts": [],
            "doc_path": None, "skipped": False,
        }
        try:
            from docx import Document  # type: ignore
        except ImportError:
            warn("verify_doc_urls: python-docx not installed; skipping")
            result["skipped"] = True
            self.manifest["doc_url_verification"] = result
            return True, "skipped — python-docx not installed"

        docx_path = (self.manifest.get("demo_doc") or {}).get("docx_path") \
                    or f"{self.work_dir}/demo-doc.docx"
        result["doc_path"] = docx_path
        if not os.path.exists(docx_path):
            self.manifest["doc_url_verification"] = result
            return False, f"docx not found at {docx_path}"

        try:
            doc = Document(docx_path)
        except Exception as e:  # noqa: BLE001
            self.manifest["doc_url_verification"] = result
            return False, f"failed to open docx: {e}"

        # Collect every external URL from the docx relationships.
        urls: list[str] = []
        try:
            for rel in doc.part.rels.values():
                if rel.reltype.endswith("/hyperlink") and rel.target_ref:
                    urls.append(rel.target_ref)
        except Exception as e:  # noqa: BLE001
            self.manifest["doc_url_verification"] = result
            return False, f"failed to enumerate doc hyperlinks: {e}"

        # Match the HubSpot contact-record URL pattern. Builder.url(...) builds
        # https://app.hubspot.com/contacts/{portal}/record/0-1/{cid}.
        contact_url_re = re.compile(
            rf"https://app\.hubspot\.com/contacts/{re.escape(str(self.portal))}"
            r"/record/0-1/(\d+)"
        )
        contact_ids_in_doc: set[str] = set()
        for u in urls:
            m = contact_url_re.search(u)
            if not m:
                continue
            cid = m.group(1)
            contact_ids_in_doc.add(cid)
            result["checked"] += 1
            s, _ = self.client.request("GET", f"/crm/v3/objects/contacts/{cid}")
            if s == 404:
                result["broken"].append(u)

        # Confirm every manifest contact appears in at least one doc link.
        manifest_cids = {str(cid) for cid in (self.manifest.get("contacts") or {}).values()}
        result["missing_contacts"] = sorted(manifest_cids - contact_ids_in_doc)

        self.manifest["doc_url_verification"] = result
        verified = not result["broken"] and not result["missing_contacts"]
        if verified:
            return True, (f"checked {result['checked']} contact link(s); "
                          f"all resolve and {len(manifest_cids)} contact(s) covered")
        msg_parts = []
        if result["broken"]:
            msg_parts.append(f"{len(result['broken'])} broken link(s) (first: {result['broken'][0]})")
        if result["missing_contacts"]:
            msg_parts.append(f"{len(result['missing_contacts'])} contact id(s) missing from doc")
        return False, "; ".join(msg_parts)

    def verify_manifest_integrity(self) -> tuple[bool, str]:
        """Sanity-check internal manifest consistency:
          - form_submissions_count is within 20% of the planned total
            (using math.ceil so a planned=1 still requires 1 actual)
          - every plan contact has a manifest entry
          - every plan deal has a manifest entry (case/whitespace normalized)
        Records detailed result in manifest["manifest_integrity"]."""
        result: dict = {
            "form_submissions": {"actual": 0, "planned": 0, "ok": True,
                                 "per_form": {}},
            "missing_contacts": [], "missing_deals": [],
        }

        # Form submission count vs planned. Fix D: math.ceil — int(0.8*1) == 0
        # made any-number-≥-0 pass, missing the small-count failures the gate
        # was supposed to catch. Ceiling preserves "≥ 80%" intent for n=1,2,4.
        planned_subs = sum(int(f.get("test_submissions", 0))
                           for f in (self.plan.get("forms") or []))
        actual_subs = int(self.manifest.get("form_submissions_count") or 0)
        result["form_submissions"]["planned"] = planned_subs
        result["form_submissions"]["actual"] = actual_subs
        # Per-form breakdown so a debug log can pinpoint which form fell short.
        result["form_submissions"]["per_form"] = dict(
            self.manifest.get("form_submissions_per_form") or {}
        )
        if planned_subs > 0:
            min_acceptable = math.ceil(planned_subs * 0.8)
            result["form_submissions"]["ok"] = actual_subs >= min_acceptable

        # Plan contacts vs manifest contacts (match on email, lowercased +
        # stripped). Per-contact rewrites already happened in create_contacts,
        # so the plan email matches the manifest key.
        manifest_emails = {e.strip().lower()
                          for e in (self.manifest.get("contacts") or {}).keys()}
        for c in (self.plan.get("contacts") or []):
            if c.get("email") and c["email"].strip().lower() not in manifest_emails:
                result["missing_contacts"].append(c["email"])

        # Plan deals vs manifest deals (case/whitespace-normalized match).
        # Trailing whitespace or "Acme Co" vs "acme co" caused false-positive
        # misses. Include both planned + actual lists in the error text.
        def _norm(s: str) -> str:
            return (s or "").strip().lower()
        manifest_deal_names_norm = {_norm(n)
                                    for n in (self.manifest.get("deals") or {}).keys()}
        for d in (self.plan.get("deals") or []):
            if d.get("name") and _norm(d["name"]) not in manifest_deal_names_norm:
                result["missing_deals"].append(d["name"])

        self.manifest["manifest_integrity"] = result

        problems = []
        if not result["form_submissions"]["ok"]:
            per_form_str = ", ".join(
                f"{name}: {pf.get('actual', 0)}/{pf.get('planned', 0)}"
                for name, pf in (result["form_submissions"]["per_form"] or {}).items()
            ) or "no per-form breakdown"
            problems.append(
                f"form submissions {actual_subs}/{planned_subs} (below 80% "
                f"threshold; per-form: {per_form_str})"
            )
        if result["missing_contacts"]:
            problems.append(
                f"{len(result['missing_contacts'])} plan contact(s) missing from manifest"
            )
        if result["missing_deals"]:
            planned_deal_names = [d.get("name") for d in (self.plan.get("deals") or []) if d.get("name")]
            actual_deal_names = list((self.manifest.get("deals") or {}).keys())
            problems.append(
                f"{len(result['missing_deals'])} plan deal(s) missing from manifest "
                f"(planned={planned_deal_names}; actual={actual_deal_names})"
            )
        if not problems:
            return True, (f"submissions {actual_subs}/{planned_subs}, "
                          f"{len(manifest_emails)} contact(s), "
                          f"{len(manifest_deal_names_norm)} deal(s) all reconciled")
        return False, "; ".join(problems)

    # ---- Run ----

    def run(self) -> dict:
        run_started = time.time()
        self.manifest["run_started_at"] = (
            datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        )
        self.preflight_scopes(strict=True)
        self.probe_sandbox_tier()
        self.ensure_properties()
        self._run_with_verify("company", self.create_company, self.verify_company,
                              is_empty_fn=lambda: not self.manifest.get("company", {}).get("id"))
        self._run_with_verify("contacts", self.create_contacts, self.verify_contacts,
                              is_empty_fn=lambda: not self.manifest.get("contacts"))
        self._run_with_verify("leads", self.create_leads, self.verify_leads,
                              is_empty_fn=lambda: not self.manifest.get("leads"))
        self._run_with_verify("pipeline_and_deals", self.create_pipeline_and_deals,
                              self.verify_pipeline_and_deals,
                              is_empty_fn=lambda: not self.manifest.get("deals"))
        self._run_with_verify("campaign_attribution_showcase",
                              self.apply_campaign_attribution_showcase,
                              self.verify_campaign_attribution_showcase,
                              is_empty_fn=lambda: (
                                  bool(self.plan.get("campaign_attribution_showcase"))
                                  and not self.manifest.get("campaign_attribution_showcase")
                              ))
        self._run_with_verify("tickets", self.create_tickets, self.verify_tickets,
                              is_empty_fn=lambda: not self.manifest.get("tickets"))
        self._run_with_verify("engagements", self.create_engagements, self.verify_engagements,
                              is_empty_fn=lambda: self.manifest.get("engagements_count", 0) == 0)
        self._run_with_verify("custom_object", self.create_custom_object, self.verify_custom_object,
                              is_empty_fn=lambda: not (self.manifest.get("custom_object") or {}).get("object_type_id"))
        self._run_with_verify("custom_events", self.create_custom_events, self.verify_custom_events,
                              is_empty_fn=lambda: not self.manifest.get("custom_events"))
        # Pre-flight: ensure any custom contact properties referenced by plan
        # forms exist on the contacts object BEFORE create_forms tries to use
        # them (otherwise the form POST 400s with a generic "internal error").
        # See _ensure_form_field_properties — fix #3, 2026-04-27.
        try:
            self._ensure_form_field_properties()
        except Exception as exc:  # noqa: BLE001 — never crash the build
            warn(f"_ensure_form_field_properties raised {type(exc).__name__}: {exc}")
            self.add_error("ensure_form_field_properties", 0, str(exc))
        self._run_with_verify("forms", self.create_forms, self.verify_forms,
                              is_empty_fn=lambda: not self.manifest.get("forms"))
        self._run_with_verify("lead_scoring", self.lead_scoring, self.verify_lead_scoring,
                              is_empty_fn=lambda: not (self.manifest.get("lead_scoring") or {}).get("backfilled"))
        self._run_with_verify("marketing_email", self.marketing_email, self.verify_marketing_email,
                              is_empty_fn=lambda: not (self.manifest.get("marketing_email") or {}).get("id"))
        self._run_with_verify("workflows", self.workflows, self.verify_workflows,
                              is_empty_fn=lambda: not self.manifest.get("workflows"))
        self._run_with_verify("quotes", self.create_quotes, self.verify_quotes,
                              is_empty_fn=lambda: not self.manifest.get("quotes"))
        self._run_with_verify("invoices", self.create_invoices, self.verify_invoices,
                              is_empty_fn=lambda: not self.manifest.get("invoices"))
        self._run_with_verify("calc_property_and_group", self.create_calc_property_and_group,
                              self.verify_calc_property_and_group,
                              is_empty_fn=lambda: not self.manifest.get("calc_property"))
        self._run_with_verify("marketing_campaign", self.create_marketing_campaign,
                              self.verify_marketing_campaign,
                              is_empty_fn=lambda: not self.manifest.get("campaign_id"))
        self._run_with_verify(
            "reports_and_dashboards",
            self.create_reports_and_dashboards,
            self.verify_reports_and_dashboards,
            is_empty_fn=lambda: (
                not self.manifest.get("dashboards_v04")
                and not self.manifest.get("reports_status")
            ),
        )
        self.save_manifest()
        # Time-saved estimate (item 14): compute BEFORE generate_doc() so the
        # doc renderer can show the hero stat + breakdown table. Wrapped so a
        # failure in the optional module never blocks doc generation.
        try:
            from time_estimates import compute_time_saved  # local import: optional module
            self.manifest["time_saved"] = compute_time_saved(self.manifest, self.plan)
            log(f"  ⏱ Time saved: {self.manifest['time_saved']['total_pretty']} vs manual build")
        except Exception as exc:  # noqa: BLE001 — never crash the build over a stat
            warn(f"time_saved estimate skipped: {type(exc).__name__}: {exc}")
            self.manifest.pop("time_saved", None)
        self.manifest["runtime_seconds"] = round(time.time() - run_started, 2)

        # Fix A: verifier ordering. Runs BEFORE Drive upload so a broken-link
        # or schema-drift doc never lands in front of the prospect.
        #
        # Order:
        #   1. verify_manifest_integrity (diagnostic; logs loudly but proceeds)
        #   2. generate_doc -> writes LOCAL .docx only
        #   3. verify_doc_urls -> parses local .docx; records issues
        #   4. upload_doc_to_drive -> Drive upload last
        try:
            verified, msg = self.verify_manifest_integrity()
            self._record_verify("manifest_integrity", verified, False, msg)
            if not verified:
                # Diagnostic: log loudly but proceed. Errors are surfaced via the
                # manifest so the rep can see them in the doc.
                warn(f"manifest_integrity issues: {msg}")
                self.manifest["errors"].append({
                    "where": "verify.manifest_integrity",
                    "status": 0, "body": msg,
                })
        except Exception as exc:  # noqa: BLE001
            self._record_verify("manifest_integrity", False, False,
                                f"manifest_integrity verifier raised {type(exc).__name__}: {exc}")

        doc = self.generate_doc()  # local .docx only — no Drive upload yet
        self.save_manifest()

        try:
            verified, msg = self.verify_doc_urls()
            self._record_verify("doc_urls", verified, False, msg)
            if not verified:
                # Loud failure: a broken link in a prospect-facing doc is a
                # support escalation. Add to manifest.errors so the rep sees it
                # in the post-run summary, and proceeds with the Drive upload
                # so the rep can manually patch — but tagged.
                warn(f"doc_urls issues: {msg}")
                self.manifest["errors"].append({
                    "where": "verify.doc_urls",
                    "status": 0, "body": msg,
                })
        except Exception as exc:  # noqa: BLE001
            self._record_verify("doc_urls", False, False,
                                f"doc_urls verifier raised {type(exc).__name__}: {exc}")
        self.save_manifest()

        # Drive upload last. Verifiers above already ran against the local docx.
        try:
            self.upload_doc_to_drive()
            doc = self.manifest.get("demo_doc") or doc
        except Exception as exc:  # noqa: BLE001
            warn(f"upload_doc_to_drive failed: {type(exc).__name__}: {exc}")
            self.add_error("upload_doc_to_drive", 0, str(exc))
        self.manifest["runtime_seconds"] = round(time.time() - run_started, 2)
        self.manifest["run_completed_at"] = (
            datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        )
        self.save_manifest()
        # Summary
        log("=" * 60)
        log(f"BUILD SUMMARY for {self.slug}")
        log(f"  Company: {self.manifest['company'].get('name')} ({self.manifest['company'].get('id')})")
        log(f"  Contacts: {len(self.manifest['contacts'])}")
        log(f"  Pipeline: {self.manifest['pipeline'].get('name')}")
        log(f"  Deals: {len(self.manifest['deals'])}")
        log(f"  Tickets: {len(self.manifest['tickets'])}")
        log(f"  Engagements: {self.manifest['engagements_count']}")
        log(f"  Custom object: {self.manifest['custom_object'].get('name')}")
        log(f"  Custom events: {len(self.manifest['custom_events'])}")
        log(f"  Forms: {len(self.manifest['forms'])}")
        log(f"  Form submissions: {self.manifest['form_submissions_count']}")
        log(f"  Lead scoring: {self.manifest['lead_scoring'].get('property')}")
        log(f"  Marketing email: {self.manifest['marketing_email'].get('name', 'logged as manual')}")
        log(f"  Workflows: {len(self.manifest['workflows'])}")
        log(f"  Leads: {len(self.manifest['leads'])}")
        log(f"  Quotes: {len(self.manifest['quotes'])}  (line items: {sum(len(v) for v in self.manifest['line_items'].values())})")
        log(f"  Invoices: {len(self.manifest['invoices'])}")
        log(f"  Campaign: {self.manifest['campaign_id'] or 'not created'}")
        reports_status = self.manifest.get("reports_status") or {}
        if reports_status:
            log(
                "  Reports: "
                f"{reports_status.get('status')} "
                f"({len(self.manifest.get('dashboards_v04') or {})} dashboard(s), "
                f"{len(self.manifest.get('reports') or {})} report(s))"
            )
        log(f"  Manual steps: {len(self.manifest['manual_steps'])}")
        log(f"  Errors: {len(self.manifest['errors'])}")
        verifs = self.manifest.get("verifications", {}) or {}
        verif_ok = sum(1 for v in verifs.values() if v.get("verified"))
        log(f"  Verified: {verif_ok}/{len(verifs)} phases")
        unverified = [k for k, v in verifs.items() if not v.get("verified")]
        if unverified:
            log(f"    unverified: {', '.join(unverified)}")
        log("=" * 60)
        return doc

    # ---- Phase: Playwright UI flows (no API exists for these) ----

    def run_playwright_phases(self, first_run: bool = False) -> None:
        """
        Drives UI flows that have no public API:
          1. Portal branding (logo + primary color)
          2. Workflow: Lead Nurture
          3. Workflow: NPS Routing
          4. Quote Template (saves template id to env)
          5. Sales Sequence (saves sequence id to env)
          6. SEO scan kickoff (async, takes hours on HubSpot side)
        Plus extras (from agent #2):
          7. Starter dashboard
          8. Saved views (3 of them)
        """
        log("Phase: Playwright UI flows")
        if not PLAYWRIGHT_PHASES_AVAILABLE:
            warn(
                "playwright_phases module not importable. "
                "Install: pip install playwright && playwright install chromium"
            )
            self.add_manual_step(
                item="Install Python playwright + run UI flows",
                ui_url="https://app.hubspot.com/",
                instructions=(
                    "pip install playwright && playwright install chromium, "
                    "then re-run with --first-run for interactive login."
                ),
                reason="Python playwright not installed",
            )
            self.manifest["playwright_phases"] = []
            return

        company = self.manifest.get("company") or {}
        customer_name = company.get("name") or self.slug
        domain = company.get("domain") or f"{self.slug}.com"

        marketing_email_id = (self.manifest.get("marketing_email") or {}).get("id")
        forms = self.manifest.get("forms") or {}
        nps_form_guid = next(
            (g for name, g in forms.items() if "nps" in str(name).lower()),
            None,
        )

        sender_email = self.env.get(
            "HUBSPOT_DEMOPREP_SENDER_EMAIL", "demo@example.com"
        )

        # Brand: support legacy plan["brand"] alongside the new plan["branding"]
        # block; fall back to research["branding"] then industry-neutral defaults.
        # The old "#FF6B35" accent default leaked Shipperz transport orange.
        brand = (self.plan.get("brand") or {})
        plan_brand = self.plan.get("branding", {}) or {}
        research_brand = self.research.get("branding", {}) or {}
        # Bug fix (2026-04-27): logo_path was only read from the legacy
        # plan["brand"] block, falling through to a non-existent
        # `{slug}-og.png` default. The v0.3.0 schema puts the logo path on
        # plan["branding"]["logo_path"] (Phase 1 records it from the
        # always-on Playwright capture). Walk all three sources before the
        # fallback so the portal-branding upload can actually find the file.
        logo_path = (
            brand.get("logo_path")
            or plan_brand.get("logo_path")
            or research_brand.get("logo_path")
            or f"{self.work_dir}/{self.slug}-og.png"
        )
        primary_color = (brand.get("primary_color")
                         or plan_brand.get("primary_color")
                         or research_brand.get("primary_color")
                         or "#1A1A1A")
        accent_color = (brand.get("accent_color")
                        or plan_brand.get("accent_color")
                        or research_brand.get("accent_color")
                        or "#3B82F6")
        # v0.3.1: secondary color is optional — only applied if a tier
        # supports a third Brand Kit slot or a designer-curated palette
        # is provided in the plan/research blocks.
        secondary_color = (brand.get("secondary_color")
                           or plan_brand.get("secondary_color")
                           or research_brand.get("secondary_color")
                           or None)
        primary_keyword = brand.get("primary_keyword")

        results = playwright_phases.run_all_phases(
            slug=self.slug,
            portal_id=self.portal,
            logo_path=logo_path,
            primary_color=primary_color,
            accent_color=accent_color,
            secondary_color=secondary_color,
            customer_name=customer_name,
            sender_email=sender_email,
            domain=domain,
            marketing_email_id=str(marketing_email_id) if marketing_email_id else None,
            nps_form_guid=nps_form_guid,
            primary_keyword=primary_keyword,
            first_run=first_run,
            work_dir=self.work_dir,
        )

        self.manifest["playwright_phases"] = results

        # Merge any manual_step entries each flow returned.
        for r in results:
            ms = r.get("manual_step")
            if ms:
                self.add_manual_step(
                    item=ms.get("item", r.get("flow", "playwright_step")),
                    ui_url=ms.get("ui_url", "https://app.hubspot.com/"),
                    instructions=ms.get("instructions", ""),
                    reason=ms.get("reason", ""),
                )

        # Surface SEO scan URL on the manifest top-level for the demo doc.
        for r in results:
            if r.get("flow") == "kick_off_seo_scan" and r.get("scan_url"):
                self.manifest["seo_scan_url"] = r["scan_url"]
                self.manifest["seo_scan_kicked_off_at"] = datetime.datetime.utcnow().isoformat() + "Z"
                break

        # v2-extras: dashboard + saved views
        if PLAYWRIGHT_EXTRAS_AVAILABLE:
            try:
                dash = playwright_phases_extras.create_starter_dashboard(
                    slug=self.slug,
                    customer_name=customer_name,
                    portal_id=self.portal,
                    work_dir=self.work_dir,
                )
                if dash and dash.get("status") == "ok":
                    self.manifest["dashboard_id"] = dash.get("dashboard_id")
                    self.manifest["dashboard_url"] = dash.get("dashboard_url")
                    results.append(dash)
                else:
                    results.append(dash or {"flow": "create_starter_dashboard", "status": "error"})
            except Exception as e:
                warn(f"  dashboard flow exception: {e}")

            try:
                views = playwright_phases_extras.create_saved_views(
                    slug=self.slug,
                    portal_id=self.portal,
                    work_dir=self.work_dir,
                )
                if views:
                    self.manifest["saved_views"] = views.get("saved_views", {})
                    results.append(views)
            except Exception as e:
                warn(f"  saved views flow exception: {e}")

        ok_count = sum(1 for r in results if r.get("status") == "ok")
        ok(f"playwright phases: {ok_count}/{len(results)} succeeded")


# ---- Cleanup ----

def cleanup(slug: str, env_path: str | None = None) -> None:
    env_path = env_path or os.path.expanduser("~/.claude/api-keys.env")
    env = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k] = v
    token = env.get("HUBSPOT_DEMOPREP_SANDBOX_TOKEN")
    portal = env.get("HUBSPOT_DEMOPREP_SANDBOX_PORTAL_ID")
    client = HubSpotClient(token, portal)
    log(f"Cleaning demo data tagged demo_customer={slug}")
    # v2: delete invoices + quotes BEFORE line_items so dependents are removed first.
    # leads (0-136) supports search by demo_customer like other objects.
    for obj_type in ["invoices", "quotes", "line_items", "0-136",
                     "contacts", "companies", "deals", "tickets",
                     "notes", "tasks", "calls", "meetings", "emails"]:
        body = {"filterGroups": [{"filters": [{"propertyName": "demo_customer", "operator": "EQ", "value": slug}]}], "limit": 100}
        while True:
            s, r = client.request("POST", f"/crm/v3/objects/{obj_type}/search", body)
            if not client.is_ok(s):
                warn(f"  search {obj_type}: {s}")
                break
            results = r.get("results", [])
            if not results:
                break
            with ThreadPoolExecutor(max_workers=5) as ex:
                futures = [ex.submit(client.request, "DELETE", f"/crm/v3/objects/{obj_type}/{item['id']}") for item in results]
                done = sum(1 for f in as_completed(futures) if client.is_ok(f.result()[0]))
            ok(f"  {obj_type}: deleted {done}")
            if len(results) < 100:
                break
    # v2: artifact teardown that requires the manifest
    manifest_path = os.path.expanduser(f"/tmp/demo-prep-{slug}/manifest.json")
    if os.path.exists(manifest_path):
        try:
            m = json.load(open(manifest_path))
        except Exception as e:
            warn(f"  manifest read failed: {e}")
            m = {}

        # Marketing campaign(s)
        campaign_ids = []
        if m.get("campaign_id"):
            campaign_ids.append(str(m.get("campaign_id")))
        for cinfo in (m.get("campaigns") or {}).values():
            if isinstance(cinfo, dict) and cinfo.get("id"):
                campaign_ids.append(str(cinfo["id"]))
        for cid in dict.fromkeys(campaign_ids):
            s, _ = client.request("DELETE", f"/marketing/v3/campaigns/{cid}")
            if 200 <= s < 300 or s == 404:
                ok(f"  campaign: deleted {cid}")
            else:
                warn(f"  campaign delete: {s}")

        # Forms, marketing emails, and API-created workflows are not tagged by
        # demo_customer, so tear them down by manifest id when available.
        for form_name, form_guid in (m.get("forms") or {}).items():
            if not form_guid:
                continue
            s, _ = client.request("DELETE", f"/marketing/v3/forms/{form_guid}")
            if 200 <= s < 300 or s == 404:
                ok(f"  form: deleted {form_name} ({form_guid})")
            else:
                warn(f"  form delete {form_name}: {s}")

        email_id = (m.get("marketing_email") or {}).get("id")
        if email_id:
            s, _ = client.request("DELETE", f"/marketing/v3/emails/{email_id}")
            if 200 <= s < 300 or s == 404:
                ok(f"  marketing email: deleted {email_id}")
            else:
                warn(f"  marketing email delete: {s}")

        for wf_name, wf_id in (m.get("workflows") or {}).items():
            if not wf_id:
                continue
            s, _ = client.request("DELETE", f"/automation/v4/flows/{wf_id}")
            if 200 <= s < 300 or s == 404:
                ok(f"  workflow: deleted {wf_name} ({wf_id})")
            else:
                warn(f"  workflow delete {wf_name}: {s}")

        # Custom-object records (records aren't tagged with demo_customer per
        # builder.py comment, so traverse the schema and delete every record).
        oid = (m.get("custom_object") or {}).get("object_type_id")
        if oid:
            after = None
            deleted = 0
            while True:
                query = {"limit": 100}
                if after:
                    query["after"] = after
                s, r = client.request("GET", f"/crm/v3/objects/{oid}", query=query)
                if not client.is_ok(s):
                    warn(f"  custom records list ({oid}): {s}")
                    break
                results = r.get("results", [])
                if not results:
                    break
                with ThreadPoolExecutor(max_workers=5) as ex:
                    futures = [ex.submit(client.request, "DELETE", f"/crm/v3/objects/{oid}/{x['id']}") for x in results]
                    deleted += sum(1 for f in as_completed(futures) if client.is_ok(f.result()[0]))
                after = (r.get("paging") or {}).get("next", {}).get("after")
                if not after:
                    break
            ok(f"  custom records: deleted {deleted}")

            # Custom-object schema
            s, _ = client.request("DELETE", f"/crm/v3/schemas/{oid}")
            if 200 <= s < 300 or s == 404:
                ok(f"  custom schema: deleted {oid}")
            elif s == 405:
                # HubSpot requires schemas to be archived first, then purged.
                client.request("DELETE", f"/crm/v3/schemas/{oid}/purge")
                ok(f"  custom schema: purged {oid}")
            else:
                warn(f"  custom schema delete: {s}")

        # Calc property + property group on deals
        calc = m.get("calc_property") or {}
        calc_name = calc.get("name")
        group_name = calc.get("group")
        if calc_name:
            s, _ = client.request("DELETE", f"/crm/v3/properties/deals/{calc_name}")
            if 200 <= s < 300 or s == 404:
                ok(f"  calc property: deleted {calc_name}")
            else:
                warn(f"  calc property delete: {s}")
        if group_name:
            s, _ = client.request("DELETE", f"/crm/v3/properties/deals/groups/{group_name}")
            if 200 <= s < 300 or s == 404:
                ok(f"  property group: deleted {group_name}")
            else:
                warn(f"  property group delete: {s}")

    log("Cleanup pass complete")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "cleanup":
        cleanup(sys.argv[2])
    else:
        # Strip flags so positional slug detection still works.
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        first_run = "--first-run" in sys.argv
        run_playwright = "--playwright" in sys.argv or "--ui" in sys.argv
        if not args:
            print("usage: builder.py <slug> [--playwright] [--first-run]")
            print("       builder.py cleanup <slug>")
            sys.exit(2)
        slug = args[0]
        b = Builder(slug)
        b.run()
        if run_playwright:
            b.run_playwright_phases(first_run=first_run)
            # Re-save manifest so dashboard/views/SEO/etc. land on disk.
            try:
                b.save_manifest()
            except AttributeError:
                # Older builder versions saved inline in run(); fall back.
                with open(f"{b.work_dir}/manifest.json", "w") as f:
                    json.dump(b.manifest, f, indent=2)
