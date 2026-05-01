#!/usr/bin/env bash
# Research the target company. Outputs /tmp/demo-prep-<slug>/research.json.
# Runs Firecrawl, Playwright screenshot, and Perplexity IN PARALLEL.
# Caches research.json for 24h per slug; pass --no-cache to force re-fetch.
#
# Usage: 01-research.sh <slug> <url-or-domain> ["stated context"] [--no-cache]

source "$(dirname "$0")/lib.sh"
load_env

# Parse args (accept --no-cache anywhere)
NO_CACHE=0
ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--no-cache" ]]; then
    NO_CACHE=1
  else
    ARGS+=("$arg")
  fi
done

SLUG="${ARGS[0]:-}"
URL="${ARGS[1]:-}"
CONTEXT="${ARGS[2]:-}"
[[ -n "$SLUG" && -n "$URL" ]] || fail "Usage: 01-research.sh <slug> <url> [\"context\"] [--no-cache]"

WORK="$(work_dir "$SLUG")"

# ---- Cache check (24h TTL) ----
RESEARCH_OUT="$WORK/research.json"
if [[ "$NO_CACHE" -eq 0 && -f "$RESEARCH_OUT" ]]; then
  AGE_SECONDS=$(( $(date +%s) - $(stat -f %m "$RESEARCH_OUT" 2>/dev/null || stat -c %Y "$RESEARCH_OUT" 2>/dev/null || echo 0) ))
  AGE_HOURS=$(( AGE_SECONDS / 3600 ))
  if [[ "$AGE_SECONDS" -lt 86400 ]]; then
    ok "Using cached research (${AGE_HOURS}h old): $RESEARCH_OUT"
    info "  Pass --no-cache to force a fresh fetch."
    exit 0
  else
    info "Cached research is ${AGE_HOURS}h old (>24h); re-fetching."
  fi
fi

# Normalize URL
if [[ "$URL" != http* ]]; then
  URL="https://$URL"
fi
DOMAIN=$(echo "$URL" | /usr/bin/sed -E 's|^https?://([^/]+).*|\1|; s|^www\.||')

info "Researching $URL"
info "Domain: $DOMAIN"
info "Context: ${CONTEXT:-(none)}"

FIRECRAWL_OUT="$WORK/firecrawl.json"
SCREENSHOT="$WORK/homepage.png"
DOM_DUMP="$WORK/dom.json"
PERPLEXITY_OUT="$WORK/perplexity.json"
LOGO_OUT="$WORK/logo.png"

# ---- Build the Playwright script up-front so it's ready to launch ----
cat > "$WORK/playwright-script.js" <<EOF
const { chromium } = require('playwright');
(async () => {
  const url = process.env.DEMO_PREP_URL;
  const screenshotPath = process.env.DEMO_PREP_SCREENSHOT;
  const domDumpPath = process.env.DEMO_PREP_DOM_DUMP;
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  try {
    await page.goto(url, { timeout: 30000, waitUntil: 'networkidle' });
    await page.screenshot({ path: screenshotPath, fullPage: false });

    const data = await page.evaluate(() => {
      const fav = document.querySelector('link[rel="icon"], link[rel="shortcut icon"]')?.href;
      const ogImg = document.querySelector('meta[property="og:image"]')?.content;
      const themeColor = document.querySelector('meta[name="theme-color"]')?.content;
      const computed = getComputedStyle(document.body);
      const colors = new Set([themeColor].filter(Boolean));

      ['header', 'nav', 'h1', 'h2', '.btn', 'button', 'a'].forEach(sel => {
        document.querySelectorAll(sel).forEach(el => {
          const cs = getComputedStyle(el);
          if (cs.color) colors.add(cs.color);
          if (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)') colors.add(cs.backgroundColor);
        });
      });

      return {
        title: document.title,
        description: document.querySelector('meta[name="description"]')?.content || '',
        ogTitle: document.querySelector('meta[property="og:title"]')?.content || '',
        favicon: fav,
        ogImage: ogImg,
        themeColor,
        colors: [...colors].slice(0, 15),
        h1: document.querySelector('h1')?.innerText?.trim() || '',
        firstParagraphs: Array.from(document.querySelectorAll('p')).slice(0, 3).map(p => p.innerText.trim()).filter(t => t.length > 20)
      };
    });
    require('fs').writeFileSync(domDumpPath, JSON.stringify(data, null, 2));
    console.log('OK');
  } catch (e) {
    console.error('Playwright failed:', e.message);
    require('fs').writeFileSync(domDumpPath, JSON.stringify({ error: e.message }));
  }
  await browser.close();
})();
EOF

# ---- Launch all three research sources in parallel ----
info "Launching Firecrawl + Playwright + Perplexity in parallel..."

FIRECRAWL_PID=""
if command -v ~/.claude/bin/firecrawl >/dev/null; then
  ( ~/.claude/bin/firecrawl scrape "$URL" --formats markdown > "$FIRECRAWL_OUT" 2>&1 ) &
  FIRECRAWL_PID=$!
else
  warn "  Firecrawl wrapper not installed, skipping"
fi

PLAYWRIGHT_PID=""
if node -e "require.resolve('playwright')" >/dev/null 2>&1; then
  ( DEMO_PREP_URL="$URL" DEMO_PREP_SCREENSHOT="$SCREENSHOT" DEMO_PREP_DOM_DUMP="$DOM_DUMP" \
      node "$WORK/playwright-script.js" > "$WORK/playwright.log" 2>&1 ) &
  PLAYWRIGHT_PID=$!
else
  warn "  Playwright not available, skipping screenshot"
fi

# ---- Always-on Playwright logo screenshot (Fix F-research, 2026-04-26) ----
# Jeremy's spec: always run Playwright for the logo. Don't trust Firecrawl's
# branding pull — it returns og:image which is often a hero photo, not a
# transparent logo. The marketing email + doc + form all reference this
# logo path, so its reliability is load-bearing for "feels brand-consistent".
LOGO_PID=""
if python3 -c "import playwright" >/dev/null 2>&1; then
  COMPANY_NAME_GUESS="$DOMAIN"
  ( python3 - "$URL" "$LOGO_OUT" "$COMPANY_NAME_GUESS" \
      > "$WORK/logo-playwright.log" 2>&1 <<'PY'
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]
out_path = sys.argv[2]
company_hint = (sys.argv[3] if len(sys.argv) > 3 else "").lower()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        print(f"PLAYWRIGHT_GOTO_FAIL: {exc}", file=sys.stderr)
        browser.close()
        sys.exit(2)

    # Priority: explicit alt-text logo > header anchor logo > nav logo >
    # .logo class > BEM-style header__logo > first img in header/nav >
    # alt matching company name. The first matching, visible element wins.
    selectors = [
        "header img[alt*='logo' i]",
        "header a[href='/'] img",
        "nav img[alt*='logo' i]",
        ".logo img",
        ".header__logo img",
        f"img[alt*='{company_hint}' i]" if company_hint else None,
        "header img:first-of-type",
        "nav img:first-of-type",
    ]
    selectors = [s for s in selectors if s]

    found = None
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                found = el
                break
        except Exception:
            continue

    try:
        if found:
            found.screenshot(path=out_path, omit_background=True)
            print(f"OK: logo saved to {out_path}", file=sys.stderr)
        else:
            # Fallback: top-left 400x120 region (most logos sit there).
            page.screenshot(
                path=out_path,
                clip={"x": 0, "y": 0, "width": 400, "height": 120},
            )
            print(f"FALLBACK: top-left region saved to {out_path}", file=sys.stderr)
    finally:
        browser.close()
PY
  ) &
  LOGO_PID=$!
else
  warn "  Python playwright not installed; logo will fall back to Firecrawl branding.logo_url if available"
fi

PERPLEXITY_PID=""
if command -v ~/.claude/bin/perplexity >/dev/null; then
  research_prompt="What does the company at $URL do, what's their target customer ICP, what industry are they in, and what are the most-cited pain points for businesses in their industry that don't have a marketing team / use HubSpot or similar CRM? Provide stats with citations. Context from the rep: $CONTEXT"
  ( ~/.claude/bin/perplexity "$research_prompt" > "$PERPLEXITY_OUT" 2>&1 ) &
  PERPLEXITY_PID=$!
else
  warn "  Perplexity wrapper not installed, skipping"
fi

# Wait for each, report status
if [[ -n "$FIRECRAWL_PID" ]]; then
  if wait "$FIRECRAWL_PID"; then
    if grep -q '"success":true' "$FIRECRAWL_OUT" 2>/dev/null; then
      ok "  Firecrawl returned data"
    else
      warn "  Firecrawl did not succeed (DNS / 404 / etc); will fall back to Playwright/Perplexity output"
    fi
  else
    warn "  Firecrawl returned non-zero"
  fi
fi

if [[ -n "$PLAYWRIGHT_PID" ]]; then
  wait "$PLAYWRIGHT_PID" || warn "  Playwright execution failed"
  if [[ -f "$SCREENSHOT" ]]; then
    ok "  Screenshot saved: $SCREENSHOT"
  else
    warn "  No screenshot; site may be JS-blocked or DNS-failed"
  fi
fi

if [[ -n "$PERPLEXITY_PID" ]]; then
  wait "$PERPLEXITY_PID" || warn "  Perplexity returned non-zero"
  if [[ -s "$PERPLEXITY_OUT" ]]; then
    ok "  Perplexity returned data"
  fi
fi

if [[ -n "$LOGO_PID" ]]; then
  wait "$LOGO_PID" || warn "  Playwright logo capture returned non-zero"
  if [[ -f "$LOGO_OUT" ]]; then
    ok "  Logo saved: $LOGO_OUT"
  else
    warn "  Logo capture produced no file; will fall back to Firecrawl branding"
  fi
fi

# ---- Consolidate ----
info "Consolidating research..."

export DEMO_PREP_WORK="$WORK"
export DEMO_PREP_SLUG="$SLUG"
export DEMO_PREP_URL="$URL"
export DEMO_PREP_DOMAIN="$DOMAIN"
export DEMO_PREP_CONTEXT="$CONTEXT"

python3 - <<'PYEOF'
import json, os, re

work = os.environ["DEMO_PREP_WORK"]
slug = os.environ["DEMO_PREP_SLUG"]
url = os.environ["DEMO_PREP_URL"]
domain = os.environ["DEMO_PREP_DOMAIN"]
context = os.environ.get("DEMO_PREP_CONTEXT", "")

# Firecrawl
firecrawl = {}
fc_path = f"{work}/firecrawl.json"
if os.path.exists(fc_path):
    try:
        firecrawl = json.load(open(fc_path)).get('data', {})
    except Exception:
        firecrawl = {}

# Playwright DOM
dom = {}
dom_path = f"{work}/dom.json"
if os.path.exists(dom_path):
    try:
        dom = json.load(open(dom_path))
    except Exception:
        dom = {}

# Perplexity
perplexity = {}
pp_path = f"{work}/perplexity.json"
if os.path.exists(pp_path):
    try:
        perplexity = json.load(open(pp_path))
    except Exception:
        perplexity = {'raw': open(pp_path).read()}

# Extract brand colors. Prefer Firecrawl theme-color, fall back to Playwright
def normalize_color(c):
    c = c.strip()
    if c.startswith('#'):
        return c
    m = re.match(r'rgba?\(([0-9,\s]+)\)', c)
    if m:
        parts = [int(x.strip()) for x in m.group(1).split(',')[:3]]
        return '#{:02x}{:02x}{:02x}'.format(*parts).upper()
    return c

colors = []
fc_meta = firecrawl.get('metadata', {})
if fc_meta.get('theme-color'):
    colors.append(normalize_color(fc_meta['theme-color']))
for c in dom.get('colors', []):
    n = normalize_color(c)
    if n.startswith('#') and n not in colors and len(colors) < 5:
        colors.append(n)

def is_gray(hex_c):
    if not hex_c.startswith('#') or len(hex_c) < 7:
        return True
    r, g, b = int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)
    return abs(r - g) < 20 and abs(g - b) < 20

primary = next((c for c in colors if not is_gray(c)), colors[0] if colors else '#FF7A59')
secondary = next((c for c in colors if c != primary and not is_gray(c)), '#33475B')
accent = next((c for c in colors if c not in (primary, secondary) and not is_gray(c)), '#00BDA5')

logo_url = fc_meta.get('og:image') or fc_meta.get('twitter:image') or dom.get('ogImage') or dom.get('favicon') or ''
company_name = (fc_meta.get('og:title') or fc_meta.get('title') or dom.get('ogTitle') or dom.get('title') or domain).split('|')[0].split('-')[0].strip()
description = fc_meta.get('description') or fc_meta.get('og:description') or dom.get('description') or ''

sources = [url]
if perplexity.get('citations'):
    sources.extend(perplexity['citations'])

# Logo path (Fix F-research, 2026-04-26). Always-on Playwright capture lands
# at {work}/logo.png. Phase 2 reads this path and copies it into
# plan["branding"]["logo_path"] so builder.py can upload to HubSpot Files.
# If Playwright logo capture didn't produce a file, we leave `logo_path` null
# and builder.py falls back to skipping the logo strip (no broken image).
logo_path = f"{work}/logo.png" if os.path.exists(f"{work}/logo.png") else None

research = {
    'url': url,
    'domain': domain,
    'company': {
        'name': company_name,
        'domain': domain,
        'description': description[:500],
        'h1': dom.get('h1', ''),
        'first_paragraphs': dom.get('firstParagraphs', [])
    },
    'branding': {
        'primary_color': primary,
        'secondary_color': secondary,
        'accent_color': accent,
        'all_colors': colors,
        'logo_url': logo_url,                              # remote URL from og:image / favicon
        'logo_path': logo_path,                            # local Playwright screenshot path
        'screenshot_path': f"{work}/homepage.png" if os.path.exists(f"{work}/homepage.png") else None
    },
    'firecrawl_markdown_excerpt': (firecrawl.get('markdown') or '')[:3000],
    'perplexity': perplexity,
    'stated_context': context,
    'sources': sources,
    'summary': '',
    'industry_stats': []
}

with open(f"{work}/research.json", 'w') as f:
    json.dump(research, f, indent=2, default=str)
print(f"Research consolidated: {work}/research.json")
PYEOF

ok "Research complete: $WORK/research.json"
