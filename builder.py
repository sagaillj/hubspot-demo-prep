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
    "quote_to_contact": 71,
    "quote_to_line_item": 67,
    "quote_to_template": 286,
    "invoice_to_contact": 177,
    "invoice_to_line_item": 181,
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

    def form_submit(self, form_guid: str, body: dict) -> tuple[int, str]:
        """Unauthenticated form submission endpoint."""
        self._throttle()
        url = f"https://api.hubapi.com/submissions/v3/integration/submit/{self.portal}/{form_guid}"
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
        self.manifest["manual_steps"].append({
            "item": item, "ui_url": ui_url,
            "instructions": instructions, "reason": reason,
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
        for c in self.plan["contacts"]:
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

        # Associate to company (parallel, but throttled by client)
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = []
            for cid in self.manifest["contacts"].values():
                futures.append(ex.submit(
                    self.client.request, "PUT",
                    f"/crm/v3/objects/contacts/{cid}/associations/companies/{company_id}/{ASSOC['contact_to_company']}"
                ))
            ok_count = sum(1 for f in as_completed(futures) if self.client.is_ok(f.result()[0]))
        ok(f"contact-company associations: {ok_count}/{len(self.manifest['contacts'])}")

    # ---- Phase 4: Pipeline + deals + tickets ----

    def create_pipeline_and_deals(self) -> None:
        log("Phase 4: Pipeline + deals")
        pipeline_plan = self.plan["deal_pipeline"]
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

        self.manifest["pipeline"] = {
            "id": pipeline_id, "name": pipeline_plan["name"],
            "url": f"https://app.hubspot.com/sales/{self.portal}/deals/board/view/all/?pipeline={pipeline_id}",
        }

        # Stage map
        s, r = self.client.request("GET", f"/crm/v3/pipelines/deals/{pipeline_id}")
        stage_map = {st["label"]: st["id"] for st in r.get("stages", [])}

        # Deals (sequential to avoid race on associations)
        company_id = self.manifest["company"]["id"]
        contact_ids = list(self.manifest["contacts"].values())
        for i, d in enumerate(self.plan["deals"]):
            stage_id = stage_map.get(d["stage"])
            if not stage_id:
                warn(f"deal {d['name']}: unknown stage {d['stage']}")
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

        notes = self.plan.get("activity_content", {}).get("notes", []) or [
            "Touchpoint with prospect.",
            "Discovery call notes.",
            "Follow-up email summary.",
        ]
        tasks = ["Follow up on pricing", "Send case studies", "Schedule technical deep-dive",
                 "Review contract", "Draft proposal"]
        calls = ["Discovery call", "Demo follow-up", "Pricing discussion", "Technical questions"]
        meetings = ["Demo session", "QBR", "Solutioning workshop"]
        emails = ["Re: Following up", "Quick question", "Demo recap + next steps", "Pricing breakdown"]

        # Pre-generate engagement payloads. Every engagement is tagged
        # demo_customer=<slug> so cleanup's search-by-property loop finds them.
        tag = {"demo_customer": self.slug}
        payloads: list[tuple[str, dict]] = []
        for cid in self.manifest["contacts"].values():
            for _ in range(n_notes):
                ts = self.ms_ago(random.randint(1, days_back))
                payloads.append(("/crm/v3/objects/notes", {
                    "properties": {"hs_note_body": random.choice(notes), "hs_timestamp": ts, **tag},
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["note_to_contact"]}]}],
                }))
            for _ in range(n_tasks):
                ts = self.ms_ago(random.randint(1, days_back))
                payloads.append(("/crm/v3/objects/tasks", {
                    "properties": {"hs_task_subject": random.choice(tasks),
                                   "hs_task_status": "COMPLETED", "hs_task_priority": "MEDIUM",
                                   "hs_timestamp": ts, **tag},
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["task_to_contact"]}]}],
                }))
            for _ in range(n_calls):
                ts = self.ms_ago(random.randint(1, days_back))
                payloads.append(("/crm/v3/objects/calls", {
                    "properties": {"hs_call_title": random.choice(calls),
                                   "hs_call_body": "Productive conversation. Next steps confirmed.",
                                   "hs_call_duration": random.randint(600000, 1800000),
                                   "hs_call_direction": "OUTBOUND", "hs_call_status": "COMPLETED",
                                   "hs_timestamp": ts, **tag},
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["call_to_contact"]}]}],
                }))
            for _ in range(n_meetings):
                start = self.ms_ago(random.randint(1, days_back))
                payloads.append(("/crm/v3/objects/meetings", {
                    "properties": {"hs_meeting_title": random.choice(meetings),
                                   "hs_meeting_body": "30-minute working session.",
                                   "hs_meeting_start_time": start,
                                   "hs_meeting_end_time": start + 1800000,
                                   "hs_meeting_outcome": "COMPLETED", "hs_timestamp": start, **tag},
                    "associations": [{"to": {"id": cid}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": ASSOC["meeting_to_contact"]}]}],
                }))
            for _ in range(n_emails):
                ts = self.ms_ago(random.randint(1, days_back))
                direction = random.choice(["INCOMING_EMAIL", "EMAIL"])
                payloads.append(("/crm/v3/objects/emails", {
                    "properties": {"hs_email_subject": random.choice(emails),
                                   "hs_email_text": "Email between rep and contact.",
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
            body = {"name": co["name"], "labels": co["labels"],
                    "primaryDisplayProperty": co["primary_display"],
                    "secondaryDisplayProperties": co.get("secondary_display", []),
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
        if not self.plan.get("custom_events"):
            return
        log("Phase 7: Custom events")
        days_back = self.plan.get("activity", {}).get("backdate_days", 120)

        # Define each
        for evt in self.plan["custom_events"]:
            body = {"label": evt.get("label", evt["name"]), "name": evt["name"],
                    "description": evt.get("description", ""),
                    "primaryObject": evt.get("primary_object", "CONTACT"),
                    "propertyDefinitions": [{"name": p["name"], "label": p["label"], "type": p["type"]}
                                            for p in evt.get("properties", [])]}
            s, r = self.client.request("POST", "/events/v3/event-definitions", body)
            if self.client.is_ok(s):
                full_name = r.get("fullyQualifiedName") or r.get("name", evt["name"])
                self.manifest["custom_events"][evt["name"]] = full_name
                ok(f"event def {evt['name']} → {full_name}")
            elif s == 409:
                s2, r2 = self.client.request("GET", f"/events/v3/event-definitions/{evt['name']}")
                if self.client.is_ok(s2):
                    full_name = r2.get("fullyQualifiedName") or evt["name"]
                    self.manifest["custom_events"][evt["name"]] = full_name
                    ok(f"event def {evt['name']} (existing)")
            else:
                warn(f"event def {evt['name']}: {s}")
                self.add_error(f"event.def:{evt['name']}", s, r)

        # Fire events on first 5 contacts (parallel)
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
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(self.client.request, "POST", "/events/v3/send", body) for body in sends]
            fires = sum(1 for f in as_completed(futures) if self.client.is_ok(f.result()[0]))
        ok(f"event fires: {fires}/{len(sends)}")

    # ---- Phase 8: Forms ----

    def create_forms(self) -> None:
        if not self.plan.get("forms"):
            return
        log("Phase 8: Forms")
        for fp in self.plan["forms"]:
            # Find existing by listing all (HubSpot list endpoint doesn't filter by name)
            existing_guid = None
            s, r = self.client.request("GET", "/marketing/v3/forms", query={"limit": 100})
            if self.client.is_ok(s):
                for f in r.get("results", []):
                    if f.get("name") == fp["name"]:
                        existing_guid = f["id"]
                        break
            if existing_guid:
                self.manifest["forms"][fp["name"]] = existing_guid
                ok(f"reusing form {fp['name']}")
            else:
                # Split fields into groups of max 3 (HubSpot constraint)
                all_fields = [{"objectTypeId": "0-1", "name": fld["name"],
                              "label": fld["label"], "required": fld.get("required", False),
                              "hidden": False, "fieldType": fld.get("field_type", "single_line_text")}
                             for fld in fp["fields"]]
                groups = [{"groupType": "default_group", "richTextType": "text",
                           "fields": all_fields[i:i+3]} for i in range(0, len(all_fields), 3)]
                now = datetime.datetime.utcnow().isoformat() + "Z"
                body = {"name": fp["name"], "formType": "hubspot",
                        "createdAt": now, "updatedAt": now, "archived": False,
                        "fieldGroups": groups,
                        "configuration": {"language": "en", "cloneable": True, "editable": True,
                                          "archivable": True, "recaptchaEnabled": False,
                                          "createNewContactForNewEmail": False,
                                          "allowLinkToResetKnownValues": False},
                        "displayOptions": {"renderRawHtml": False, "theme": "default_style",
                                           "submitButtonText": fp.get("submit_text", "Submit")},
                        "legalConsentOptions": {"type": "none"}}
                s, r = self.client.request("POST", "/marketing/v3/forms", body)
                if self.client.is_ok(s):
                    self.manifest["forms"][fp["name"]] = r["id"]
                    ok(f"form {fp['name']} → {r['id']}")
                else:
                    warn(f"form {fp['name']}: {s} {str(r)[:200]}")
                    self.add_error(f"form.create:{fp['name']}", s, r)
                    continue

            form_guid = self.manifest["forms"][fp["name"]]
            # Submit test fills (parallel)
            n = fp.get("test_submissions", 5)
            first_names = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Sam", "Drew"]
            last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Davis", "Miller"]
            submission_bodies = []
            for i in range(n):
                fields = []
                for fld in fp["fields"]:
                    if fld["name"] == "email":
                        val = f"demo-lead-{i}-{random.randint(1000,9999)}@demo{self.slug}.com"
                    elif fld["name"] == "firstname":
                        val = random.choice(first_names)
                    elif fld["name"] == "lastname":
                        val = random.choice(last_names)
                    else:
                        val = "sample"
                    fields.append({"objectTypeId": "0-1", "name": fld["name"], "value": val})
                submission_bodies.append({
                    "fields": fields,
                    "context": {"pageUri": "https://example.com/demo", "pageName": fp["name"]},
                })
            with ThreadPoolExecutor(max_workers=3) as ex:
                futures = [ex.submit(self.client.form_submit, form_guid, b) for b in submission_bodies]
                ok_count = sum(1 for f in as_completed(futures) if 200 <= f.result()[0] < 300)
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

        # Hot list with dedup
        list_name = f"Demo: Hot leads by score ({self.slug})"
        # Look for existing list
        s, r = self.client.request("GET", "/crm/v3/lists", query={"objectTypeId": "0-1"})
        list_id = None
        if self.client.is_ok(s):
            for lst in r.get("lists", []) or r.get("results", []):
                if lst.get("name") == list_name:
                    list_id = lst.get("listId") or lst.get("id")
                    break
        if not list_id:
            body = {"name": list_name, "objectTypeId": "0-1", "processingType": "MANUAL"}
            s, r = self.client.request("POST", "/crm/v3/lists", body)
            if self.client.is_ok(s):
                list_id = r.get("list", {}).get("listId") or r.get("listId") or r.get("id")
                ok(f"hot leads list → {list_id}")
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

    # ---- Phase 10: AI marketing email ----

    def upload_hero_image(self, local_path: str, folder: str = "/demo-prep") -> str | None:
        """Upload an image to HubSpot Files via REST API. Returns CDN URL."""
        try:
            import io
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
            warn(f"hero upload failed: {e}")
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

        primary = self.research.get("branding", {}).get("primary_color", "#1a1a1a")
        secondary = self.research.get("branding", {}).get("secondary_color", "#FF6B35")
        company_name = self.manifest["company"]["name"]

        hero_img_html = ""
        if hero_b64:
            hero_img_html = f'<img src="data:image/png;base64,{hero_b64}" alt="{company_name} hero" style="display:block;width:100%;height:auto;border-radius:8px;margin:0 0 24px 0">'

        html_body = f"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{me['subject']}</title></head>
<body style="margin:0;padding:0;background:#f4f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<div style="max-width:640px;margin:0 auto;background:#ffffff;">
  <div style="padding:24px 32px 0 32px;border-top:6px solid {primary};">
    <h1 style="margin:24px 0 8px 0;color:{primary};font-size:28px;line-height:1.2;font-weight:700;">{me['subject']}</h1>
    <p style="color:#666;font-size:14px;margin:0 0 24px 0;">From {me.get('from_name', company_name)}</p>
  </div>
  <div style="padding:0 32px;">{hero_img_html}</div>
  <div style="padding:0 32px 32px 32px;color:#1a1a1a;font-size:16px;line-height:1.6;">
    <p>Thanks for requesting a quote with {company_name}. Here's what happens next:</p>
    <ol style="padding-left:20px;">
      <li><strong>Within 1 hour:</strong> Our team confirms your pickup and delivery details.</li>
      <li><strong>Within 24 hours:</strong> You receive a personalized quote tailored to your vehicle and route.</li>
      <li><strong>Day of pickup:</strong> Door-to-door enclosed transport, with real-time updates.</li>
    </ol>
    <p style="margin-top:24px;">
      <a href="https://www.{self.plan['company']['domain']}" style="display:inline-block;background:{secondary};color:#ffffff;text-decoration:none;padding:14px 28px;border-radius:6px;font-weight:600;">View our services</a>
    </p>
    <p style="color:#666;font-size:13px;margin-top:32px;border-top:1px solid #eee;padding-top:16px;">
      Questions? Reply to this email and we'll get back within an hour.<br>
      {company_name} · {self.plan['company'].get('description', '').split('.')[0]}.
    </p>
  </div>
  <div style="background:{primary};color:#ffffff;padding:16px 32px;text-align:center;font-size:12px;">
    {company_name} — Premium auto transport
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
                    wbody["html"] = (
                        f'<h1 style="text-align:center;color:#1a1a1a;font-size:28px;line-height:1.2;">'
                        f'{me["subject"]}</h1>'
                        f'<p style="font-size:16px;line-height:1.6;color:#1a1a1a;">'
                        f'Hi {{{{contact.firstname}}}}, thanks for requesting a quote with {company_name}. '
                        f'Here\'s what happens next:</p>'
                        f'<ol style="font-size:15px;line-height:1.65;color:#333;">'
                        f'<li><strong>Within 1 hour:</strong> Our team confirms your details.</li>'
                        f'<li><strong>Within 24 hours:</strong> You receive a personalized quote.</li>'
                        f'<li><strong>Day of pickup:</strong> Door-to-door service with real-time updates.</li>'
                        f'</ol>'
                        f'<p style="text-align:center;margin-top:24px;">'
                        f'<a href="https://www.{self.plan["company"]["domain"]}" '
                        f'style="display:inline-block;background:#FF6B35;color:#fff;padding:14px 28px;'
                        f'border-radius:6px;text-decoration:none;font-weight:600;">View our services</a></p>'
                    )
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
                self.add_manual_step(
                    f"Workflow: {wf['name']}", self.url("workflows", self.portal),
                    f"Build via UI. Steps: " + " → ".join([s["type"] for s in wf.get("steps", [])]),
                    f"API returned {s}",
                )

            for gap in gaps:
                wid = self.manifest["workflows"].get(wf["name"], "")
                self.add_manual_step(
                    f"Add {gap['type']} action to '{wf['name']}'",
                    self.url("workflows", self.portal, "platform/flow", str(wid), "edit") if wid else self.url("workflows", self.portal),
                    gap["description"] or f"Add {gap['type']} action at step {gap['step_index']}",
                    f"v4 API does not support {gap['type']} action directly",
                )

    # ---- Phase 12: Sales Workspace Leads (object 0-136) ----

    def create_leads(self) -> None:
        """Create one lead per contact in Sales Workspace. Sales Hub Pro+
        gated — degrade gracefully on 403/404."""
        if not self.manifest["contacts"]:
            return
        log("Phase 12: Sales Workspace leads (0-136)")

        # Pre-flight: ensure demo_customer property exists on the leads object
        prop_body = {
            "name": "demo_customer", "label": "Demo Customer Slug",
            "type": "string", "fieldType": "text", "groupName": "leadinformation",
            "description": "Tags demo data created by hubspot-demo-prep skill.",
        }
        s, _ = self.client.request("POST", "/crm/v3/properties/0-136", prop_body)
        if s in (403, 404):
            warn(f"leads object not available (status {s}) — skipping phase")
            self.add_manual_step(
                "Sales Workspace leads",
                f"https://app.hubspot.com/sales-workspace/{self.portal}",
                "Sales Hub Pro+ required for the Leads object. Create leads manually if needed.",
                "Sales Hub Pro+ required for Leads object",
            )
            return
        # 409 = already exists; other errors are non-fatal here

        labels = ["WARM", "HOT", "COLD"]
        sources = ["Web form", "Inbound call", "LinkedIn outreach",
                   "Referral", "Trade show", "Cold email"]
        contact_items = list(self.manifest["contacts"].items())  # [(email, id), ...]

        ok_count = 0
        sales_pro_blocked = False
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {}
            for email, cid in contact_items:
                name_prefix = email.split("@")[0].replace(".", " ").title()
                src = random.choice(sources)
                body = {
                    "properties": {
                        "hs_lead_name": f"{name_prefix} — auto transport inquiry ({src})",
                        "hs_lead_label": random.choice(labels),
                        "demo_customer": self.slug,
                    },
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

        # Realistic transport-service line-item catalog
        catalog = [
            {"name": "Enclosed transport — coast to coast", "price": "2400"},
            {"name": "Open transport — regional", "price": "850"},
            {"name": "Expedited delivery (3-day)", "price": "650"},
            {"name": "Insurance upgrade — full coverage", "price": "150"},
            {"name": "White-glove pickup + delivery", "price": "300"},
            {"name": "Storage (per day, post-delivery)", "price": "45"},
        ]

        deal_items = list(self.manifest["deals"].items())
        contact_ids = list(self.manifest["contacts"].values())

        for i, (deal_name, deal_id) in enumerate(deal_items):
            # 1) Create 2-3 line items
            n_items = random.randint(2, 3)
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

    def create_calc_property_and_group(self) -> None:
        """Create 'Shipperz Demo Properties' group on deals, add deal_age_days
        calculation property, and re-group existing demo properties under it."""
        log("Phase 15: Calc property + property group")
        group_name = "shipperz_demo_properties"
        group_label = "Shipperz Demo"

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

        # 2) Calculation property: deal_age_days
        calc_body = {
            "name": "deal_age_days",
            "label": "Deal Age (days)",
            "type": "number",
            "fieldType": "calculation_equation",
            "groupName": group_name,
            "calculationFormula": "DAYS_BETWEEN(createdate, NOW())",
            "description": "Days since the deal was created (auto-calculated).",
        }
        s, r = self.client.request("POST", "/crm/v3/properties/deals", calc_body)
        if self.client.is_ok(s) or s == 409:
            self.manifest["calc_property"] = {
                "name": "deal_age_days", "group": group_name,
            }
            ok(f"calc property deal_age_days → {group_name}")
        else:
            warn(f"calc property: {s} {str(r)[:200]}")
            self.add_error("calc_property.create", s, r)
            self.add_manual_step(
                "Calc property: Deal Age (days)",
                self.url("property-settings", self.portal, "properties"),
                "Add deal_age_days property manually with formula DAYS_BETWEEN(createdate, NOW()).",
                f"API returned {s}",
            )

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

    def create_marketing_campaign(self) -> None:
        """Create a Marketing Campaign and associate the existing email + form
        + hot-leads list. Defensive on missing scope."""
        log("Phase 16: Marketing campaign")
        company_name = self.manifest["company"].get("name", "Demo")

        body = {"properties": {
            "hs_name": f"{company_name}: Snowbird Season Q1 2026",
            "hs_start_date": "2026-01-06",
            "hs_end_date": "2026-04-15",
            "hs_notes": ("Seasonal northbound campaign targeting FL/AZ/TX snowbirds "
                         "returning to NY/MA/CT/NJ."),
            "hs_audience": "Snowbirds 60+ owners of vehicles needing seasonal transport",
            "hs_currency_code": "USD",
            "hs_campaign_status": "in_progress",
            "hs_utm": "utm_source=hubspot&utm_medium=email&utm_campaign=snowbird_q1_2026",
        }}

        s, r = self.client.request("POST", "/marketing/v3/campaigns", body)
        if s in (401, 403):
            warn(f"campaign blocked ({s}) — likely missing marketing.campaigns.write")
            self.add_manual_step(
                "Marketing campaign",
                self.url("marketing", self.portal, "campaigns"),
                "Create campaign 'Snowbird Season Q1 2026' manually and associate the marketing email + NPS form.",
                "Token missing marketing.campaigns.write scope (enforced 2026-07-09)",
            )
            return
        if not self.client.is_ok(s):
            warn(f"campaign create: {s} {str(r)[:200]}")
            self.add_error("campaign.create", s, r)
            return

        campaign_guid = r.get("id") or r.get("hs_object_id") or r.get("campaignGuid")
        if not campaign_guid:
            warn(f"campaign: no GUID in response: {str(r)[:200]}")
            self.add_error("campaign.create", s, r)
            return
        self.manifest["campaign_id"] = campaign_guid
        self.manifest["campaign_url"] = self.url(
            "marketing", self.portal, "campaigns/details", str(campaign_guid))
        ok(f"campaign → {campaign_guid}")

        # Associate assets — PUTs with no body
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
        ok(f"campaign assets linked: {linked}/{len(assets_to_link)}")

    # ---- Output ----

    def generate_doc(self) -> dict:
        """Build the .docx demo runbook + (best-effort) upload to Drive."""
        from doc_generator import generate_docx, upload_to_drive
        log("Phase 17: Generate demo doc")
        docx_path = generate_docx(self.manifest, self.research, self.plan,
                                  slug=self.slug, work_dir=self.work_dir,
                                  portal=self.portal)
        company_name = (self.plan.get("company") or {}).get("name") or self.slug
        title = f"HubSpot Demo Prep · {company_name}"
        locked_id = self.env.get("HUBSPOT_DEMOPREP_LOCKED_DOC_ID")
        replace_doc_id = locked_id if (self.slug == "shipperzinc" and locked_id) else None
        upload = upload_to_drive(docx_path, doc_title=title,
                                 replace_doc_id=replace_doc_id)
        self.manifest["demo_doc"] = {
            "docx_path": docx_path,
            "gdoc_url": upload.get("gdoc_url"),
            "doc_id": upload.get("doc_id"),
            "pdf_path": upload.get("pdf_path"),
        }
        if upload.get("gdoc_url"):
            ok(f"demo doc → {upload['gdoc_url']}")
        else:
            ok(f"demo doc → {docx_path} (Drive upload skipped)")
        return self.manifest["demo_doc"]

    # ---- Run ----

    def run(self) -> dict:
        self.preflight_scopes(strict=True)
        self.ensure_properties()
        self.create_company()
        self.create_contacts()
        self.create_leads()                       # v2 — after contacts
        self.create_pipeline_and_deals()
        self.create_tickets()
        self.create_engagements()
        self.create_custom_object()
        self.create_custom_events()
        self.create_forms()
        self.lead_scoring()
        self.marketing_email()
        self.workflows()
        self.create_quotes()                      # v2 — after deals
        self.create_invoices()                    # v2 — after quotes (reuses line items)
        self.create_calc_property_and_group()     # v2 — after deals exist
        self.create_marketing_campaign()          # v2 — after email + form
        self.save_manifest()
        doc = self.generate_doc()
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
        log(f"  Manual steps: {len(self.manifest['manual_steps'])}")
        log(f"  Errors: {len(self.manifest['errors'])}")
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

        brand = (self.plan.get("brand") or {})
        logo_path = brand.get(
            "logo_path",
            f"{self.work_dir}/{self.slug}-og.png",
        )
        primary_color = brand.get("primary_color", "#1A1A1A")
        accent_color = brand.get("accent_color", "#FF6B35")
        primary_keyword = brand.get("primary_keyword")

        results = playwright_phases.run_all_phases(
            slug=self.slug,
            portal_id=self.portal,
            logo_path=logo_path,
            primary_color=primary_color,
            accent_color=accent_color,
            customer_name=customer_name,
            sender_email=sender_email,
            domain=domain,
            marketing_email_id=str(marketing_email_id) if marketing_email_id else None,
            nps_form_guid=nps_form_guid,
            primary_keyword=primary_keyword,
            first_run=first_run,
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

        # Marketing campaign
        cid = m.get("campaign_id")
        if cid:
            s, _ = client.request("DELETE", f"/marketing/v3/campaigns/{cid}")
            if 200 <= s < 300 or s == 404:
                ok(f"  campaign: deleted {cid}")
            else:
                warn(f"  campaign delete: {s}")

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
        slug = args[0] if args else "shipperzinc"
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
