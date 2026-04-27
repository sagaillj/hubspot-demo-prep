#!/usr/bin/env bash
# Generate the final Google Doc output (or local Markdown fallback).
#
# Usage: 08-output.sh <customer-slug>

source "$(dirname "$0")/lib.sh"
load_env

SLUG="${1:-}"
[[ -n "$SLUG" ]] || fail "Usage: 08-output.sh <slug>"

WORK="$(work_dir "$SLUG")"
PLAN="$WORK/build-plan.json"
MANIFEST="$WORK/manifest.json"
RESEARCH="$WORK/research.json"
PORTAL=$(sandbox_portal_id)

# Build the HTML version of the doc (Drive auto-converts HTML → native GDoc).
HTML_OUT="$WORK/demo-doc.html"

python3 - "$PLAN" "$MANIFEST" "$RESEARCH" "$WORK/manual-steps.json" "$HTML_OUT" "$SLUG" "$PORTAL" <<'PYEOF'
import json, os, sys, html, datetime

plan_path, manifest_path, research_path, ms_path, html_out, slug, portal = sys.argv[1:]

plan = json.load(open(plan_path))
manifest = json.load(open(manifest_path))
research = json.load(open(research_path))
manual_steps = json.load(open(ms_path)) if os.path.exists(ms_path) else []

company_name = manifest.get('company', {}).get('name', plan.get('company', {}).get('name', 'Unknown'))
brand = research.get('branding', {})
primary = brand.get('primary_color', '#FF7A59')
secondary = brand.get('secondary_color', '#33475B')
accent = brand.get('accent_color', '#00BDA5')
logo_url = brand.get('logo_url', '')

agenda = plan.get('agenda', [])
easter_egg = plan.get('easter_egg', {})
date = datetime.date.today().isoformat()

def link(text, url):
    return f'<a href="{html.escape(url)}" target="_blank">{html.escape(text)}</a>'

def kv_link(category, key, label_override=None):
    cat = manifest.get(category, {})
    if isinstance(cat, dict) and key in cat:
        url = cat.get(key, '')
        if url and url.startswith('http'):
            return link(label_override or key, url)
    return ''

# ---- Build HTML ----
parts = []
parts.append(f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<title>HubSpot Demo Prep — {html.escape(company_name)} — {date}</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; color: #333; line-height: 1.5; }}
  h1 {{ color: {primary}; border-bottom: 3px solid {primary}; padding-bottom: 8px; }}
  h2 {{ color: {secondary}; margin-top: 32px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  h3 {{ color: {primary}; }}
  .easter-egg {{ background: {primary}10; border-left: 4px solid {primary}; padding: 12px 16px; margin: 16px 0; }}
  .easter-egg h3 {{ margin-top: 0; }}
  .swatch {{ display: inline-block; width: 40px; height: 40px; border-radius: 4px; vertical-align: middle; margin-right: 6px; border: 1px solid #ddd; }}
  .swatch-label {{ display: inline-block; vertical-align: middle; font-family: monospace; font-size: 12px; color: #666; margin-right: 16px; }}
  .agenda-item {{ margin: 16px 0; padding: 12px; background: #fafafa; border-radius: 4px; }}
  .agenda-item .why {{ color: #666; font-style: italic; margin-top: 4px; }}
  .agenda-item .stat {{ color: {accent}; font-weight: bold; margin-top: 8px; font-size: 14px; }}
  .stat-cite {{ color: #999; font-size: 11px; }}
  .manual-steps {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px 16px; }}
  ul {{ padding-left: 20px; }}
  li {{ margin: 4px 0; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 32px 0; }}
  .meta {{ color: #999; font-size: 12px; }}
  code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 12px; }}
</style></head><body>''')

parts.append(f'<h1>HubSpot Demo Prep — {html.escape(company_name)}</h1>')
parts.append(f'<p class="meta">Demo date: {date}  ·  Sandbox: {portal}  ·  Slug: <code>{slug}</code></p>')

# Brand strip
parts.append('<h2>Brand</h2>')
if logo_url:
    parts.append(f'<p><img src="{html.escape(logo_url)}" alt="{html.escape(company_name)} logo" style="max-width:300px;max-height:120px"></p>')
swatch_html = ''
for label, hex_val in [('Primary', primary), ('Secondary', secondary), ('Accent', accent)]:
    swatch_html += f'<span class="swatch" style="background:{hex_val}"></span><span class="swatch-label">{label} {hex_val}</span> '
parts.append(f'<p>{swatch_html}</p>')

# Agenda
parts.append('<h2>Demo agenda</h2>')
for i, item in enumerate(agenda, 1):
    title = html.escape(item.get('title', f'Item {i}'))
    why = html.escape(item.get('why', ''))
    show_url = item.get('show_url', '')
    show_label = item.get('show_label', 'open in HubSpot')
    stat = item.get('stat', '')
    stat_cite = item.get('stat_cite', '')

    parts.append('<div class="agenda-item">')
    parts.append(f'<h3>{i}. {title}</h3>')
    if why:
        parts.append(f'<p class="why">Why for {html.escape(company_name)}: {why}</p>')
    if show_url:
        parts.append(f'<p>What to show: {link(show_label, show_url)}</p>')
    if stat:
        cite_part = f' <span class="stat-cite">— <a href="{html.escape(stat_cite)}">source</a></span>' if stat_cite else ''
        parts.append(f'<p class="stat">📊 {html.escape(stat)}{cite_part}</p>')
    parts.append('</div>')

# Easter egg
if easter_egg:
    parts.append('<div class="easter-egg">')
    parts.append(f'<h3>★ Easter egg — {html.escape(easter_egg.get("title", ""))}</h3>')
    why = easter_egg.get('why', '')
    if why:
        parts.append(f'<p class="why">{html.escape(why)}</p>')
    show_url = easter_egg.get('show_url', '')
    show_label = easter_egg.get('show_label', 'open in HubSpot')
    if show_url:
        parts.append(f'<p>What to show: {link(show_label, show_url)}</p>')
    stat = easter_egg.get('stat', '')
    if stat:
        cite = easter_egg.get('stat_cite', '')
        cite_part = f' <span class="stat-cite">— <a href="{html.escape(cite)}">source</a></span>' if cite else ''
        parts.append(f'<p class="stat">📊 {html.escape(stat)}{cite_part}</p>')
    parts.append('</div>')

# What was built
parts.append('<h2>What was built in your demo portal</h2>')

if 'company' in manifest:
    company_link = manifest['company'].get('url', '')
    parts.append(f'<p><strong>Company:</strong> {link(company_name, company_link)}</p>')

if 'contacts' in manifest:
    parts.append(f'<p><strong>Contacts ({len(manifest["contacts"])}):</strong></p><ul>')
    for email, cid in list(manifest['contacts'].items())[:10]:
        url = f'https://app.hubspot.com/contacts/{portal}/record/0-1/{cid}'
        parts.append(f'<li>{link(email, url)}</li>')
    parts.append('</ul>')

if 'pipeline' in manifest:
    pn = manifest['pipeline'].get('name', 'pipeline')
    pu = manifest['pipeline'].get('url', '')
    parts.append(f'<p><strong>Deal pipeline:</strong> {link(pn, pu)}</p>')

if 'deals' in manifest:
    parts.append(f'<p><strong>Deals ({len(manifest["deals"])}):</strong></p><ul>')
    for name, did in manifest['deals'].items():
        url = f'https://app.hubspot.com/contacts/{portal}/record/0-3/{did}'
        parts.append(f'<li>{link(name, url)}</li>')
    parts.append('</ul>')

if 'tickets' in manifest:
    parts.append(f'<p><strong>Tickets ({len(manifest["tickets"])}):</strong></p><ul>')
    for name, tid in manifest['tickets'].items():
        url = f'https://app.hubspot.com/contacts/{portal}/record/0-5/{tid}'
        parts.append(f'<li>{link(name, url)}</li>')
    parts.append('</ul>')

if 'activity' in manifest:
    lvl = manifest['activity'].get('level', '?')
    days = manifest['activity'].get('backdate_days', '?')
    parts.append(f'<p><strong>Activity timeline:</strong> {lvl} level, backdated {days} days. Open any contact above to see the timeline.</p>')

if 'custom_object' in manifest:
    co_name = manifest['custom_object'].get('name', '')
    co_url = manifest['custom_object'].get('url', '')
    parts.append(f'<p><strong>Custom object:</strong> {link(co_name, co_url)}</p>')

if 'custom_events' in manifest:
    parts.append(f'<p><strong>Custom events:</strong> {len(manifest["custom_events"])} event types defined and fired across contacts.</p>')

if 'forms' in manifest:
    parts.append('<p><strong>Forms:</strong></p><ul>')
    for fname, fguid in manifest['forms'].items():
        url = f'https://app.hubspot.com/forms/{portal}/editor/{fguid}/edit/form'
        parts.append(f'<li>{link(fname, url)}</li>')
    parts.append('</ul>')

if 'marketing_email' in manifest:
    em = manifest['marketing_email']
    if em.get('url'):
        parts.append(f'<p><strong>Marketing email:</strong> {link(em.get("name", ""), em["url"])}</p>')

if 'landing_page' in manifest:
    lp = manifest['landing_page']
    if lp.get('url'):
        parts.append(f'<p><strong>Landing page:</strong> {link(lp.get("name", ""), lp["url"])}</p>')

if 'workflows' in manifest:
    parts.append('<p><strong>Workflows:</strong></p><ul>')
    for wname, wid in manifest['workflows'].items():
        wurl = manifest.get('workflow_urls', {}).get(wname, '')
        if wurl:
            parts.append(f'<li>{link(wname, wurl)}</li>')
        else:
            parts.append(f'<li>{html.escape(wname)} (id={wid})</li>')
    parts.append('</ul>')

if 'lead_scoring' in manifest:
    ls = manifest['lead_scoring']
    parts.append(f'<p><strong>Lead scoring:</strong> property <code>{ls.get("property", "")}</code>')
    if ls.get('list_url'):
        parts.append(f' · {link("Hot leads list", ls["list_url"])}')
    parts.append('</p>')

# Manual steps
if manual_steps:
    parts.append('<h2>⚠ Manual steps before demo</h2>')
    parts.append('<div class="manual-steps">')
    for s in manual_steps:
        parts.append(f'<p><strong>{html.escape(s["item"])}:</strong> {html.escape(s.get("instructions", ""))}<br>')
        parts.append(f'<span class="meta">Reason: {html.escape(s.get("reason", ""))}</span><br>')
        if s.get('ui_url'):
            parts.append(f'{link("Open UI", s["ui_url"])}</p>')
        else:
            parts.append('</p>')
    parts.append('</div>')

# Research summary
parts.append('<h2>Research summary</h2>')
summary = research.get('summary', '')
if summary:
    parts.append(f'<p>{html.escape(summary)}</p>')
sources = research.get('sources', [])
if sources:
    parts.append('<p><strong>Sources:</strong></p><ul>')
    for s in sources[:10]:
        parts.append(f'<li>{link(s, s)}</li>')
    parts.append('</ul>')

# Pre-demo checklist
parts.append('<h2>Pre-demo checklist</h2><ul>')
parts.append('<li>☐ Open one of the contacts above and verify timeline looks alive</li>')
parts.append(f'<li>☐ Open the deal pipeline ({link("here", manifest.get("pipeline", {}).get("url", ""))}) and confirm deal distribution</li>')
if 'workflows' in manifest:
    parts.append('<li>☐ Open at least one workflow and confirm the action graph</li>')
if 'lead_scoring' in manifest:
    parts.append('<li>☐ Open the hot leads list and verify scores rendered</li>')
if manual_steps:
    parts.append('<li>☐ Complete every manual UI step listed above</li>')
parts.append('</ul>')

# Cleanup
parts.append('<h2>Cleanup</h2>')
parts.append(f'<p>When done with this demo, run:</p>')
parts.append(f'<p><code>~/.claude/skills/hubspot-demo-prep/helpers/cleanup.sh --slug={slug}</code></p>')

parts.append('</body></html>')

with open(html_out, 'w') as f:
    f.write('\n'.join(parts))
print(f'HTML written to {html_out}', file=sys.stderr)
PYEOF

ok "Doc HTML written: $HTML_OUT"

# Upload to Drive (or fallback to local md)
info "Uploading to Drive..."
DOC_TITLE=$(python3 -c "
import json, datetime
m = json.load(open('$MANIFEST'))
name = m.get('company', {}).get('name', 'Unknown')
print(f'HubSpot Demo Prep — {name} — {datetime.date.today().isoformat()}')
")

# Read HTML, base64 it for Drive MCP create_file with mimeType: text/html
HTML_B64=$(base64 -i "$HTML_OUT" | tr -d '\n')

# Save b64 to file the MCP can pick up; the actual MCP call must happen in
# Claude Code orchestration layer (not bash). Persist the doc info for caller.
echo "$DOC_TITLE" > "$WORK/doc-title.txt"
echo "$HTML_B64" > "$WORK/doc-html-base64.txt"

ok "Doc payload ready at $WORK/doc-title.txt + $WORK/doc-html-base64.txt"
warn "The actual Drive upload happens via the Drive MCP tool — Claude must call:"
warn "  mcp__8a98d6d7-*-create_file with title=$DOC_TITLE, mimeType=text/html, content=<the b64 content>"
warn "  Read it from: $WORK/doc-html-base64.txt"

manifest_add "$SLUG" "_meta" "phase_4_output_done" "true"
manifest_add "$SLUG" "output" "doc_title" "$DOC_TITLE"
manifest_add "$SLUG" "output" "html_path" "$HTML_OUT"
