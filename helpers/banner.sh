#!/usr/bin/env bash
# Hot Dog · HubSpot Demo Prep banner.
# Colored ASCII for Claude Code, iTerm, Warp, and other 256-color terminals.

# Color variables use $'\e[...m' ANSI-C quoting so heredoc preserves escapes.
O=$'\e[38;5;208m'    # HubSpot orange
T=$'\e[38;5;215m'    # Tangerine bun outline
M=$'\e[1;38;5;226m'  # Mustard yellow (bold for pop)
R=$'\e[38;5;160m'    # Sausage red
D=$'\e[38;5;94m'     # Char (sausage edges)
G=$'\e[38;5;245m'    # Steam gray
C=$'\e[1;38;5;87m'   # Claude Code cyan (sparkles)
A=$'\e[1;38;5;173m'  # Anthropic warm clay (Opus)
W=$'\e[1;38;5;231m'  # Bold white (separators)
S=$'\e[2;38;5;245m'  # Dim gray (tagline)
B=$'\e[1m'
N=$'\e[0m'

cat <<EOF

           ${C}✻${N}     ${G}∴${N}     ${C}✦${N}     ${G}∴${N}     ${C}✻${N}
                 ${G}'   '   '   '${N}
                 ${G})   )   )   )${N}
       ${T}╭──────────────────────────────╮${N}
      ${T}╱${N}  ${M}〰〰〰〰〰〰〰〰〰〰〰〰〰〰${N}  ${T}╲${N}
   ${D}▟${R}████████████████████████████████████${D}▙${N}
   ${D}▜${R}████████████████████████████████████${D}▛${N}
      ${T}╲${N}  ${M}〰〰〰〰〰〰〰〰〰〰〰〰〰〰${N}  ${T}╱${N}
       ${T}╰──────────────────────────────╯${N}

  ${C}✻${N}  ${O}${B}H U B S P O T${N}  ${W}·${N}  ${O}${B}H O T   D O G${N}  ${W}·${N}  ${O}${B}D E M O   P R E P${N}  ${C}✻${N}
                          ${S}( H D G )${N}

      ${S}a magnum${N} ${A}${B}opus${N} ${S}cooked up by${N} ${C}${B}Claude Code${N}  ${S}·  plated in ~10 min${N}

EOF
