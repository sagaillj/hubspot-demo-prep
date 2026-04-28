#!/usr/bin/env python3
"""
playwright_phases.py — UI automation for hubspot-demo-prep

HubSpot UI flows that have NO public API surface (see
references/v2-capabilities.md for the why):

  1. upload_portal_branding / upload_portal_branding_with_logo
       (logo + primary/accent/secondary brand colors site-wide)
  2. create_workflow(slug, workflow_type, contact_id_for_test=None)
  3. create_quote_template(slug, customer_name, logo_path, accent_color)
  4. create_sales_sequence(slug, sender_email)
  5. polish_nps_form(slug, customer_name, portal_id, form_guid, ...)
       (radio-NPS → horizontal scale + theme colors)
  6. kick_off_seo_scan(slug, domain)

Each flow:
  - Logs into HubSpot via stored auth state (per-portal-per-slug). First run
    requires interactive headed login; subsequent runs reuse the saved state.
  - Uses text/role-based selectors (page.get_by_text / get_by_role) — CSS
    classes churn weekly in HubSpot's UI.
  - Has a 30s timeout per click. On timeout, falls back to logging a
    `manual_step` and continues — never crashes the build.
  - Takes a screenshot on success AND failure to
    /tmp/demo-prep-{slug}/playwright/{flow}.png

Auth model: HubSpot has no machine-to-machine UI login (per-user Google OAuth
or password). We use Playwright's storage_state (cookies + localStorage)
written to ~/.claude/skills/hubspot-demo-prep/state/{slug}-hubspot.json on
first run.

Designed to be called from builder.Builder.run_playwright_phases(). Runs AFTER
the API phases complete, since several flows depend on artifacts the API phase
creates (marketing email id for workflows, etc.).

Usage standalone:
    python3 playwright_phases.py <slug> --first-run     # interactive login
    python3 playwright_phases.py <slug>                 # headless replay
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
from typing import Any, Callable

# Playwright is an optional runtime dep. Imported lazily so importing this
# module doesn't fail in environments where it isn't installed yet (the
# wizard's setup step installs it).
try:
    from playwright.sync_api import (
        Browser,
        BrowserContext,
        Page,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )

    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    PLAYWRIGHT_AVAILABLE = False
    PlaywrightTimeoutError = Exception  # type: ignore


# ---- Constants ----

DEFAULT_TIMEOUT_MS = 30_000
NETWORK_IDLE_TIMEOUT_MS = 45_000
SCREENSHOT_DIR_TEMPLATE = "/tmp/demo-prep-{slug}/playwright"
STATE_DIR = os.path.expanduser("~/.claude/data/hubspot-demo-prep/state")
ENV_PATH = os.path.expanduser("~/.claude/api-keys.env")
HUBSPOT_BASE = "https://app.hubspot.com"


# ---- Lightweight log helpers (mirror builder.py style) ----

def _log(msg: str) -> None:
    print(f"[playwright] {msg}", flush=True)


def _ok(msg: str) -> None:
    _log(f"  ✓ {msg}")


def _warn(msg: str) -> None:
    _log(f"  ⚠ {msg}")


def _fail(msg: str) -> None:
    _log(f"  ✗ {msg}")


# ---- Humanish delays + load helpers ----

def _human_pause(page: "Page", min_ms: int = 500, max_ms: int = 1500) -> None:
    """Random delay between major actions to reduce bot-detection signal."""
    page.wait_for_timeout(random.randint(min_ms, max_ms))


def _wait_idle(page: "Page") -> None:
    """Wait for HubSpot's heavy SPA to settle before clicking."""
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        # HubSpot occasionally has long-poll websockets that never go idle.
        # Fall back to domcontentloaded so we don't hang forever.
        page.wait_for_load_state("domcontentloaded", timeout=10_000)


def _screenshot(page: "Page", slug: str, flow: str, suffix: str = "") -> str:
    """Save a screenshot. Returns the path."""
    out_dir = SCREENSHOT_DIR_TEMPLATE.format(slug=slug)
    os.makedirs(out_dir, exist_ok=True)
    name = f"{flow}{('-' + suffix) if suffix else ''}.png"
    path = os.path.join(out_dir, name)
    try:
        page.screenshot(path=path, full_page=True)
        _ok(f"screenshot: {path}")
    except Exception as e:  # pragma: no cover
        _warn(f"screenshot failed ({e})")
    return path


# ---- Storage-state path resolution ----

def _state_path(portal_id: str) -> str:
    """Storage state is keyed per HubSpot portal (sandbox), NOT per customer slug.
    All prospects in the same sandbox share one HubSpot login, so reusing
    storage state across slugs avoids re-prompting interactive login per
    prospect. Falls back to slug-keyed paths if a legacy file exists."""
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, f"portal-{portal_id}-hubspot.json")


def _has_state(portal_id: str) -> bool:
    return os.path.exists(_state_path(portal_id))


# ---- Env file mutation (append-or-replace key) ----

def _save_to_env(key: str, value: str) -> None:
    """
    Append-or-replace a single key in ~/.claude/api-keys.env. Does not echo
    the value to stdout — only the key name. Avoids the `paste-token`
    transcript-leak pattern flagged in MEMORY.md.
    """
    if not os.path.exists(ENV_PATH):
        with open(ENV_PATH, "w") as f:
            f.write(f"{key}={value}\n")
        _ok(f"env: created and set {key}")
        return

    lines: list[str] = []
    found = False
    with open(ENV_PATH) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith(f"{key}="):
                lines.append(f"{key}={value}\n")
                found = True
            else:
                lines.append(line if line.endswith("\n") else line + "\n")
    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")
    with open(ENV_PATH, "w") as f:
        f.writelines(lines)
    _ok(f"env: {'updated' if found else 'appended'} {key}")


# ---- Plan loader (mirror playwright_phases_extras._load_plan) ----

def _load_plan(work_dir: str) -> dict[str, Any]:
    """
    Load build-plan.json from {work_dir}. Returns {} on any failure (missing
    file, malformed JSON, permission error) so callers can use
    `plan.get(...)` patterns without guarding against None. Phase 2
    (orchestrator) writes this file; if it's absent, downstream code falls
    back to industry-neutral defaults derived from customer_name + manifest.
    """
    plan_path = os.path.join(work_dir, "build-plan.json")
    if not os.path.exists(plan_path):
        return {}
    try:
        with open(plan_path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:  # noqa: BLE001
        _warn(f"_load_plan failed reading {plan_path}: {e}")
        return {}


def _load_research(work_dir: str) -> dict[str, Any]:
    """
    Load research.json from {work_dir} for industry/keyword fallbacks.
    Returns {} on any failure.
    """
    research_path = os.path.join(work_dir, "research.json")
    if not os.path.exists(research_path):
        return {}
    try:
        with open(research_path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_manifest(work_dir: str) -> dict[str, Any]:
    """Load manifest.json from {work_dir}. Returns {} on any failure."""
    manifest_path = os.path.join(work_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        return {}
    try:
        with open(manifest_path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _work_dir_for(slug: str, work_dir: str | None = None) -> str:
    """Resolve work_dir, defaulting to /tmp/demo-prep-{slug}."""
    return work_dir or f"/tmp/demo-prep-{slug}"


# ---- Status dict helpers ----

def _manual_step_result(
    flow: str,
    item: str,
    ui_url: str,
    instructions: str,
    reason: str,
    screenshot_path: str | None = None,
) -> dict[str, Any]:
    return {
        "flow": flow,
        "status": "manual_step",
        "manual_step": {
            "item": item,
            "ui_url": ui_url,
            "instructions": instructions,
            "reason": reason,
        },
        "screenshot": screenshot_path,
    }


def _success_result(
    flow: str,
    extras: dict[str, Any] | None = None,
    screenshot_path: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "flow": flow,
        "status": "ok",
        "screenshot": screenshot_path,
    }
    if extras:
        out.update(extras)
    return out


# ---- PlaywrightSession context manager ----

class PlaywrightSession:
    """
    Owns the browser + context + page lifecycle. Loads storage state from
    disk if present; otherwise launches headed for an interactive login (if
    first_run=True) or surfaces a manual_step.
    """

    def __init__(
        self,
        slug: str,
        portal_id: str,
        first_run: bool = False,
        headless: bool | None = None,
    ) -> None:
        self.slug = slug
        self.portal_id = portal_id
        self.first_run = first_run
        self.headless = (not first_run) if headless is None else headless
        # Per-portal state (was per-slug — caused redundant logins for every prospect).
        self.state_path = _state_path(portal_id)
        # Migrate legacy per-slug state if present and per-portal state isn't.
        legacy = os.path.join(STATE_DIR, f"{slug}-hubspot.json")
        if os.path.exists(legacy) and not os.path.exists(self.state_path):
            try:
                os.rename(legacy, self.state_path)
            except OSError:
                pass

        self._pw = None
        self.browser: "Browser" | None = None
        self.context: "BrowserContext" | None = None
        self.page: "Page" | None = None

    def __enter__(self) -> "PlaywrightSession":
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Python playwright not installed. Run: "
                "pip install playwright && playwright install chromium"
            )

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=self.headless)

        ctx_kwargs: dict[str, Any] = {
            "viewport": {"width": 1440, "height": 900},
            # Default UA — don't spoof, HubSpot sees Chrome-on-Mac, fine.
        }
        if _has_state(self.portal_id) and not self.first_run:
            ctx_kwargs["storage_state"] = self.state_path
            _ok(f"loaded storage state: {self.state_path}")
        else:
            if not self.first_run:
                _warn(
                    f"no storage state at {self.state_path} — "
                    "either pass --first-run or all flows will be marked manual"
                )

        self.context = self.browser.new_context(**ctx_kwargs)
        self.context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        self.page = self.context.new_page()

        if self.first_run:
            self._interactive_login()

        return self

    def _interactive_login(self) -> None:
        """
        On --first-run, open HubSpot login and wait for the user to complete
        Google OAuth or password sign-in. Detects success by waiting for ANY
        post-login HubSpot URL with a numeric portal id (the user may land on
        their default portal, not necessarily the sandbox), then explicitly
        navigates to the sandbox portal before saving storage state.
        """
        assert self.page is not None and self.context is not None
        _log("first-run: opening HubSpot login. Sign in interactively.")
        self.page.goto(f"{HUBSPOT_BASE}/login", wait_until="domcontentloaded")
        try:
            # Match any logged-in HubSpot URL — common landing paths after auth
            # include /home-beta, /reports-dashboard/<portal>, /contacts/<portal>,
            # etc. The /portal-id-prefixed paths all contain a numeric portal id.
            self.page.wait_for_url(
                re.compile(rf"{re.escape(HUBSPOT_BASE)}/(home|reports-dashboard|contacts|crm|sales|marketing|settings|account)"),
                timeout=300_000,
            )
            _ok("login detected — switching to sandbox portal")
            # Force a navigation to the sandbox portal so the saved storage
            # state is keyed to the right portal context.
            self.page.goto(
                f"{HUBSPOT_BASE}/contacts/{self.portal_id}",
                wait_until="domcontentloaded",
            )
            try:
                self.page.wait_for_url(
                    re.compile(rf"{re.escape(HUBSPOT_BASE)}/.*/{self.portal_id}.*"),
                    timeout=60_000,
                )
                _ok(f"in sandbox portal {self.portal_id}")
            except PlaywrightTimeoutError:
                _warn(
                    f"could not auto-switch to portal {self.portal_id}. "
                    "If this account has multiple portals, click the avatar → "
                    "Account & Billing → switch to portal "
                    f"{self.portal_id}, then re-run."
                )
            self.context.storage_state(path=self.state_path)
            _ok(f"storage state saved: {self.state_path}")
        except PlaywrightTimeoutError:
            _fail("login did not complete within 5 minutes")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if self.context is not None:
                self.context.close()
            if self.browser is not None:
                self.browser.close()
            if self._pw is not None:
                self._pw.stop()
        except Exception as e:  # pragma: no cover
            _warn(f"session teardown: {e}")


# ---- Per-flow safe-exec wrapper ----

def _safe_flow(
    slug: str,
    flow_name: str,
    fn: Callable[["Page"], dict[str, Any]],
    page: "Page",
) -> dict[str, Any]:
    """
    Run a flow function. On any exception (timeout, selector miss, network
    error), screenshot + log + return a manual_step dict. NEVER crashes.
    """
    _log(f"flow: {flow_name}")
    try:
        result = fn(page)
        if not result.get("screenshot"):
            result["screenshot"] = _screenshot(page, slug, flow_name, "success")
        return result
    except PlaywrightTimeoutError as e:
        _fail(f"{flow_name}: timeout — {e}")
        path = _screenshot(page, slug, flow_name, "timeout")
        return _manual_step_result(
            flow=flow_name,
            item=flow_name.replace("_", " ").title(),
            ui_url=HUBSPOT_BASE,
            instructions=(
                f"Playwright timed out on '{flow_name}'. "
                f"Open HubSpot UI and complete this step manually. "
                f"See screenshot: {path}"
            ),
            reason=f"Playwright timeout: {str(e)[:200]}",
            screenshot_path=path,
        )
    except Exception as e:
        _fail(f"{flow_name}: {type(e).__name__} — {e}")
        path = _screenshot(page, slug, flow_name, "error")
        return _manual_step_result(
            flow=flow_name,
            item=flow_name.replace("_", " ").title(),
            ui_url=HUBSPOT_BASE,
            instructions=(
                f"Playwright failed on '{flow_name}'. "
                f"Open HubSpot UI and complete this step manually. "
                f"See screenshot: {path}"
            ),
            reason=f"{type(e).__name__}: {str(e)[:200]}",
            screenshot_path=path,
        )


# ============================================================
# FLOW 1 — Portal branding upload (logo + brand colors)
# ============================================================

def upload_portal_branding(
    slug: str,
    portal_id: str,
    logo_path: str,
    primary_color: str,
    accent_color: str,
    page: "Page",
    secondary_color: str | None = None,
) -> dict[str, Any]:
    """
    Settings → Account Defaults → Branding. Upload logo + set brand colors.

    When this phase succeeds, the prospect's logo + colors propagate site-wide
    in HubSpot: form pages, marketing emails sent through HubSpot, customer
    portal, etc. This is the "make it look like a real customer's portal" win.

    Input contract:
      - logo_path: absolute path to a local PNG/JPG (HubSpot resizes
        internally; recommend ~512x512 or larger square logo for best results).
      - primary_color: hex (e.g. "#1A1A1A"). HubSpot stores as the dominant
        brand color used on customer-facing assets.
      - accent_color: hex. Stored as a second brand color slot in HubSpot's
        "Brand Kit" — used for buttons/CTAs in some templates.
      - secondary_color: optional hex. If HubSpot's Brand Kit on this portal
        exposes a third color slot (Marketing Hub Pro+ tiers do), this is
        applied; otherwise it's logged and skipped without failing the flow.

    No public API for brand_settings (see v2-capabilities.md §10). UI-only.

    Selectors are role/text-based; the actual labels in HubSpot's React UI as
    of 2026-04: "Upload logo", "Primary color", "Accent color", "Save".

    Tier dependency: HubSpot's portal branding (logo + primary color) is
    available on every paid tier. Multiple brand colors / "Brand Kit" with
    secondary + accent slots typically requires Marketing Hub Starter+. If a
    color slot is missing on the live tier, the flow skips that slot and
    records it without erroring.

    Failure modes:
      - Logo button selector miss → manual_step pointing at Settings → Account
        Setup → Branding with the local logo path.
      - Color input missing → skipped silently for that slot, success_result
        still returned for the slots that worked.
      - Total flow timeout → _safe_flow wraps and screenshots; manual_step
        falls back to the deep link.
    """
    flow = "upload_portal_branding"

    def _do(p: "Page") -> dict[str, Any]:
        url = f"{HUBSPOT_BASE}/account/{portal_id}/account-defaults?tab=branding"
        p.goto(url, wait_until="domcontentloaded")
        _wait_idle(p)
        _human_pause(p)

        # v0.3.1 walkthrough caught: HubSpot SANDBOX portals don't expose
        # Account & Billing → Branding. The page renders "Sandbox accounts
        # don't have access to Account & Billing." We detect that text early
        # and emit a clean manual_step instead of timing out on each selector
        # for 30s × N slots. Production portals continue normally.
        try:
            page_text = p.evaluate("() => document.body && document.body.innerText || ''")
        except Exception:
            page_text = ""
        sandbox_blockers = [
            "Sandbox accounts don't have access",
            "sandbox accounts don't have access",
            "not available in sandbox",
            "Account & Billing isn't available",
        ]
        if any(blocker.lower() in (page_text or "").lower() for blocker in sandbox_blockers):
            _warn("Sandbox portal blocks Account Defaults → Branding (HubSpot product limit). "
                  "Logo upload + brand colors only land on production portals.")
            return {
                "status": "skipped_sandbox",
                "reason": "Sandbox portals do not expose Account Defaults → Branding. "
                          "Run on a production portal to apply portal-wide logo + brand colors.",
                "manual_step": {
                    "item": "Portal branding (logo + colors)",
                    "ui_url": url,
                    "instructions": (
                        f"This is a production-portal-only setting. "
                        f"On a production HubSpot, upload {logo_path} and set "
                        f"primary={primary_color}"
                        + (f", accent={accent_color}" if accent_color else "")
                        + (f", secondary={secondary_color}" if secondary_color else "")
                        + ". Sandbox portals inherit the parent account's branding."
                    ),
                },
            }

        applied: dict[str, Any] = {
            "logo_uploaded": False,
            "primary_color": None,
            "accent_color": None,
            "secondary_color": None,
        }

        # Logo upload — file chooser pattern, since the input is hidden behind
        # a styled "Upload logo" button.
        if logo_path and os.path.exists(logo_path):
            try:
                with p.expect_file_chooser() as fc_info:
                    # GUESSED selector: match either "Upload logo" or "Upload" CTA.
                    p.get_by_role(
                        "button",
                        name=re.compile(r"upload\s*(logo)?|replace\s+logo|change\s+logo", re.I),
                    ).first.click()
                file_chooser = fc_info.value
                file_chooser.set_files(logo_path)
                _ok(f"logo uploaded: {logo_path}")
                applied["logo_uploaded"] = True
                _human_pause(p)
            except Exception as e:
                _warn(f"logo upload failed ({e}) — continuing with colors")
        else:
            _warn(f"logo_path missing or not found ({logo_path}) — skipping logo upload")

        # Primary color (the customer-facing dominant brand color).
        try:
            p.get_by_label(re.compile(r"primary\s*color", re.I)).first.fill(primary_color)
            applied["primary_color"] = primary_color
            _ok(f"primary color set: {primary_color}")
        except Exception:
            try:
                p.get_by_text(re.compile(r"primary\s*color", re.I)).first.click()
                _human_pause(p)
                p.keyboard.type(primary_color)
                applied["primary_color"] = primary_color
            except Exception as e:
                _warn(f"primary color input not found ({e})")

        # Accent color slot. HubSpot's Brand Kit exposes this on Starter+
        # tiers as "Accent color" or "Brand color 2".
        try:
            p.get_by_label(
                re.compile(r"accent\s*color|brand\s*color\s*2|secondary\s*brand\s*color", re.I)
            ).first.fill(accent_color)
            applied["accent_color"] = accent_color
            _ok(f"accent color set: {accent_color}")
        except Exception:
            _warn("accent color slot not found — likely tier-restricted; skipping")

        # Secondary color slot — typically only on Marketing Hub Pro+.
        if secondary_color:
            try:
                p.get_by_label(
                    re.compile(r"^secondary\s*color$|brand\s*color\s*3|tertiary\s*color", re.I)
                ).first.fill(secondary_color)
                applied["secondary_color"] = secondary_color
                _ok(f"secondary color set: {secondary_color}")
            except Exception:
                _warn("secondary color slot not found — likely tier-restricted; skipping")

        _human_pause(p)
        # Save
        try:
            p.get_by_role("button", name=re.compile(r"^save$", re.I)).first.click()
            _wait_idle(p)
            _human_pause(p, 1000, 2000)
        except Exception as e:
            _warn(f"save button click failed ({e})")

        # Verify by reloading and confirming the primary color value persists.
        try:
            p.reload(wait_until="domcontentloaded")
            _wait_idle(p)
        except Exception:
            pass
        verified = False
        try:
            color_input = p.get_by_label(re.compile(r"primary\s*color", re.I)).first
            v = color_input.input_value()
            verified = (v.lower().lstrip("#") == primary_color.lower().lstrip("#"))
        except Exception:
            verified = False

        return _success_result(
            flow,
            extras={
                "logo_path": logo_path,
                "primary_color": applied["primary_color"],
                "accent_color": applied["accent_color"],
                "secondary_color": applied["secondary_color"],
                "logo_uploaded": applied["logo_uploaded"],
                "verified": verified,
                "url": url,
            },
        )

    return _safe_flow(slug, flow, _do, page)


def upload_portal_branding_with_logo(
    slug: str,
    customer_name: str,
    portal_id: str,
    logo_path: str,
    primary_color: str,
    secondary_color: str | None = None,
    accent_color: str | None = None,
    page: "Page" | None = None,
    work_dir: str | None = None,
    env_path: str | None = None,
) -> dict[str, Any]:
    """
    Wire-friendly wrapper around `upload_portal_branding` matching the v0.3.1
    phase signature spec'd by Jeremy:

        (slug, customer_name, portal_id, logo_path, primary_color,
         secondary_color=None, accent_color=None, work_dir=None, env_path=None)

    This is the public phase name listed in the orchestrator. Internally it
    just calls `upload_portal_branding` with the args remapped — the heavy
    lifting (selectors, file chooser, fallbacks) lives there.

    `customer_name` is accepted for logging/manual-step messaging; it isn't
    sent to HubSpot here (the company name lives on the company record, not
    portal branding).

    `env_path` is accepted for signature parity with other v0.3.1 phases;
    this flow doesn't write to env.

    If `accent_color` is None, falls back to `primary_color` so the existing
    `upload_portal_branding` always has a valid second slot to attempt.

    `page` is required when called from inside an active PlaywrightSession.
    The function is structured this way (page-as-arg) so the orchestrator
    `run_all_phases` can share one browser session across all flows.
    """
    if page is None:
        return _manual_step_result(
            flow="upload_portal_branding_with_logo",
            item=f"Upload portal branding for {customer_name}",
            ui_url=f"{HUBSPOT_BASE}/account/{portal_id}/account-defaults?tab=branding",
            instructions=(
                "Open Settings → Account Setup → Branding and upload "
                f"{logo_path}. Set primary color to {primary_color}"
                + (f", accent color to {accent_color}" if accent_color else "")
                + (f", secondary color to {secondary_color}" if secondary_color else "")
                + "."
            ),
            reason="No active Playwright page passed; cannot drive UI.",
        )
    effective_accent = accent_color or primary_color
    return upload_portal_branding(
        slug=slug,
        portal_id=portal_id,
        logo_path=logo_path,
        primary_color=primary_color,
        accent_color=effective_accent,
        page=page,
        secondary_color=secondary_color,
    )


# ============================================================
# FLOW 2 — Workflow creation
# ============================================================

def create_workflow(
    slug: str,
    portal_id: str,
    workflow_type: str,
    page: "Page",
    marketing_email_id: str | None = None,
    nps_form_guid: str | None = None,
    contact_id_for_test: str | None = None,
    customer_name: str | None = None,
    work_dir: str | None = None,
) -> dict[str, Any]:
    """
    Workflows → Create → Contact-based → blank. Trigger + actions, save +
    activate.

    workflow_type ∈ {"lead_nurture", "nps_routing"}.

    Worst case (UI changed): create empty workflow with name + trigger only;
    add manual_step for the rest.

    Workflow name resolution (industry-neutral; previously hardcoded "Shipperz"):
      1. If `plan["workflows"]` is a list and contains an entry whose name
         matches the workflow_type intent (lead nurture / NPS), use it.
      2. Else build `f"{customer_name} - Welcome nurture"` /
         `f"{customer_name} - NPS routing"` from customer_name.
      3. Else fall back to slug.
    """
    flow = f"create_workflow_{workflow_type}"

    def _do(p: "Page") -> dict[str, Any]:
        url = f"{HUBSPOT_BASE}/workflows/{portal_id}/list/all"
        p.goto(url, wait_until="domcontentloaded")
        _wait_idle(p)
        _human_pause(p)

        # Click "Create workflow"
        p.get_by_role("button", name=re.compile(r"create\s+workflow", re.I)).first.click()
        _human_pause(p)
        # Choose Contact-based blank
        p.get_by_text(re.compile(r"contact[\-\s]based", re.I)).first.click()
        _human_pause(p)
        try:
            p.get_by_text(re.compile(r"start\s+from\s+scratch|blank", re.I)).first.click()
        except Exception:
            pass
        try:
            p.get_by_role("button", name=re.compile(r"^next|create$", re.I)).first.click()
        except Exception:
            pass
        _wait_idle(p)
        _human_pause(p)

        # Industry-neutral workflow name (previously hardcoded "Shipperz Lead
        # Nurture" / "Shipperz NPS Routing"). Resolution order:
        #   1. plan["workflows"][i]["name"] — pick the entry whose name
        #      contains "nurture"/"welcome" (lead_nurture) or "nps"/"routing"
        #      (nps_routing). Use as-is.
        #   2. f"{customer_name} - Welcome nurture" / f"{customer_name} - NPS routing"
        #   3. f"{slug} - Welcome nurture" / f"{slug} - NPS routing"
        plan = _load_plan(_work_dir_for(slug, work_dir))
        cname = customer_name or slug
        plan_workflows = plan.get("workflows") or []
        wf_name = None
        if isinstance(plan_workflows, list):
            if workflow_type == "lead_nurture":
                wanted_keywords = ("nurture", "welcome", "lead")
            else:  # nps_routing
                wanted_keywords = ("nps", "routing", "survey")
            for entry in plan_workflows:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name") or "").strip()
                if name and any(k in name.lower() for k in wanted_keywords):
                    wf_name = name
                    break
        if not wf_name:
            if workflow_type == "lead_nurture":
                wf_name = f"{cname} - Welcome nurture"
            else:
                wf_name = f"{cname} - NPS routing"
        try:
            p.get_by_role("textbox", name=re.compile(r"name|workflow\s*name", re.I)).first.fill(wf_name)
            _ok(f"workflow named: {wf_name}")
        except Exception:
            _warn("could not name workflow via labeled textbox")

        _human_pause(p)

        # Trigger setup — most variable part of HubSpot's editor. If selectors
        # don't resolve, fall back to manual completion.
        manual_actions_needed = False
        try:
            p.get_by_text(re.compile(r"set\s+up\s+triggers|enrollment\s+trigger", re.I)).first.click()
            _human_pause(p)
            if workflow_type == "lead_nurture":
                p.get_by_text(re.compile(r"contact\s+properties", re.I)).first.click()
                _human_pause(p)
                p.get_by_role("textbox").first.fill("Lifecycle stage")
                _human_pause(p)
                p.get_by_text(re.compile(r"^lifecycle\s+stage$", re.I)).first.click()
            else:  # nps_routing
                p.get_by_text(re.compile(r"form\s+submission", re.I)).first.click()
                _human_pause(p)
                if nps_form_guid:
                    p.get_by_role("textbox").first.fill(nps_form_guid)
                    _human_pause(p)
            p.get_by_role("button", name=re.compile(r"apply|done|save", re.I)).first.click()
            _human_pause(p)
        except Exception as e:
            _warn(f"trigger setup hit unexpected UI ({e}) — falling back to manual_step")
            manual_actions_needed = True

        # Actions (Send Email + Delay) for lead_nurture — only if we have an
        # email id and trigger setup didn't already fail.
        if not manual_actions_needed and marketing_email_id and workflow_type == "lead_nurture":
            try:
                p.get_by_text(re.compile(r"add\s+action|\+\s*action", re.I)).first.click()
                _human_pause(p)
                p.get_by_text(re.compile(r"send\s+email", re.I)).first.click()
                _human_pause(p)
                p.get_by_role("textbox").first.fill(str(marketing_email_id))
                _human_pause(p)
                p.get_by_role("button", name=re.compile(r"save|apply", re.I)).first.click()
                _human_pause(p)
                # 1-day delay
                p.get_by_text(re.compile(r"add\s+action|\+\s*action", re.I)).first.click()
                _human_pause(p)
                p.get_by_text(re.compile(r"^delay$", re.I)).first.click()
                _human_pause(p)
                p.get_by_role("textbox").first.fill("1")
                _human_pause(p)
                p.get_by_role("button", name=re.compile(r"save|apply", re.I)).first.click()
                _human_pause(p)
            except Exception as e:
                _warn(f"action setup failed ({e}) — leaving for manual completion")
                manual_actions_needed = True

        # Save + activate
        try:
            p.get_by_role("button", name=re.compile(r"^save$|review|publish", re.I)).first.click()
            _human_pause(p, 1000, 2000)
            p.get_by_role("switch", name=re.compile(r"on|active", re.I)).first.click()
            _human_pause(p)
        except Exception as e:
            _warn(f"save/activate skipped ({e})")

        # Capture workflow id from URL.
        wf_id = None
        m = re.search(r"/platform/flow/(\d+)/", p.url)
        if m:
            wf_id = m.group(1)

        result = _success_result(
            flow,
            extras={
                "workflow_type": workflow_type,
                "workflow_name": wf_name,
                "workflow_id": wf_id,
                "url": p.url,
                "manual_actions_needed": manual_actions_needed,
            },
        )
        if manual_actions_needed:
            result["status"] = "partial"
            result["manual_step"] = {
                "item": f"Finish {workflow_type} workflow",
                "ui_url": p.url,
                "instructions": (
                    f"Workflow '{wf_name}' was created but actions could not be added "
                    "programmatically. Open the workflow editor and add the Send Email + "
                    "Delay actions manually, then activate."
                ),
                "reason": "HubSpot workflow editor selectors did not resolve — UI may have changed.",
            }
        return result

    return _safe_flow(slug, flow, _do, page)


# ============================================================
# FLOW 3 — Quote template
# ============================================================

def create_quote_template(
    slug: str,
    portal_id: str,
    customer_name: str,
    logo_path: str,
    accent_color: str,
    page: "Page",
    work_dir: str | None = None,
) -> dict[str, Any]:
    """
    Sales → Quotes → Templates → Create. Use Modern/Classic base, customize
    branding, save. Capture template id, persist to env.

    Quote intro-copy resolution (industry-neutral; previously hardcoded
    auto-transport "Door-to-door / vehicle and route" copy):
      1. plan["quote_template"]["intro_copy"] — used verbatim if present.
      2. Generic neutral 3-step "what happens next" template using
         {customer_name}.
    """
    flow = "create_quote_template"

    def _do(p: "Page") -> dict[str, Any]:
        url = f"{HUBSPOT_BASE}/quotes-settings/{portal_id}/templates"
        p.goto(url, wait_until="domcontentloaded")
        _wait_idle(p)
        _human_pause(p)

        p.get_by_role("button", name=re.compile(r"create\s+(new\s+)?template", re.I)).first.click()
        _human_pause(p)
        # Prefer Modern, fall back to Classic.
        try:
            p.get_by_text(re.compile(r"^modern$", re.I)).first.click()
        except Exception:
            p.get_by_text(re.compile(r"^classic$", re.I)).first.click()
        _human_pause(p)
        try:
            p.get_by_role("button", name=re.compile(r"^select|^next", re.I)).first.click()
        except Exception:
            pass
        _wait_idle(p)
        _human_pause(p)

        # Logo upload
        if logo_path and os.path.exists(logo_path):
            try:
                with p.expect_file_chooser() as fc_info:
                    p.get_by_role("button", name=re.compile(r"upload|replace\s+logo|add\s+logo", re.I)).first.click()
                fc_info.value.set_files(logo_path)
                _ok(f"quote logo uploaded: {logo_path}")
                _human_pause(p)
            except Exception as e:
                _warn(f"quote logo upload skipped ({e})")

        # Primary color
        try:
            p.get_by_label(re.compile(r"primary\s*color|brand\s*color", re.I)).first.fill(accent_color)
        except Exception:
            _warn("quote color input not found by label")

        # Business name
        try:
            p.get_by_label(re.compile(r"business\s*name|company\s*name", re.I)).first.fill(customer_name)
        except Exception:
            _warn("business name input not found")

        # Custom intro — industry-neutral. Previously hardcoded auto-transport
        # copy ("auto transport on the road / vehicle and route").
        plan = _load_plan(_work_dir_for(slug, work_dir))
        plan_quote = plan.get("quote_template") or {}
        intro = (
            (plan_quote.get("intro_copy") or "").strip()
            if isinstance(plan_quote, dict) else ""
        )
        if not intro:
            intro = (
                f"Thanks for requesting a quote with {customer_name}. "
                "Here's what happens next: 1. We confirm your details. "
                "2. You receive a personalized proposal. "
                "3. We hand-off to your dedicated rep."
            )
        try:
            p.get_by_label(re.compile(r"intro|introduction|message|comments", re.I)).first.fill(intro)
        except Exception:
            _warn("intro field not found")

        _human_pause(p)
        # Name the template
        template_name = f"{customer_name} Branded Template"
        try:
            p.get_by_label(re.compile(r"template\s*name|name", re.I)).first.fill(template_name)
        except Exception:
            pass

        # Save
        p.get_by_role("button", name=re.compile(r"^save", re.I)).first.click()
        _wait_idle(p)
        _human_pause(p, 1500, 2500)

        # Extract template id from URL.
        template_id = None
        m = re.search(r"/templates/(\d+)", p.url)
        if m:
            template_id = m.group(1)

        if template_id:
            _save_to_env(
                f"HUBSPOT_DEMOPREP_{slug.upper()}_QUOTE_TEMPLATE_ID",
                template_id,
            )

        return _success_result(
            flow,
            extras={
                "template_id": template_id,
                "template_name": template_name,
                "url": p.url,
            },
        )

    return _safe_flow(slug, flow, _do, page)


# ============================================================
# FLOW 4 — Sales sequence
# ============================================================

def create_sales_sequence(
    slug: str,
    portal_id: str,
    sender_email: str,
    page: "Page",
    customer_name: str | None = None,
    work_dir: str | None = None,
) -> dict[str, Any]:
    """
    Automation → Sequences → Create. Outbound prospecting starter (3 steps),
    customize each step, save, capture id.

    Sequences API has no create endpoint (see v2-capabilities.md §1) — UI-only.

    Sequence name + first-step subject/body resolution (industry-neutral;
    previously hardcoded "Shipperz" / "auto transport"):
      1. plan["outbound_sequence"]["name"] / .steps[0].subject / .steps[0].body
         (subject and body fall back independently).
      2. Else `f"{customer_name} - Outbound nurture"` for name; neutral
         "{{first_name}}, quick question about {customer_name}" subject; neutral
         intro body.
    """
    flow = "create_sales_sequence"

    def _do(p: "Page") -> dict[str, Any]:
        url = f"{HUBSPOT_BASE}/sequences/{portal_id}"
        p.goto(url, wait_until="domcontentloaded")
        _wait_idle(p)
        _human_pause(p)

        p.get_by_role("button", name=re.compile(r"create\s+sequence", re.I)).first.click()
        _human_pause(p)
        try:
            p.get_by_text(re.compile(r"outbound\s+prospecting", re.I)).first.click()
        except Exception:
            try:
                p.get_by_text(re.compile(r"start\s+from\s+scratch", re.I)).first.click()
            except Exception:
                pass
        _human_pause(p)
        try:
            p.get_by_role("button", name=re.compile(r"^select|^next|^create", re.I)).first.click()
        except Exception:
            pass
        _wait_idle(p)
        _human_pause(p)

        # Industry-neutral sequence name + step copy (previously hardcoded
        # "Shipperz Outbound" / "Shipperz auto transport"). Pull from
        # plan["outbound_sequence"] when available; fall back to customer_name.
        plan = _load_plan(_work_dir_for(slug, work_dir))
        plan_seq = plan.get("outbound_sequence") or {}
        if not isinstance(plan_seq, dict):
            plan_seq = {}
        cname = customer_name or slug

        seq_name = (plan_seq.get("name") or "").strip() or f"{cname} - Outbound nurture"

        plan_steps = plan_seq.get("steps") if isinstance(plan_seq.get("steps"), list) else []
        first_step = plan_steps[0] if plan_steps and isinstance(plan_steps[0], dict) else {}
        seq_subject = (first_step.get("subject") or "").strip() or (
            f"{{{{first_name}}}}, quick question about {cname}"
        )
        seq_body = (first_step.get("body") or "").strip() or (
            f"Hi {{{{first_name}}}}, I'd love to learn more about your team's "
            f"current process and share how {cname} might help. Open to a quick call?"
        )

        try:
            p.get_by_role("textbox", name=re.compile(r"sequence\s*name|name", re.I)).first.fill(seq_name)
        except Exception:
            _warn("sequence name input not found")

        # Customize first step (subject + body). Deeper customization is
        # fragile — leave step 2/3 to the starter template.
        try:
            p.get_by_role("textbox", name=re.compile(r"subject", re.I)).first.fill(seq_subject)
            _human_pause(p)
            body_locator = p.get_by_role("textbox").nth(1)
            body_locator.fill(seq_body)
        except Exception:
            _warn("could not customize first-step email — leaving template defaults")

        _human_pause(p)
        # Save
        p.get_by_role("button", name=re.compile(r"^save", re.I)).first.click()
        _wait_idle(p)
        _human_pause(p, 1500, 2500)

        sequence_id = None
        m = re.search(r"/sequences/[^/]+/(\d+)", p.url)
        if m:
            sequence_id = m.group(1)

        if sequence_id:
            _save_to_env(
                f"HUBSPOT_DEMOPREP_{slug.upper()}_SEQUENCE_ID",
                sequence_id,
            )
            _save_to_env(
                "HUBSPOT_DEMOPREP_SENDER_EMAIL",
                sender_email,
            )

        return _success_result(
            flow,
            extras={
                "sequence_id": sequence_id,
                "sequence_name": seq_name,
                "sender_email": sender_email,
                "url": p.url,
            },
        )

    return _safe_flow(slug, flow, _do, page)


# ============================================================
# FLOW 5 — SEO scan kickoff (async)
# ============================================================

def kick_off_seo_scan(
    slug: str,
    portal_id: str,
    domain: str,
    page: "Page",
    primary_keyword: str | None = None,
    work_dir: str | None = None,
) -> dict[str, Any]:
    """
    Marketing → SEO → Add topic. Drop the customer's domain + a primary
    keyword. The audit runs async on HubSpot's side (1-3 min). We just kick
    it off and capture the URL.

    Keyword resolution (industry-neutral; previously defaulted to
    "auto transport"):
      1. `primary_keyword` arg (caller-provided).
      2. plan["seo_targets"][0] (or first dict's "keyword"/"name" field).
      3. research["industry"] from research.json.
      4. Skip the SEO step gracefully (returns status="skipped") if no
         keyword can be resolved.
    """
    flow = "kick_off_seo_scan"

    # Resolve keyword BEFORE entering the page-driving closure so we can
    # skip the entire flow gracefully if there's nothing reasonable to type.
    def _resolve_keyword() -> str | None:
        if primary_keyword and primary_keyword.strip():
            return primary_keyword.strip()
        wd = _work_dir_for(slug, work_dir)
        plan = _load_plan(wd)
        targets = plan.get("seo_targets") if isinstance(plan, dict) else None
        if isinstance(targets, list) and targets:
            first = targets[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                for key in ("keyword", "name", "term"):
                    v = first.get(key)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        research = _load_research(wd)
        industry = research.get("industry") if isinstance(research, dict) else None
        if isinstance(industry, str) and industry.strip():
            return industry.strip()
        return None

    resolved_keyword = _resolve_keyword()
    if not resolved_keyword:
        _warn("kick_off_seo_scan: no keyword available (no primary_keyword arg, "
              "no plan['seo_targets'], no research['industry']); skipping.")
        return {
            "flow": flow,
            "status": "skipped",
            "reason": "No SEO keyword available from arg, plan, or research.",
            "domain": domain,
        }

    def _do(p: "Page") -> dict[str, Any]:
        url = f"{HUBSPOT_BASE}/seo/{portal_id}"
        p.goto(url, wait_until="domcontentloaded")
        _wait_idle(p)
        _human_pause(p)

        try:
            p.get_by_role("button", name=re.compile(r"add\s+topic|new\s+topic|create\s+topic", re.I)).first.click()
        except Exception:
            p.get_by_role("button", name=re.compile(r"get\s+audit|run\s+audit", re.I)).first.click()
        _human_pause(p)

        keyword = resolved_keyword
        try:
            p.get_by_label(re.compile(r"core\s*topic|topic|keyword", re.I)).first.fill(keyword)
        except Exception:
            p.get_by_role("textbox").first.fill(keyword)
        _human_pause(p)

        # Domain field (optional in some flows)
        try:
            p.get_by_label(re.compile(r"domain|website|url", re.I)).first.fill(domain)
        except Exception:
            pass

        _human_pause(p)
        try:
            p.get_by_role("button", name=re.compile(r"get\s+audit|run\s+audit|save", re.I)).first.click()
        except Exception:
            p.get_by_role("button", name=re.compile(r"^next|continue", re.I)).first.click()
        _wait_idle(p)
        _human_pause(p, 1500, 2500)

        scan_url = p.url
        scan_id = None
        m = re.search(r"/(seo/[^/]+/[^/]+/(\d+))", scan_url)
        if m:
            scan_id = m.group(2)

        return _success_result(
            flow,
            extras={
                "domain": domain,
                "keyword": keyword,
                "scan_url": scan_url,
                "scan_id": scan_id,
                "note": "Audit runs async on HubSpot side (1-3 min). Refresh the URL to see results.",
            },
        )

    return _safe_flow(slug, flow, _do, page)


# ============================================================
# FLOW 6 — Polish NPS form (radio → horizontal scale + theme colors)
# ============================================================

def polish_nps_form(
    slug: str,
    customer_name: str,
    portal_id: str,
    form_guid: str,
    primary_color: str,
    secondary_color: str | None = None,
    page: "Page" | None = None,
    work_dir: str | None = None,
    env_path: str | None = None,
) -> dict[str, Any]:
    """
    Open the form editor for the API-built NPS form (radio with 10 options
    1-10) and apply the polish that the API can't:

      1. Try to switch the NPS score field's radio layout to "Horizontal" /
         "Inline" so the 10 options render as a connected scale instead of a
         vertical list. (Available on Marketing Hub Pro+; on lower tiers this
         option may not be exposed in the field-style panel.)
      2. Apply theme colors deeper than just the submit button: form
         background tint (subtle), label color, input border color, helper
         text color — using primary + secondary brand colors.
      3. Save.

    On any failure: screenshot, manual_step pointing at the form editor URL,
    keep the build green. This is bonus polish — the form remains functional
    if the polish fails.

    Args:
      form_guid: the form GUID returned from the API form-builder. Pulled
        from `manifest["forms"]["<NPS form name>"]` by the orchestrator.

    Failure modes & manual fallbacks:
      - Form editor URL 404 / form not found → manual_step asking the rep to
        open Marketing → Forms → find the NPS form by name and edit manually.
      - Field-style panel not exposing "Horizontal" → log a manual_step:
        "Open form in HubSpot UI → click NPS score field → Style tab → set
        Display style to Horizontal." Falls through gracefully; theme colors
        are still attempted.
      - Style panel selectors miss → record manual_step with deep link.

    Tier dependency: form Style customization (label color, border color,
    background) is available on Marketing Hub Starter+. The "Horizontal" /
    inline radio layout typically requires Marketing Hub Pro+; on Starter
    the field-style panel only exposes vertical/stacked. The flow is
    written to skip slots that aren't exposed rather than fail.
    """
    flow = "polish_nps_form"

    if page is None:
        return _manual_step_result(
            flow=flow,
            item=f"Polish NPS form for {customer_name}",
            ui_url=f"{HUBSPOT_BASE}/forms/{portal_id}/editor/{form_guid}/edit/form",
            instructions=(
                "Open the NPS form in HubSpot's form editor. Click the NPS "
                "score field, switch its display style to Horizontal/Inline, "
                f"then set theme colors: labels {primary_color}"
                + (f", secondary {secondary_color}" if secondary_color else "")
                + "."
            ),
            reason="No active Playwright page passed; cannot drive UI.",
        )

    if not form_guid:
        return _manual_step_result(
            flow=flow,
            item=f"Polish NPS form for {customer_name}",
            ui_url=f"{HUBSPOT_BASE}/forms/{portal_id}",
            instructions=(
                "No NPS form GUID was found in the manifest. Open Marketing → "
                "Forms, locate the NPS form, and apply Horizontal display "
                f"style + theme colors ({primary_color})."
            ),
            reason="manifest['forms'] did not contain an NPS-named form GUID.",
        )

    def _do(p: "Page") -> dict[str, Any]:
        url = f"{HUBSPOT_BASE}/forms/{portal_id}/editor/{form_guid}/edit/form"
        p.goto(url, wait_until="domcontentloaded")
        _wait_idle(p)
        _human_pause(p)

        applied: dict[str, Any] = {
            "horizontal_layout": False,
            "label_color": None,
            "input_border_color": None,
            "helper_color": None,
            "form_background": None,
            "submit_color": None,
        }

        # ---- Step 1: Find and click the NPS score field ----
        # The NPS score field will be the radio field with 10 options. We
        # locate it by clicking any field whose label contains "score" /
        # "NPS" / "1-10". If multiple match, take the first.
        try:
            nps_field = p.get_by_text(
                re.compile(r"score|nps|how\s+likely|1\s*[-–]\s*10|recommend", re.I)
            ).first
            nps_field.click()
            _human_pause(p)
            _ok("NPS score field selected in editor")
        except Exception as e:
            _warn(f"could not select NPS score field ({e})")

        # ---- Step 2: Try to switch layout to Horizontal ----
        # HubSpot's field options panel opens on the right after clicking a
        # field. Look for a "Display style" / "Layout" / "Field style" toggle.
        try:
            # First, try clicking a "Style" or "Display" tab inside the panel.
            for tab_label in ("Style", "Display", "Field style", "Layout"):
                try:
                    p.get_by_role("tab", name=re.compile(rf"^{re.escape(tab_label)}$", re.I)).first.click(timeout=2_000)
                    _human_pause(p, 200, 500)
                    break
                except Exception:
                    continue

            # Then click the Horizontal option.
            try:
                p.get_by_role(
                    "radio", name=re.compile(r"horizontal|inline", re.I)
                ).first.click(timeout=3_000)
                applied["horizontal_layout"] = True
                _ok("NPS field layout: horizontal")
            except Exception:
                # Fallback: button or text-only toggle
                try:
                    p.get_by_role(
                        "button", name=re.compile(r"horizontal|inline", re.I)
                    ).first.click(timeout=2_000)
                    applied["horizontal_layout"] = True
                    _ok("NPS field layout: horizontal (button)")
                except Exception:
                    _warn(
                        "Horizontal layout option not exposed on this tier — "
                        "recording manual_step. Will continue with theme colors."
                    )
            _human_pause(p)
        except Exception as e:
            _warn(f"layout switch path errored ({e})")

        # ---- Step 3: Theme colors ----
        # Navigate to the form-wide Style tab (separate from per-field style).
        # HubSpot's form editor usually has a top-level "Style" or "Style &
        # preview" tab in addition to per-field style.
        try:
            for tab_label in ("Style & preview", "Style", "Theme"):
                try:
                    p.get_by_role("tab", name=re.compile(rf"^{re.escape(tab_label)}$", re.I)).first.click(timeout=2_000)
                    _human_pause(p, 300, 700)
                    break
                except Exception:
                    continue
        except Exception:
            _warn("style tab not found — colors may not apply")

        def _try_fill_color(label_pattern: str, value: str, slot: str) -> None:
            """Attempt to fill a color input by label; skip silently on miss."""
            try:
                p.get_by_label(re.compile(label_pattern, re.I)).first.fill(value)
                applied[slot] = value
                _ok(f"{slot} set: {value}")
            except Exception:
                _warn(f"{slot} input not found (pattern={label_pattern}) — skipped")

        # Submit-button color → primary (most impactful CTA color).
        _try_fill_color(r"submit.*color|button.*color", primary_color, "submit_color")
        # Label color → primary (text headlines).
        _try_fill_color(r"label\s*color|field\s*label", primary_color, "label_color")
        # Helper text → secondary (or primary if no secondary).
        _try_fill_color(
            r"help(er)?\s*text\s*color|description\s*color",
            secondary_color or primary_color,
            "helper_color",
        )
        # Input border → primary (subtle brand presence on focus).
        _try_fill_color(
            r"border\s*color|input\s*border",
            primary_color,
            "input_border_color",
        )
        # Form background — leave default unless secondary_color provided
        # (background changes are visually risky; only apply when caller
        # explicitly sent a secondary color implying a designer-curated
        # palette).
        if secondary_color:
            _try_fill_color(r"background\s*color|form\s*background", secondary_color, "form_background")

        _human_pause(p)

        # ---- Step 4: Save ----
        try:
            p.get_by_role(
                "button", name=re.compile(r"^update|^save|publish", re.I)
            ).first.click()
            _wait_idle(p)
            _human_pause(p, 1000, 2000)
            _ok("form saved")
        except Exception as e:
            _warn(f"save click failed ({e})")

        # Build the result. If horizontal layout failed AND no colors stuck,
        # this is effectively a no-op — flag as partial with a manual_step.
        any_applied = applied["horizontal_layout"] or any(
            applied[k] for k in ("label_color", "input_border_color", "helper_color", "submit_color", "form_background")
        )
        result = _success_result(
            flow,
            extras={
                "form_guid": form_guid,
                "applied": applied,
                "url": url,
            },
        )
        if not applied["horizontal_layout"]:
            # The headline polish (radio → scale) didn't land. Surface a
            # manual_step so the rep can flip it in 5 seconds before the demo.
            result["status"] = "partial" if any_applied else "manual_step"
            result["manual_step"] = {
                "item": f"Set NPS field to Horizontal layout",
                "ui_url": url,
                "instructions": (
                    "Open the NPS form in HubSpot's form editor → click the "
                    "NPS score field → Style tab → set Display style to "
                    "Horizontal. (Marketing Hub Pro+ feature; if it's not "
                    "available on this tier, leave the radio buttons stacked — "
                    "the form is still functional.)"
                ),
                "reason": (
                    "Horizontal layout selector did not resolve in the form "
                    "editor — likely tier-restricted or HubSpot UI changed."
                ),
            }
        return result

    return _safe_flow(slug, flow, _do, page)


# ============================================================
# Phase orchestrator (called by Builder.run_playwright_phases)
# ============================================================

def run_all_phases(
    slug: str,
    portal_id: str,
    *,
    logo_path: str,
    primary_color: str,
    accent_color: str,
    customer_name: str,
    sender_email: str,
    domain: str,
    secondary_color: str | None = None,
    marketing_email_id: str | None = None,
    nps_form_guid: str | None = None,
    primary_keyword: str | None = None,
    first_run: bool = False,
    work_dir: str | None = None,
) -> list[dict[str, Any]]:
    """
    Run all UI flows sequentially. Each returns a status dict. The list is
    meant to be merged by the caller (Builder.run_playwright_phases) into
    manifest under manifest["playwright_phases"].

    Order:
      1. upload_portal_branding_with_logo  (logo + brand colors site-wide)
      2. create_workflow lead_nurture
      3. create_workflow nps_routing
      4. create_quote_template
      5. create_sales_sequence
      6. polish_nps_form  (radio → horizontal scale; theme colors)
      7. kick_off_seo_scan  (async kickoff, last because it doesn't gate
         anything else)
    """
    if not PLAYWRIGHT_AVAILABLE:
        msg = (
            "Python playwright not installed. Skipping all UI phases. "
            "Run: pip install playwright && playwright install chromium"
        )
        _warn(msg)
        return [{"flow": "all", "status": "skipped", "reason": msg}]

    # Bug fix (2026-04-27): _has_state / _state_path are keyed by *portal_id*
    # (state files are named `portal-{portal_id}-hubspot.json` — see
    # _state_path at line ~128). The previous code passed `slug` here, which
    # made every run with --playwright bail out with a "no storage state"
    # manual step even though the portal-keyed state file existed and the
    # PlaywrightSession constructor would happily load it. The visible
    # symptom: portal branding upload (Fix F3) never ran on any v0.3.1
    # build.
    if not _has_state(portal_id) and not first_run:
        msg = (
            f"No storage state at {_state_path(portal_id)}. "
            "Re-run with --first-run to perform interactive login first."
        )
        _warn(msg)
        return [_manual_step_result(
            flow="all",
            item="HubSpot UI authentication",
            ui_url=HUBSPOT_BASE,
            instructions=(
                "Run `python3 builder.py <slug> --first-run` once to log into "
                "HubSpot interactively. This saves a session cookie that all "
                "subsequent UI flows will reuse headlessly."
            ),
            reason=msg,
        )]

    results: list[dict[str, Any]] = []
    with PlaywrightSession(slug=slug, portal_id=portal_id, first_run=first_run) as session:
        page = session.page
        assert page is not None

        # 1. Portal branding (logo + colors). v0.3.1: use the wrapper
        # `upload_portal_branding_with_logo` which adds secondary_color
        # support and a customer_name-aware manual_step fallback.
        results.append(upload_portal_branding_with_logo(
            slug=slug,
            customer_name=customer_name,
            portal_id=portal_id,
            logo_path=logo_path,
            primary_color=primary_color,
            secondary_color=secondary_color,
            accent_color=accent_color,
            page=page,
            work_dir=work_dir,
        ))
        # 2-3. Workflows
        results.append(create_workflow(
            slug=slug, portal_id=portal_id,
            workflow_type="lead_nurture", page=page,
            marketing_email_id=marketing_email_id,
            customer_name=customer_name,
            work_dir=work_dir,
        ))
        results.append(create_workflow(
            slug=slug, portal_id=portal_id,
            workflow_type="nps_routing", page=page,
            nps_form_guid=nps_form_guid,
            customer_name=customer_name,
            work_dir=work_dir,
        ))
        # 4. Quote template
        results.append(create_quote_template(
            slug=slug, portal_id=portal_id,
            customer_name=customer_name,
            logo_path=logo_path,
            accent_color=accent_color,
            page=page,
            work_dir=work_dir,
        ))
        # 5. Sales sequence
        results.append(create_sales_sequence(
            slug=slug, portal_id=portal_id,
            sender_email=sender_email,
            page=page,
            customer_name=customer_name,
            work_dir=work_dir,
        ))
        # 6. v0.3.1 polish: convert API-built radio NPS form to horizontal
        # scale + apply theme colors. Skipped gracefully if no NPS form
        # GUID is in the manifest.
        if nps_form_guid:
            results.append(polish_nps_form(
                slug=slug,
                customer_name=customer_name,
                portal_id=portal_id,
                form_guid=nps_form_guid,
                primary_color=primary_color,
                secondary_color=secondary_color,
                page=page,
                work_dir=work_dir,
            ))
        else:
            _warn("polish_nps_form: no nps_form_guid; skipping")
            results.append({
                "flow": "polish_nps_form",
                "status": "skipped",
                "reason": "No NPS form GUID in manifest['forms'].",
            })
        # 7. SEO scan kickoff (async; last because it doesn't gate anything).
        results.append(kick_off_seo_scan(
            slug=slug, portal_id=portal_id,
            domain=domain, page=page,
            primary_keyword=primary_keyword,
            work_dir=work_dir,
        ))

    return results


# ============================================================
# CLI entry (standalone use; usually called via builder.py)
# ============================================================

def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not os.path.exists(ENV_PATH):
        return env
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k] = v
    return env


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: playwright_phases.py <slug> [--first-run]", file=sys.stderr)
        return 2
    slug = argv[1]
    first_run = "--first-run" in argv

    env = _load_env()
    portal_id = env.get("HUBSPOT_DEMOPREP_SANDBOX_PORTAL_ID", "51393541")

    work_dir = f"/tmp/demo-prep-{slug}"
    manifest_path = os.path.join(work_dir, "manifest.json")
    manifest: dict[str, Any] = {}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)

    me_id = (manifest.get("marketing_email") or {}).get("id")
    forms = manifest.get("forms") or {}
    nps_form_guid = next(
        (g for name, g in forms.items() if "nps" in name.lower()),
        None,
    )
    company_name = (manifest.get("company") or {}).get("name") or slug
    domain = (manifest.get("company") or {}).get("domain") or f"{slug}.com"
    sender_email = env.get("HUBSPOT_DEMOPREP_SENDER_EMAIL", "demo@example.com")

    # Industry-neutral defaults. Previously hardcoded "shipperz-og.png" +
    # "#FF6B35" (transport orange). Logo now derived from slug; brand colors
    # pulled from build-plan.json (`branding`) → manifest['branding'] →
    # neutral fallback (#1A1A1A near-black + #3B82F6 slate blue accent).
    plan = _load_plan(work_dir)
    plan_brand = (plan.get("branding") or {}) if isinstance(plan, dict) else {}
    manifest_brand = (manifest.get("branding") or {}) if isinstance(manifest, dict) else {}
    primary_color_default = (
        plan_brand.get("primary_color")
        or manifest_brand.get("primary_color")
        or "#1A1A1A"
    )
    accent_color_default = (
        plan_brand.get("accent_color")
        or manifest_brand.get("accent_color")
        or "#3B82F6"
    )
    secondary_color_default = (
        plan_brand.get("secondary_color")
        or manifest_brand.get("secondary_color")
        or None
    )
    logo_default = f"/tmp/demo-prep-{slug}/{slug}-og.png"
    results = run_all_phases(
        slug=slug,
        portal_id=portal_id,
        logo_path=logo_default,
        primary_color=primary_color_default,
        accent_color=accent_color_default,
        secondary_color=secondary_color_default,
        customer_name=company_name,
        sender_email=sender_email,
        domain=domain,
        marketing_email_id=str(me_id) if me_id else None,
        nps_form_guid=nps_form_guid,
        first_run=first_run,
        work_dir=work_dir,
    )

    out_path = os.path.join(work_dir, "playwright-results.json")
    os.makedirs(work_dir, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
