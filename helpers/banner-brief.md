# HotDoG Banner — Design Brief

Looking for a meaningfully better terminal ASCII art banner for a CLI tool. The current
hand-drawn version is OK but not exciting. Help me get to "people screenshot this" tier.

## What it's for

I'm building a CLI skill called **HDG** — *HubSpot Demo Generator*, friendly name
**HotDoG** (note the embedded H/D/G capitalization — that's the joke). It runs from
either Claude Code or Codex. In ~10 minutes it researches a sales prospect, builds a
fully-populated HubSpot demo environment (CRM data, marketing assets, workflows, a
Google Doc agenda), and hands the rep a tailored demo to walk into.

The banner is the splash screen that prints when the skill kicks off. It sets tone for
the run. I want it to feel premium, fun, a little playful — *not* generic ASCII clipart.

## Constraints

- **Output**: a bash script that prints to terminal (variables for colors, heredoc for art)
- **Color**: 256-color ANSI escapes (`\e[38;5;Nm` foreground, `\e[1m` bold, `\e[2m` dim, `\e[0m` reset)
- **Width**: under ~80 columns
- **Height**: 12–18 lines including title and tagline
- **No tool-specific glyphs**: avoid `✻` (Claude Code) or anything that signals one vendor
- **Must render across**: iTerm2, Warp, Alacritty, Claude Code's terminal, Codex CLI

## Brand palette (256-color codes)

- HubSpot orange: 208 (primary)
- Tangerine bun: 215
- Mustard yellow: 226
- Sausage red: 160
- Char brown: 94 (sausage edges)
- Steam gray: 245
- Bright accent yellow: 220 (sparkles)

## What to depict

A **hot dog** — bun + sausage + mustard + steam — that reads as a hot dog at first
glance. Bonus points for visual personality: maybe a face, maybe a "sizzle" effect, maybe
the sausage casually winks at you. The point of the visual is to embody the HotDoG name
so the user remembers what they're running.

## Title and tagline (these can stay; you don't need to redesign them)

```
   HUBSPOT  ·  HotDoG  ·  DEMO GENERATOR
                ( H D G )

       tailored to your prospect  ·  plated in ~10 min
```

## What I have now (the bar to clear)

```
           ✦     ∴     ✧     ∴     ✦
                 '   '   '   '
                 )   )   )   )
       ╭──────────────────────────────╮
      ╱  〰〰〰〰〰〰〰〰〰〰〰〰〰〰  ╲
   ▟████████████████████████████████████▙
   ▜████████████████████████████████████▛
      ╲  〰〰〰〰〰〰〰〰〰〰〰〰〰〰  ╱
       ╰──────────────────────────────╯

   H U B S P O T  ·  HotDoG  ·  D E M O   G E N E R A T O R
                              ( H D G )

           tailored to your prospect  ·  plated in ~10 min
```

The shape is fine but the sausage is a flat slab and the whole thing feels like "rectangle
with squiggles" rather than a hot dog. I want more visual depth — shading on the bun,
texture on the sausage, mustard that actually drizzles, steam with motion. Use a wider
range of unicode block characters (`▀▁▂▃▄▅▆▇█▉▊▋▌▍▎▏░▒▓▔▕`) and box-drawing variants
(`┌┐└┘├┤┬┴┼━┃┏┓┗┛╔╗╚╝╭╮╰╯◜◝◞◟◠◡╱╲`) for shading, dimension, and curve.

## Two ways you could approach this

**Path A — Better hand-drawn ASCII**
Iterate directly on the bash heredoc. Use 256-color escapes liberally. Aim for visible
depth and texture rather than just outlines.

**Path B — Image → ASCII pipeline**
1. Generate a stylized hot dog image (you can use DALL-E here). Prompt suggestion: 
   *"minimalist isometric hot dog illustration, vibrant orange and red, clean vector 
   style, white background, centered, simple shapes, 800x400"*
2. Convert to colored ASCII. Tools that work well:
   - `chafa --symbols=block --colors=256 -s 70x18 hotdog.png` (best for terminal)
   - `jp2a --colors --width=70 hotdog.png`
   - `ascii-image-converter -C -d 70,18 hotdog.png`
3. Wrap output in a bash heredoc with the title/tagline below.

I'd lean toward Path B if you can produce a clean source image — the texture and shading
you get from a real image are hard to match by hand. But Path A can also work if you're
willing to use a wide unicode palette.

## Output format

Give me a complete `banner.sh` I can drop into 
`~/.claude/skills/hubspot-demo-prep/helpers/banner.sh` and run with `bash banner.sh`. 
Use the same color-variable convention as my current version (`O=$'\e[38;5;208m'` etc.) 
so it's easy to tweak.

If you go Path B, also include the source image and the exact conversion command you ran,
so I can re-run it if I want to tweak.
