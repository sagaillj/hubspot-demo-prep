#!/usr/bin/env python3
"""
playwright_phases.py — UI automation for hubspot-demo-prep

Five HubSpot UI flows that have NO public API surface (see
references/v2-capabilities.md for the why):

  1. upload_portal_branding(slug, logo_path, primary_color, accent_color)
  2. create_workflow(slug, workflow_type, contact_id_for_test=None)
  3. create_quote_template(slug, customer_name, logo_path, accent_color)
  4. create_sales_sequence(slug, sender_email)
  5. kick_off_seo_scan(slug, domain)

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
# FLOW 1 — Portal branding upload
# ============================================================

def upload_portal_branding(
    slug: str,
    portal_id: str,
    logo_path: str,
    primary_color: str,
    accent_color: str,
    page: "Page",
) -> dict[str, Any]:
    """
    Settings → Account Defaults → Branding. Upload logo + set primary color.

    No public API for brand_settings (see v2-capabilities.md §10). UI-only.

    Selectors are role/text-based; the actual labels in HubSpot's React UI as
    of 2026-04: "Upload logo", "Primary color", "Save".
    """
    flow = "upload_portal_branding"

    def _do(p: "Page") -> dict[str, Any]:
        url = f"{HUBSPOT_BASE}/account/{portal_id}/account-defaults?tab=branding"
        p.goto(url, wait_until="domcontentloaded")
        _wait_idle(p)
        _human_pause(p)

        # Logo upload — file chooser pattern, since the input is hidden behind
        # a styled "Upload logo" button.
        if logo_path and os.path.exists(logo_path):
            with p.expect_file_chooser() as fc_info:
                # GUESSED selector: match either "Upload logo" or "Upload" CTA.
                p.get_by_role("button", name=re.compile(r"upload\s*(logo)?", re.I)).first.click()
            file_chooser = fc_info.value
            file_chooser.set_files(logo_path)
            _ok(f"logo uploaded: {logo_path}")
            _human_pause(p)

        # Primary color input.
        try:
            p.get_by_label(re.compile(r"primary\s*color", re.I)).first.fill(accent_color)
            _ok(f"primary color set: {accent_color}")
        except Exception:
            p.get_by_text(re.compile(r"primary\s*color", re.I)).first.click()
            _human_pause(p)
            p.keyboard.type(accent_color)

        _human_pause(p)
        # Save
        p.get_by_role("button", name=re.compile(r"^save$", re.I)).first.click()
        _wait_idle(p)
        _human_pause(p, 1000, 2000)

        # Verify by reloading and confirming the color value persists.
        p.reload(wait_until="domcontentloaded")
        _wait_idle(p)
        verified = False
        try:
            color_input = p.get_by_label(re.compile(r"primary\s*color", re.I)).first
            v = color_input.input_value()
            verified = (v.lower().lstrip("#") == accent_color.lower().lstrip("#"))
        except Exception:
            verified = False

        return _success_result(
            flow,
            extras={
                "logo_path": logo_path,
                "primary_color": accent_color,
                "verified": verified,
                "url": url,
            },
        )

    return _safe_flow(slug, flow, _do, page)


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
) -> dict[str, Any]:
    """
    Workflows → Create → Contact-based → blank. Trigger + actions, save +
    activate.

    workflow_type ∈ {"lead_nurture", "nps_routing"}.

    Worst case (UI changed): create empty workflow with name + trigger only;
    add manual_step for the rest.
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

        wf_name = (
            f"Demo: Shipperz Lead Nurture ({slug})"
            if workflow_type == "lead_nurture"
            else f"Demo: Shipperz NPS Routing ({slug})"
        )
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
) -> dict[str, Any]:
    """
    Sales → Quotes → Templates → Create. Use Modern/Classic base, customize
    branding, save. Capture template id, persist to env.
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

        # Custom intro
        intro = (
            f"Thanks for considering {customer_name}. We'll get your auto "
            "transport on the road fast — see pricing below."
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
) -> dict[str, Any]:
    """
    Automation → Sequences → Create. Outbound prospecting starter (3 steps),
    customize each step, save, capture id.

    Sequences API has no create endpoint (see v2-capabilities.md §1) — UI-only.
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

        # Name
        seq_name = f"Demo: Shipperz Outbound ({slug})"
        try:
            p.get_by_role("textbox", name=re.compile(r"sequence\s*name|name", re.I)).first.fill(seq_name)
        except Exception:
            _warn("sequence name input not found")

        # Customize first step (subject + body). Deeper customization is
        # fragile — leave step 2/3 to the starter template.
        try:
            p.get_by_role("textbox", name=re.compile(r"subject", re.I)).first.fill(
                "Quick question about Shipperz auto transport"
            )
            _human_pause(p)
            body_locator = p.get_by_role("textbox").nth(1)
            body_locator.fill(
                "Hi {{first_name}}, I help auto transport teams like Shipperz "
                "tighten their pipeline. Worth a quick call?"
            )
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
) -> dict[str, Any]:
    """
    Marketing → SEO → Add topic. Drop the customer's domain + a primary
    keyword. The audit runs async on HubSpot's side (1-3 min). We just kick
    it off and capture the URL.
    """
    flow = "kick_off_seo_scan"

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

        keyword = primary_keyword or "auto transport"
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
    marketing_email_id: str | None = None,
    nps_form_guid: str | None = None,
    primary_keyword: str | None = None,
    first_run: bool = False,
) -> list[dict[str, Any]]:
    """
    Run all 5 flows sequentially. Each returns a status dict. The list is
    meant to be merged by the caller (Builder.run_playwright_phases) into
    manifest under e.g. manifest["playwright_phases"].
    """
    if not PLAYWRIGHT_AVAILABLE:
        msg = (
            "Python playwright not installed. Skipping all UI phases. "
            "Run: pip install playwright && playwright install chromium"
        )
        _warn(msg)
        return [{"flow": "all", "status": "skipped", "reason": msg}]

    if not _has_state(slug) and not first_run:
        msg = (
            f"No storage state at {_state_path(slug)}. "
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

        results.append(upload_portal_branding(
            slug=slug, portal_id=portal_id,
            logo_path=logo_path, primary_color=primary_color,
            accent_color=accent_color, page=page,
        ))
        results.append(create_workflow(
            slug=slug, portal_id=portal_id,
            workflow_type="lead_nurture", page=page,
            marketing_email_id=marketing_email_id,
        ))
        results.append(create_workflow(
            slug=slug, portal_id=portal_id,
            workflow_type="nps_routing", page=page,
            nps_form_guid=nps_form_guid,
        ))
        results.append(create_quote_template(
            slug=slug, portal_id=portal_id,
            customer_name=customer_name,
            logo_path=logo_path,
            accent_color=accent_color,
            page=page,
        ))
        results.append(create_sales_sequence(
            slug=slug, portal_id=portal_id,
            sender_email=sender_email,
            page=page,
        ))
        results.append(kick_off_seo_scan(
            slug=slug, portal_id=portal_id,
            domain=domain, page=page,
            primary_keyword=primary_keyword,
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

    logo_default = f"/tmp/demo-prep-{slug}/shipperz-og.png"
    results = run_all_phases(
        slug=slug,
        portal_id=portal_id,
        logo_path=logo_default,
        primary_color="#1A1A1A",
        accent_color="#FF6B35",
        customer_name=company_name,
        sender_email=sender_email,
        domain=domain,
        marketing_email_id=str(me_id) if me_id else None,
        nps_form_guid=nps_form_guid,
        first_run=first_run,
    )

    out_path = os.path.join(work_dir, "playwright-results.json")
    os.makedirs(work_dir, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
