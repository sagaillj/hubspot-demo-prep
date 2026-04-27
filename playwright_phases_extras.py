"""
playwright_phases_extras — v2 UI flow additions.

Two flows that are awkward to drive via the HubSpot REST API and worth doing
in the UI:

  1. create_starter_dashboard(slug, customer_name)
     Builds a "Shipperz Daily Snapshot" dashboard with 4-6 cards relevant to
     a shipping-prospect "morning coffee" view. ~2 minutes of UI work.

  2. create_saved_views(slug)
     Creates 3 private saved views (Hot Leads / Open Quotes / Needs Reply).
     ~30 seconds each.

Architecture notes
------------------

* Imports PlaywrightSession from playwright_phases.py. If that module is not
  yet present (the other agent is still writing it), this file defines a
  minimal-compatible PlaywrightSession that the other agent will detect and
  skip when it patches.

* All selectors are text/role-based (not CSS class chains), per the demo-prep
  Playwright contract: HubSpot ships frequent UI updates and class-based
  selectors break every few weeks.

* Every navigation has a 30-second timeout. Every click is wrapped in a
  try/except that records a `manual_step` to the manifest and continues —
  these flows must NEVER crash the build.

* Screenshots are taken on every successful step boundary AND on every
  failure, written to {work_dir}/screenshots/.

CONFIDENCE on selectors (flag for live testing — none of these have been
verified against the live HubSpot UI as of 2026-04-26):

  GUESSED — needs live confirmation:
    - "Create dashboard" button (could be "Create new dashboard" or icon-only)
    - "Sales overview" template tile name
    - "Add report" / "Add card" entry point on the dashboard editor
    - "Report library" tab label inside the add-report modal
    - Filter pill UI for `demo_lead_score >= 50`
    - Saved-view "Save view" button location in the contacts/deals/tickets
      list editor — HubSpot has shipped at least 3 different UIs for this
      since 2024.

  CONFIRMED via HubSpot docs / the existing skill code:
    - URL paths: /reports-dashboard/{portal}/dashboards
                 /contacts/{portal}/objects/0-1/views/all/list
                 /contacts/{portal}/objects/0-3/views/all/list
                 /contacts/{portal}/objects/0-5/views/all/list
    - Custom Shipperz pipeline ID is read from manifest['pipeline']['id']
"""
from __future__ import annotations

import datetime
import json
import os
import re
import time
import traceback
from contextlib import contextmanager
from typing import Any

# ----------------------------------------------------------------------------
# PlaywrightSession import (with minimal-compatible fallback)
# ----------------------------------------------------------------------------

try:
    # Preferred — the other agent's full implementation.
    from playwright_phases import PlaywrightSession  # type: ignore  # noqa: F401
    _HAVE_REAL_SESSION = True
except Exception:  # pragma: no cover — fallback path only
    _HAVE_REAL_SESSION = False

    class PlaywrightSession:  # type: ignore[no-redef]
        """
        Minimal-compatible fallback so this module imports cleanly even when
        the in-flight playwright_phases.py has not landed yet. The other
        agent's patcher detects an existing PlaywrightSession and skips its
        own write, so the real implementation wins on every run after it
        lands.

        Contract:
          - Constructed as PlaywrightSession(slug, work_dir, env_path=None)
          - Used as a context manager: `with PlaywrightSession(...) as s:`
          - Exposes `.page` (Playwright Page), `.work_dir` (str),
            `.manifest` (dict), `.token` (HubSpot sandbox token),
            `.portal` (portal id str).
          - Loads/saves storage_state.json at {work_dir}/playwright/state.json
            so login persists across runs.
        """

        def __init__(self, slug: str, work_dir: str, env_path: str | None = None):
            self.slug = slug
            self.work_dir = work_dir
            self.env_path = env_path or os.path.expanduser("~/.claude/api-keys.env")
            self.manifest_path = os.path.join(work_dir, "manifest.json")
            self.state_path = os.path.join(work_dir, "playwright", "state.json")
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            os.makedirs(os.path.join(work_dir, "screenshots"), exist_ok=True)
            self.manifest = (
                json.load(open(self.manifest_path))
                if os.path.exists(self.manifest_path)
                else {}
            )
            env: dict[str, str] = {}
            if os.path.exists(self.env_path):
                with open(self.env_path) as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, _, v = line.partition("=")
                            env[k] = v
            self.token = env.get("HUBSPOT_DEMOPREP_SANDBOX_TOKEN", "")
            self.portal = env.get("HUBSPOT_DEMOPREP_SANDBOX_PORTAL_ID", "51393541")
            self._pw = None
            self._browser = None
            self._context = None
            self.page = None  # set in __enter__

        def __enter__(self):
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as e:
                raise RuntimeError(
                    "playwright is not installed. Run: pip install playwright "
                    "&& npx playwright install chromium"
                ) from e
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            ctx_kwargs: dict[str, Any] = {"viewport": {"width": 1440, "height": 900}}
            if os.path.exists(self.state_path):
                ctx_kwargs["storage_state"] = self.state_path
            self._context = self._browser.new_context(**ctx_kwargs)
            self.page = self._context.new_page()
            self.page.set_default_timeout(30_000)
            return self

        def save_state(self) -> None:
            if self._context is not None:
                self._context.storage_state(path=self.state_path)

        def screenshot(self, label: str) -> str:
            ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            path = os.path.join(self.work_dir, "screenshots", f"{ts}-{label}.png")
            try:
                if self.page is not None:
                    self.page.screenshot(path=path, full_page=True)
            except Exception:
                pass
            return path

        def save_manifest(self) -> None:
            with open(self.manifest_path, "w") as f:
                json.dump(self.manifest, f, indent=2, default=str)

        def __exit__(self, exc_type, exc, tb):
            try:
                self.save_state()
            except Exception:
                pass
            try:
                self.save_manifest()
            except Exception:
                pass
            try:
                if self._context is not None:
                    self._context.close()
                if self._browser is not None:
                    self._browser.close()
                if self._pw is not None:
                    self._pw.stop()
            except Exception:
                pass
            return False  # do not swallow exceptions


# ----------------------------------------------------------------------------
# Logging helpers (mirror builder.py style)
# ----------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _ok(msg: str) -> None:
    _log(f"  PW-EXTRAS ok: {msg}")


def _warn(msg: str) -> None:
    _log(f"  PW-EXTRAS warn: {msg}")


def _fail(msg: str) -> None:
    _log(f"  PW-EXTRAS fail: {msg}")


def _record_manual(session: PlaywrightSession, item: str, ui_url: str,
                   instructions: str, reason: str) -> None:
    """Append a manual_step entry to the manifest (matches Builder's schema)."""
    if "manual_steps" not in session.manifest:
        session.manifest["manual_steps"] = []
    session.manifest["manual_steps"].append({
        "item": item, "ui_url": ui_url,
        "instructions": instructions, "reason": reason,
    })


@contextmanager
def _step(session: PlaywrightSession, label: str, manual_url: str,
          manual_instructions: str):
    """
    Wrap a UI step. Screenshots on success and failure. On any exception
    records a manual_step and re-raises a flag so the caller can continue.
    """
    try:
        yield
        session.screenshot(f"ok-{label}")
        _ok(label)
    except Exception as e:  # noqa: BLE001 — we explicitly want to log everything
        session.screenshot(f"fail-{label}")
        _fail(f"{label}: {e}")
        traceback.print_exc()
        _record_manual(
            session,
            item=f"playwright-extras: {label}",
            ui_url=manual_url,
            instructions=manual_instructions,
            reason=f"Playwright step '{label}' raised: {type(e).__name__}: {e}",
        )
        raise _StepFailed(label) from e


class _StepFailed(Exception):
    """Internal sentinel so flow functions can `try/except _StepFailed` without
    swallowing real bugs."""


def _click_text(session: PlaywrightSession, text: str, *,
                exact: bool = False, timeout_ms: int = 30_000) -> None:
    """Click an element by visible text using role-based locators."""
    page = session.page
    if page is None:
        raise RuntimeError("PlaywrightSession.page is not initialized")
    # Try button role first (most common), then link, then any text.
    for locator in (
        page.get_by_role("button", name=text, exact=exact),
        page.get_by_role("link", name=text, exact=exact),
        page.get_by_text(text, exact=exact).first,
    ):
        try:
            locator.click(timeout=timeout_ms)
            return
        except Exception:
            continue
    raise TimeoutError(f"Could not click text={text!r} within {timeout_ms}ms")


def _fill_label(session: PlaywrightSession, label: str, value: str,
                timeout_ms: int = 15_000) -> None:
    page = session.page
    if page is None:
        raise RuntimeError("PlaywrightSession.page is not initialized")
    page.get_by_label(label).fill(value, timeout=timeout_ms)


# ----------------------------------------------------------------------------
# Flow 1: create_starter_dashboard
# ----------------------------------------------------------------------------

def create_starter_dashboard(slug: str, customer_name: str,
                             portal_id: str,
                             work_dir: str | None = None,
                             env_path: str | None = None) -> dict[str, Any]:
    """
    Build the "Shipperz Daily Snapshot" dashboard with the prospect's
    "morning coffee" view. Records dashboard_id + url into manifest.

    Returns a small dict summary of what was created (or what was logged as
    a manual step).
    """
    work_dir = work_dir or f"/tmp/demo-prep-{slug}"
    summary: dict[str, Any] = {"flow": "create_starter_dashboard",
                               "slug": slug, "customer_name": customer_name,
                               "cards_added": [], "dashboard_id": None}

    try:
        session_cm = PlaywrightSession(slug=slug, portal_id=portal_id)
    except Exception as e:  # noqa: BLE001
        _fail(f"PlaywrightSession init failed: {e}")
        return {**summary, "error": f"session-init: {e}"}

    with session_cm as session:
        portal = session.portal_id
        page = session.page
        if page is None:
            _fail("page is None — Playwright failed to launch")
            return {**summary, "error": "page-init-none"}

        dashboards_url = f"https://app.hubspot.com/reports-dashboard/{portal}/dashboards"
        manual_instructions = (
            "Open Reports -> Dashboards, click 'Create dashboard', pick "
            "'Sales overview' template (or 'Blank' if not offered), name it "
            "'Shipperz Daily Snapshot', then add cards for: deal pipeline by "
            "stage, tickets by status (last 30d), contacts created (last 90d), "
            "marketing email opens/clicks, and shipperz_quote_requested "
            "events over time."
        )

        # ---- Navigate ----
        try:
            with _step(session, "01-nav-dashboards", dashboards_url, manual_instructions):
                page.goto(dashboards_url, timeout=30_000)
                page.wait_for_load_state("domcontentloaded")
        except _StepFailed:
            return {**summary, "error": "nav-dashboards"}

        # ---- Create dashboard ----
        try:
            with _step(session, "02-click-create-dashboard", dashboards_url,
                       manual_instructions):
                # GUESSED: button label may be "Create dashboard" or
                # "Create new dashboard". Try both.
                clicked = False
                for label in ("Create dashboard", "Create new dashboard",
                              "New dashboard", "Create"):
                    try:
                        _click_text(session, label, timeout_ms=5_000)
                        clicked = True
                        break
                    except Exception:
                        continue
                if not clicked:
                    raise TimeoutError(
                        "No 'Create dashboard' button matched any guessed label"
                    )
        except _StepFailed:
            return {**summary, "error": "click-create"}

        # ---- Pick template ----
        try:
            with _step(session, "03-pick-template", dashboards_url,
                       manual_instructions):
                # GUESSED: try the canonical starter template first.
                picked = False
                for label in ("Sales overview", "Sales", "Blank dashboard",
                              "Blank", "Start from scratch"):
                    try:
                        _click_text(session, label, timeout_ms=5_000)
                        picked = True
                        break
                    except Exception:
                        continue
                if not picked:
                    raise TimeoutError(
                        "No template tile matched — chooser layout changed?"
                    )
                # Confirm dialog if present.
                for label in ("Next", "Create dashboard", "Create"):
                    try:
                        _click_text(session, label, timeout_ms=2_000)
                        break
                    except Exception:
                        continue
        except _StepFailed:
            return {**summary, "error": "pick-template"}

        # ---- Name dashboard ----
        try:
            with _step(session, "04-name-dashboard", dashboards_url,
                       manual_instructions):
                # GUESSED: HubSpot sometimes prompts inline, sometimes via modal.
                try:
                    _fill_label(session, "Dashboard name", "Shipperz Daily Snapshot",
                                timeout_ms=5_000)
                except Exception:
                    try:
                        _fill_label(session, "Name", "Shipperz Daily Snapshot",
                                    timeout_ms=5_000)
                    except Exception:
                        # Fallback: edit the title in the header.
                        page.keyboard.type("Shipperz Daily Snapshot")
                # Confirm.
                for label in ("Save", "Create", "Done"):
                    try:
                        _click_text(session, label, timeout_ms=2_000)
                        break
                    except Exception:
                        continue
        except _StepFailed:
            # Non-fatal: continue trying to add cards even if name didn't stick.
            _warn("dashboard naming may have failed; continuing")

        # Capture dashboard ID from URL (HubSpot redirects to
        # /reports-dashboard/{portal}/dashboard/{id}).
        try:
            url = page.url
            m = re.search(r"/dashboard/(\d+)", url)
            if m:
                dashboard_id = m.group(1)
                summary["dashboard_id"] = dashboard_id
                session.manifest["dashboard_id"] = dashboard_id
                session.manifest["dashboard_url"] = url
        except Exception:
            pass

        # ---- Add cards ----
        pipeline_id = (session.manifest.get("pipeline") or {}).get("id", "")
        cards_to_add = [
            ("Deal pipeline by stage",
             "Pipelines -> select Shipperz pipeline" + (f" ({pipeline_id})" if pipeline_id else ""),
             "deal_pipeline_by_stage"),
            ("Tickets by status (last 30 days)",
             "Tickets -> Status -> last 30 days", "tickets_by_status"),
            ("Contacts created (last 90 days)",
             "Contacts -> Create date -> last 90 days", "contacts_created"),
            ("Marketing email performance",
             "Marketing -> Email opens / clicks", "email_performance"),
            ("NPS score distribution",
             "Custom report -> NPS property -> bar chart", "nps_distribution"),
            ("Quote-request event volume",
             "Custom report -> shipperz_quote_requested over time",
             "quote_request_events"),
        ]

        for idx, (card_label, library_hint, card_key) in enumerate(cards_to_add, start=1):
            label = f"05-{idx:02d}-add-{card_key}"
            try:
                with _step(session, label, dashboards_url,
                           f"On the dashboard, click 'Add report' and search the library for: {card_label}. {library_hint}."):
                    # GUESSED: 'Add report' is the most common entry point.
                    clicked = False
                    for entry in ("Add report", "Add card", "Add", "+ Add report"):
                        try:
                            _click_text(session, entry, timeout_ms=5_000)
                            clicked = True
                            break
                        except Exception:
                            continue
                    if not clicked:
                        raise TimeoutError("'Add report' entry not found")

                    # Use the report-library search.
                    try:
                        page.get_by_placeholder("Search").first.fill(
                            card_label, timeout=5_000)
                    except Exception:
                        try:
                            page.keyboard.type(card_label)
                        except Exception:
                            pass

                    # Pick first result.
                    try:
                        _click_text(session, card_label, timeout_ms=5_000)
                    except Exception:
                        # Fallback: click the first result tile by index.
                        try:
                            page.locator("[role='option']").first.click(timeout=5_000)
                        except Exception:
                            raise TimeoutError(
                                f"No library result matched {card_label!r}")

                    # Confirm add.
                    for confirm in ("Add to dashboard", "Save", "Add"):
                        try:
                            _click_text(session, confirm, timeout_ms=3_000)
                            break
                        except Exception:
                            continue
                    summary["cards_added"].append(card_key)
            except _StepFailed:
                # Non-fatal — keep going so we still get a partial dashboard.
                _warn(f"card '{card_key}' skipped; logged as manual step")
                continue

        session.save_manifest()

    summary["card_count"] = len(summary["cards_added"])
    # Builder expects status + dashboard_url keys (Codex finding).
    summary["status"] = "ok" if summary.get("dashboard_id") else "error"
    if summary.get("dashboard_id") and not summary.get("dashboard_url"):
        summary["dashboard_url"] = (
            f"https://app.hubspot.com/reports-dashboard/{portal_id}/dashboard/"
            f"{summary['dashboard_id']}"
        )
    _ok(
        f"create_starter_dashboard done: id={summary['dashboard_id']} "
        f"cards={summary['card_count']}"
    )
    return summary


# ----------------------------------------------------------------------------
# Flow 2: create_saved_views
# ----------------------------------------------------------------------------

# Definitions for the three saved views. Captured here so they're easy to
# tweak without surgery on the flow code.
_SAVED_VIEWS: list[dict[str, Any]] = [
    {
        "key": "hot_leads",
        "name": "Hot Leads",
        "object": "contacts",
        "object_id": "0-1",
        "url_segment": "contacts",
        "filter_summary": "demo_lead_score >= 50",
        "filter_property": "demo_lead_score",
        "filter_operator": "is greater than or equal to",
        "filter_value": "50",
        "sort_property": "demo_lead_score",
        "sort_descending": True,
    },
    {
        "key": "open_quotes",
        "name": "Open Quotes",
        "object": "deals",
        "object_id": "0-3",
        "url_segment": "contacts",  # HubSpot deals list lives under /contacts/{portal}/objects/0-3/
        "filter_summary": "pipeline = Shipperz AND stage in (Quote Requested, Quote Sent, Negotiating)",
        "filter_property": "dealstage",
        "filter_operator": "is any of",
        "filter_value": "Quote Requested|Quote Sent|Negotiating",
        "sort_property": "amount",
        "sort_descending": True,
    },
    {
        "key": "needs_reply",
        "name": "Needs Reply",
        "object": "tickets",
        "object_id": "0-5",
        "url_segment": "contacts",  # /contacts/{portal}/objects/0-5/
        "filter_summary": "status = New OR pipeline_stage = Waiting on contact",
        "filter_property": "hs_pipeline_stage",
        "filter_operator": "is any of",
        "filter_value": "New|Waiting on contact",
        "sort_property": "createdate",
        "sort_descending": False,
    },
]


def create_saved_views(slug: str, portal_id: str, work_dir: str | None = None,
                       env_path: str | None = None) -> dict[str, Any]:
    """
    Create the three private saved views. Records {key: {id, url}} into
    manifest['saved_views'].
    """
    work_dir = work_dir or f"/tmp/demo-prep-{slug}"
    summary: dict[str, Any] = {"flow": "create_saved_views", "slug": slug,
                               "views": {}}

    try:
        session_cm = PlaywrightSession(slug=slug, portal_id=portal_id)
    except Exception as e:  # noqa: BLE001
        _fail(f"PlaywrightSession init failed: {e}")
        return {**summary, "error": f"session-init: {e}"}

    with session_cm as session:
        page = session.page
        portal = session.portal_id
        if page is None:
            _fail("page is None — Playwright failed to launch")
            return {**summary, "error": "page-init-none"}

        if "saved_views" not in session.manifest:
            session.manifest["saved_views"] = {}

        for view in _SAVED_VIEWS:
            list_url = (
                f"https://app.hubspot.com/{view['url_segment']}/{portal}/"
                f"objects/{view['object_id']}/views/all/list"
            )
            manual_instructions = (
                f"Open the {view['object']} list, click 'Add filter', filter "
                f"{view['filter_summary']}, sort by {view['sort_property']} "
                f"({'desc' if view['sort_descending'] else 'asc'}), then "
                f"click 'Save view as' -> private -> name it '{view['name']}'."
            )
            label_prefix = f"sv-{view['key']}"

            # ---- Navigate to the list ----
            try:
                with _step(session, f"{label_prefix}-01-nav", list_url,
                           manual_instructions):
                    page.goto(list_url, timeout=30_000)
                    page.wait_for_load_state("domcontentloaded")
            except _StepFailed:
                continue

            # ---- Apply filter ----
            try:
                with _step(session, f"{label_prefix}-02-filter", list_url,
                           manual_instructions):
                    # GUESSED: HubSpot's list filter button is "Advanced filters"
                    # or "Add filter" depending on object. Try both.
                    opened = False
                    for label in ("Advanced filters", "Add filter", "Filter"):
                        try:
                            _click_text(session, label, timeout_ms=5_000)
                            opened = True
                            break
                        except Exception:
                            continue
                    if not opened:
                        raise TimeoutError("filter panel did not open")

                    # Search for the property.
                    try:
                        page.get_by_placeholder("Search properties").first.fill(
                            view["filter_property"], timeout=5_000)
                    except Exception:
                        page.keyboard.type(view["filter_property"])
                    _click_text(session, view["filter_property"],
                                timeout_ms=5_000)

                    # Choose operator.
                    try:
                        _click_text(session, view["filter_operator"],
                                    timeout_ms=5_000)
                    except Exception:
                        pass  # operator may be default for some property types

                    # Enter value(s) — for "is any of" pipe-split into chips.
                    if "|" in view["filter_value"]:
                        for chip in view["filter_value"].split("|"):
                            page.keyboard.type(chip)
                            page.keyboard.press("Enter")
                    else:
                        try:
                            page.get_by_label("Value").fill(
                                view["filter_value"], timeout=5_000)
                        except Exception:
                            page.keyboard.type(view["filter_value"])

                    # Apply.
                    for label in ("Apply filter", "Apply", "Done"):
                        try:
                            _click_text(session, label, timeout_ms=3_000)
                            break
                        except Exception:
                            continue
            except _StepFailed:
                continue

            # ---- Save view ----
            try:
                with _step(session, f"{label_prefix}-03-save", list_url,
                           manual_instructions):
                    saved = False
                    for label in ("Save view as", "Save view", "Save as new view",
                                  "Save"):
                        try:
                            _click_text(session, label, timeout_ms=5_000)
                            saved = True
                            break
                        except Exception:
                            continue
                    if not saved:
                        raise TimeoutError("'Save view' button not found")

                    # Name the view.
                    try:
                        _fill_label(session, "View name", view["name"],
                                    timeout_ms=5_000)
                    except Exception:
                        try:
                            _fill_label(session, "Name", view["name"],
                                        timeout_ms=5_000)
                        except Exception:
                            page.keyboard.type(view["name"])

                    # Make it private.
                    try:
                        _click_text(session, "Private", timeout_ms=3_000)
                    except Exception:
                        try:
                            _click_text(session, "Only me", timeout_ms=3_000)
                        except Exception:
                            pass  # Private may already be the default

                    # Confirm.
                    for label in ("Save", "Create view", "Done"):
                        try:
                            _click_text(session, label, timeout_ms=3_000)
                            break
                        except Exception:
                            continue
            except _StepFailed:
                continue

            # Capture URL + view id from current page URL.
            try:
                url = page.url
                m = re.search(r"/views/(\d+)/", url) or re.search(r"viewId=(\d+)", url)
                view_id = m.group(1) if m else None
                summary["views"][view["key"]] = {"id": view_id, "url": url,
                                                 "name": view["name"]}
                session.manifest["saved_views"][view["key"]] = {
                    "id": view_id, "url": url, "name": view["name"],
                    "object": view["object"],
                }
            except Exception:
                pass

        session.save_manifest()

    # Builder expects "saved_views" key, not "views" (Codex finding).
    summary["saved_views"] = summary.get("views", {})
    summary["status"] = "ok" if summary["saved_views"] else "error"
    _ok(f"create_saved_views done: {len(summary['saved_views'])} views")
    return summary


# ----------------------------------------------------------------------------
# Module re-exports
# ----------------------------------------------------------------------------

  # 're' is now imported at the top of the file (was previously imported here at module bottom — risky for cold-import callers).

__all__ = ["create_starter_dashboard", "create_saved_views",
           "PlaywrightSession"]
