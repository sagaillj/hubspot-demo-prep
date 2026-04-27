#!/usr/bin/env bash
# Generate a marketing-email hero image via OpenAI gpt-image-1 OR Google Gemini imagen.
#
# This is the REST-API fallback path. The orchestrator's preferred path is the
# Recraft MCP tool (free tier, 30 credits/day, called directly from Claude).
# This script exists so the orchestrator (or anything running outside Claude
# Code) can shell out when the MCP path isn't available.
#
# Usage: 09-generate-hero.sh <provider> <slug>
#   <provider> = openai | gemini
#   <slug>     = e.g. boomer-mcloud (work dir: /tmp/demo-prep-<slug>/)
#
# Reads:    /tmp/demo-prep-<slug>/research.json
# Writes:   /tmp/demo-prep-<slug>/hero-image.png   (mode 644)
#           /tmp/demo-prep-<slug>/hero-image.log
# stdout:   absolute path to the generated PNG (so the caller can capture it)
# stderr:   progress logs and error messages
#
# Exits non-zero with a one-line stderr message on any failure (missing key,
# missing research.json, HTTP error, decode error, network error, etc.).
#
# Resolves lib.sh from the script's own directory, so it works from both
# ${CLAUDE_PLUGIN_ROOT}/skills/hubspot-demo-prep/helpers/ (plugin install) and
# ~/.claude/skills/hubspot-demo-prep/skills/hubspot-demo-prep/helpers/ (dev tree).

set -euo pipefail

# Distinct exit code so the orchestrator can detect "no provider configured"
# and fall back to a different provider rather than treating it as a network
# error. Matches sysexits.h EX_USAGE-adjacent conventions (64 = usage/config).
EX_NO_PROVIDER=64

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

# Local fail variant that exits with EX_NO_PROVIDER (64) instead of 1.
# lib.sh's `fail` hard-codes exit 1, so we inline the stderr-then-exit pattern
# here to keep the contract: one-line message to stderr, distinct non-zero exit.
fail_no_provider() {
  printf '%berr%b   %s\n' $'\033[31m' $'\033[0m' "$1" >&2
  exit "$EX_NO_PROVIDER"
}

# ---- Parse + validate args ----

PROVIDER="${1:-}"
SLUG="${2:-}"

[[ -n "$PROVIDER" ]] || fail "Usage: 09-generate-hero.sh <provider> <slug>  (provider = openai|gemini)"
[[ -n "$SLUG" ]]     || fail "Usage: 09-generate-hero.sh <provider> <slug>  (slug missing)"

case "$PROVIDER" in
  openai|gemini) ;;
  *) fail "Invalid provider '$PROVIDER'. Must be 'openai' or 'gemini'." ;;
esac

# ---- Required tools ----

command -v jq      >/dev/null || fail "jq is required but not installed."
command -v python3 >/dev/null || fail "python3 is required but not installed."
command -v curl    >/dev/null || fail "curl is required but not installed."

# ---- Paths ----

WORK="$(work_dir "$SLUG")"
RESEARCH="$WORK/research.json"
OUT_PNG="$WORK/hero-image.png"
LOG="$WORK/hero-image.log"

[[ -f "$RESEARCH" ]] || fail "Missing $RESEARCH. Run 01-research.sh first."

# Validate the entire JSON shape upfront. Without this, a malformed
# research.json would trip raw `jq` parse errors under `set -e` and dump a
# stack of red noise instead of the advertised one-line stderr contract.
if ! jq empty "$RESEARCH" 2>/dev/null; then
  fail "research.json is malformed JSON (path: $RESEARCH)"
fi

# ---- Provider key check ----

case "$PROVIDER" in
  openai)
    [[ -n "${OPENAI_API_KEY:-}" ]] || fail_no_provider "OPENAI_API_KEY not set in env (looked in \$HUBSPOT_DEMO_PREP_ENV / ~/.claude/api-keys.env). [exit $EX_NO_PROVIDER]"
    ;;
  gemini)
    # Accept either var name; normalize to GEMINI_API_KEY for downstream use.
    if [[ -z "${GEMINI_API_KEY:-}" && -n "${GOOGLE_AI_STUDIO_KEY:-}" ]]; then
      GEMINI_API_KEY="$GOOGLE_AI_STUDIO_KEY"
    fi
    [[ -n "${GEMINI_API_KEY:-}" ]] || fail_no_provider "Neither GEMINI_API_KEY nor GOOGLE_AI_STUDIO_KEY set in env. [exit $EX_NO_PROVIDER]"
    ;;
esac

# ---- Extract prompt inputs from research.json ----

# Be permissive: research.json shape comes from 01-research.sh, but pain points
# live in the free-form `perplexity` blob. Use jq with safe fallbacks so a
# missing field never breaks prompt construction.

# Each extraction uses `// "default"` so a missing key produces a sane
# default rather than an empty string silently propagating into the prompt.
# Defense-in-depth: also reject literal-string "null" and empty results.
COMPANY="$(jq -r '(.company.name // .domain // "the company") | tostring' "$RESEARCH")"
[[ -z "$COMPANY" || "$COMPANY" == "null" ]] && COMPANY="the company"

INDUSTRY="$(jq -r '
  (
    .company.industry
    // (.perplexity.industry // empty)
    // (.stated_context | select(. != null and . != "") )
    // "professional services"
  ) | tostring
' "$RESEARCH")"
[[ -z "$INDUSTRY" || "$INDUSTRY" == "null" ]] && INDUSTRY="professional services"

PRIMARY_HEX="$(jq -r '(.branding.primary_color // "#0070F0") | tostring' "$RESEARCH")"
[[ -z "$PRIMARY_HEX" || "$PRIMARY_HEX" == "null" ]] && PRIMARY_HEX="#0070F0"

SECONDARY_HEX="$(jq -r '(.branding.secondary_color // "#1A1A1A") | tostring' "$RESEARCH")"
[[ -z "$SECONDARY_HEX" || "$SECONDARY_HEX" == "null" ]] && SECONDARY_HEX="#1A1A1A"

# Pain-point hint: prefer an explicit pain_points array, else first sentence
# from perplexity raw text mentioning "pain", else fall back to a generic
# industry-themed cue.
PAIN_HINT="$(jq -r '
  if (.perplexity.pain_points? | type == "array" and length > 0) then
    .perplexity.pain_points[0]
  elif (.pain_points? | type == "array" and length > 0) then
    .pain_points[0]
  else
    (
      (.perplexity.raw // "")
      | capture("(?<s>[^.]*\\b[Pp]ain[^.]*\\.)"; "g")
      | .s
    ) // empty
  end
' "$RESEARCH" 2>/dev/null || true)"

# Strip newlines / collapse whitespace; cap length so the prompt stays sane.
PAIN_HINT="$(printf '%s' "$PAIN_HINT" | tr '\n' ' ' | sed 's/  */ /g' | cut -c1-240)"
if [[ -z "$PAIN_HINT" || "$PAIN_HINT" == "null" ]]; then
  PAIN_HINT="A modern professional working environment relevant to the ${INDUSTRY} industry"
fi

PROMPT="Hero image for a marketing email to ${COMPANY}'s customers. Industry: ${INDUSTRY}. Brand colors: primary ${PRIMARY_HEX}, secondary ${SECONDARY_HEX}. Visual concept: ${PAIN_HINT}. Photorealistic, modern, no text overlay, 1200x600 aspect ratio."

info "Provider: $PROVIDER"
info "Company:  $COMPANY"
info "Industry: $INDUSTRY"
info "Colors:   $PRIMARY_HEX / $SECONDARY_HEX"
info "Prompt:   $(printf '%s' "$PROMPT" | cut -c1-160)..."

# ---- Initialize log ----

{
  printf '=== hero-image generation ===\n'
  printf 'timestamp: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'provider:  %s\n' "$PROVIDER"
  printf 'slug:      %s\n' "$SLUG"
  printf 'company:   %s\n' "$COMPANY"
  printf 'industry:  %s\n' "$INDUSTRY"
  printf 'primary:   %s\n' "$PRIMARY_HEX"
  printf 'secondary: %s\n' "$SECONDARY_HEX"
  printf 'prompt:    %s\n' "$PROMPT"
} > "$LOG"

# ---- Helpers ----

# Decode a base64 string (read from stdin) to a file. Uses python3 stdlib only
# so we don't depend on either the macOS or GNU `base64` flavor.
decode_b64_to_file() {
  local out="$1"
  python3 -c '
import sys, base64
data = sys.stdin.read()
# Strip whitespace/newlines that curl/jq may have introduced.
data = "".join(data.split())
sys.stdout.buffer.write(base64.b64decode(data))
' > "$out"
}

# Validate that a response body file is parseable JSON. Guards against
# providers returning HTTP 200 with HTML/text payloads (captive portals,
# maintenance pages, error pages without 4xx codes). Calls `fail` on mismatch.
# Args: <provider-name> <http-code> <response-body-file>
require_json_response() {
  local provider="$1" code="$2" body_file="$3"
  if ! jq empty "$body_file" 2>/dev/null; then
    local preview
    preview="$(head -c 200 "$body_file" | tr '\n' ' ' | tr -s ' ')"
    fail "$provider returned HTTP $code but body is not valid JSON (first 200 chars: $preview)"
  fi
}

# Verify the on-disk bytes are an actual PNG by checking the 8-byte magic
# signature. Hard-fails with a descriptive message naming the actual format
# detected (JPEG/WebP/GIF/unknown) so the orchestrator can decide whether to
# retry. We deliberately do NOT convert formats — that would add an
# ImageMagick dependency and silently produce a wrong-named file.
# Args: <output-png-path>
require_png_bytes() {
  local out_path="$1"
  local magic actual_format
  # 8 bytes hex-encoded uppercase, no whitespace. xxd is on macOS + Linux.
  magic="$(head -c 8 "$out_path" | xxd -p -u | tr -d '\n')"
  if [[ ! "$magic" =~ ^89504E470D0A1A0A ]]; then
    if [[ "$magic" =~ ^FFD8FF ]]; then
      actual_format="JPEG"
    elif [[ "$magic" =~ ^52494646 ]]; then
      actual_format="RIFF (likely WebP)"
    elif [[ "$magic" =~ ^474946 ]]; then
      actual_format="GIF"
    else
      actual_format="unknown (magic: $magic)"
    fi
    fail "Decoded bytes are not PNG -- got $actual_format. Provider likely returned a different format. Saved to $out_path for inspection."
  fi
}

# ---- Provider calls ----

RESP_BODY="$(mktemp)"
trap 'rm -f "$RESP_BODY"' EXIT

case "$PROVIDER" in
  openai)
    URL="https://api.openai.com/v1/images/generations"
    REQ_BODY="$(jq -n --arg p "$PROMPT" '{
      model: "gpt-image-1",
      prompt: $p,
      size:  "1536x1024",
      n:     1
    }')"

    info "POST $URL"
    HTTP_CODE="$(
      curl -sS -X POST "$URL" \
        -H "Authorization: Bearer ${OPENAI_API_KEY}" \
        -H "Content-Type: application/json" \
        --data "$REQ_BODY" \
        -o "$RESP_BODY" \
        -w '%{http_code}'
    )" || fail "curl to OpenAI failed (network error)."

    printf 'http_status: %s\n' "$HTTP_CODE" >> "$LOG"

    if [[ "$HTTP_CODE" != "200" ]]; then
      # Even error responses should be JSON; if not, surface that explicitly.
      if jq empty "$RESP_BODY" 2>/dev/null; then
        ERR_MSG="$(jq -r '.error.message // .error // "unknown error"' < "$RESP_BODY")"
      else
        ERR_MSG="$(head -c 200 "$RESP_BODY" | tr '\n' ' ' | tr -s ' ')"
      fi
      printf 'error: %s\n' "$ERR_MSG" >> "$LOG"
      fail "OpenAI returned HTTP $HTTP_CODE: $ERR_MSG"
    fi

    # 200 OK doesn't guarantee a JSON body — captive portals, maintenance
    # pages, and proxy errors can still return 200 with HTML. Validate before
    # touching jq so the failure is a one-line message, not a stack trace.
    require_json_response "OpenAI" "$HTTP_CODE" "$RESP_BODY"

    # gpt-image-1 returns base64 by default in .data[0].b64_json
    B64="$(jq -r '.data[0].b64_json // empty' < "$RESP_BODY")"
    if [[ -z "$B64" ]]; then
      # Some response shapes may include a URL instead — fall back to that.
      IMG_URL="$(jq -r '.data[0].url // empty' < "$RESP_BODY")"
      if [[ -n "$IMG_URL" ]]; then
        info "Response gave URL; downloading..."
        DL_CODE="$(curl -sS -L -o "$OUT_PNG" -w '%{http_code}' "$IMG_URL")" \
          || fail "Failed to download image from $IMG_URL"
        [[ "$DL_CODE" == "200" ]] || fail "Image download from $IMG_URL returned HTTP $DL_CODE"
      else
        printf 'error: response had neither b64_json nor url\n' >> "$LOG"
        fail "OpenAI response missing b64_json/url. See $LOG and $RESP_BODY."
      fi
    else
      printf '%s' "$B64" | decode_b64_to_file "$OUT_PNG" \
        || fail "Failed to base64-decode OpenAI response."
    fi
    ;;

  gemini)
    URL="https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key=${GEMINI_API_KEY}"
    REQ_BODY="$(jq -n --arg p "$PROMPT" '{
      instances:  [ { prompt: $p } ],
      parameters: { sampleCount: 1, aspectRatio: "16:9" }
    }')"

    # Log a redacted URL (key removed) so the log is safe to share.
    info "POST https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key=REDACTED"
    HTTP_CODE="$(
      curl -sS -X POST "$URL" \
        -H "Content-Type: application/json" \
        --data "$REQ_BODY" \
        -o "$RESP_BODY" \
        -w '%{http_code}'
    )" || fail "curl to Gemini failed (network error)."

    printf 'http_status: %s\n' "$HTTP_CODE" >> "$LOG"

    if [[ "$HTTP_CODE" != "200" ]]; then
      if jq empty "$RESP_BODY" 2>/dev/null; then
        ERR_MSG="$(jq -r '.error.message // .error // "unknown error"' < "$RESP_BODY")"
      else
        ERR_MSG="$(head -c 200 "$RESP_BODY" | tr '\n' ' ' | tr -s ' ')"
      fi
      printf 'error: %s\n' "$ERR_MSG" >> "$LOG"
      fail "Gemini returned HTTP $HTTP_CODE: $ERR_MSG"
    fi

    # 200 OK doesn't guarantee a JSON body — see OpenAI branch for rationale.
    require_json_response "Gemini" "$HTTP_CODE" "$RESP_BODY"

    # imagen-3.0 returns base64 in .predictions[0].bytesBase64Encoded
    B64="$(jq -r '.predictions[0].bytesBase64Encoded // empty' < "$RESP_BODY")"
    if [[ -z "$B64" ]]; then
      printf 'error: response missing predictions[0].bytesBase64Encoded\n' >> "$LOG"
      fail "Gemini response missing image bytes. See $LOG and $RESP_BODY."
    fi

    printf '%s' "$B64" | decode_b64_to_file "$OUT_PNG" \
      || fail "Failed to base64-decode Gemini response."
    ;;
esac

# ---- Post-flight: confirm the file is real ----

if [[ ! -s "$OUT_PNG" ]]; then
  fail "Output file $OUT_PNG is empty after decode."
fi

# Hard-fail (not warn) if the bytes aren't actually PNG. Downstream code
# (builder.upload_hero_image) expects a real PNG; uploading a JPEG/WebP under
# a .png filename produces broken renders or upload errors. Let the
# orchestrator decide whether to retry with a different provider — don't try
# to convert formats inline (avoids ImageMagick dependency).
require_png_bytes "$OUT_PNG"

chmod 644 "$OUT_PNG"

SIZE_BYTES="$(wc -c < "$OUT_PNG" | tr -d ' ')"
printf 'output:    %s\n' "$OUT_PNG"   >> "$LOG"
printf 'size_b:    %s\n' "$SIZE_BYTES" >> "$LOG"

ok "Hero image written: $OUT_PNG (${SIZE_BYTES} bytes)"

# stdout: just the path so the caller can capture it cleanly.
printf '%s\n' "$OUT_PNG"
