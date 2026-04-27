#!/usr/bin/env bash
# HotDoG · HubSpot Demo Generator banner.
# Colored ASCII for any 256-color terminal (iTerm, Warp, Claude Code, Codex CLI).

# Color variables use $'\e[...m' ANSI-C quoting so heredoc preserves escapes.
O=$'\e[38;5;208m'    # HubSpot orange
T=$'\e[38;5;215m'    # Tangerine bun outline
M=$'\e[1;38;5;226m'  # Mustard yellow (bold)
R=$'\e[38;5;160m'    # Sausage red
D=$'\e[38;5;94m'     # Char (sausage edges)
G=$'\e[38;5;245m'    # Steam gray
Y=$'\e[1;38;5;220m'  # Bright yellow (sparkles)
W=$'\e[1;38;5;231m'  # Bold white (separators)
S=$'\e[2;38;5;245m'  # Dim gray (tagline)
B=$'\e[1m'
N=$'\e[0m'

cat <<EOF

           ${Y}✦${N}     ${G}∴${N}     ${Y}✧${N}     ${G}∴${N}     ${Y}✦${N}
                 ${G}'   '   '   '${N}
                 ${G})   )   )   )${N}
       ${T}╭──────────────────────────────╮${N}
      ${T}╱${N}  ${M}〰〰〰〰〰〰〰〰〰〰〰〰〰〰${N}  ${T}╲${N}
   ${D}▟${R}████████████████████████████████████${D}▙${N}
   ${D}▜${R}████████████████████████████████████${D}▛${N}
      ${T}╲${N}  ${M}〰〰〰〰〰〰〰〰〰〰〰〰〰〰${N}  ${T}╱${N}
       ${T}╰──────────────────────────────╯${N}

   ${O}${B}H U B S P O T${N}  ${W}·${N}  ${O}${B}HotDoG${N}  ${W}·${N}  ${O}${B}D E M O   G E N E R A T O R${N}
                              ${S}( H D G )${N}

           ${S}tailored to your prospect  ·  plated in ~10 min${N}

EOF
