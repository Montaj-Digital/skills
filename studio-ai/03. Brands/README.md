# Brand kits

One folder per brand: `03. Brands/<id>/brand.json` plus its assets. `default/` is today's look and the default:
a video with no `brand` (or `"brand": "default"`) builds exactly as before.

```
<id>/
├── brand.json
├── fonts/      font files (.ttf .otf .woff .woff2); licences are the client's responsibility
├── logos/      logo-light.svg (for dark backgrounds, used on the end screen), logo-dark, mark
└── images/     background.jpg (end screen + takeover background; optional, a gradient is made from the colours)
```

## brand.json

| Key | What it is |
|---|---|
| `id`, `name`, `website` | The folder name, the display name, the client's site. |
| `colors.primary`, `colors.accent` | Main brand colour and the bright accent. |
| `colors.gradient` | `[from, to]`: buttons, number dots, lower-thirds. |
| `colors.keyword` | `[a, b, c]`: the caption keyword gradient and card titles. |
| `colors.kicker`, `colors.highlight`, `colors.text` | Small uppercase labels, "yes" marks, text colour (default white). |
| `colors.glass_tint` | `[top, bottom]` rgba colours of the glass cards. |
| `colors.takeover_bg` | Solid colour under the takeover background. |
| `fonts.display` / `fonts.body` | `{family, files: [{file, weight}]}`. Display = headlines and captions, body = small text. |
| `logos.light` / `dark` / `mark` | Paths inside the kit. |
| `images.background` | End screen and takeover background image. |
| `captions.keyword` | `"gradient"` (uses `colors.keyword`) or one solid colour. `captions.weight`: 500 to 800. |
| `endscreen.lines` | `[{text, bold}]`, the same shape as `reel.json` `endcard.lines`. `endscreen.cta`: one-line call to action. |
| `voice.tone`, `voice.cta` | Given to Claude when it plans, fills takeovers and writes AI clips. |

Missing keys fall back to values made from `primary` and `accent`. A kit with no font files uses Helvetica Neue / Arial,
never the licensed default font (Display).

## Making and editing kits

Use the **Brands** button in the Studio header. You can add a client, pick colours (with a contrast check), choose a
Google Font (downloaded from Fontsource) or upload font files, upload logos and a background, and edit the end screen and
tone of voice. The preview on the right shows the real caption, cards, takeover, lower-third and end screen as you go.
Saving keeps the previous `brand.json` in `<id>/.backups/`. Code: `brandkit.py` (here), `01. Short-form/04. Editor/brands.py`
(routes), `app/brands.js`.

**Import a brand guide** (top of a client's kit): choose a PDF or an image of the guide, or type the client's website,
and press *Read it with Claude*. Claude Code reads the pages it needs (about a minute), fills in the colours, fonts,
end screen and tone of voice, and lists what it guessed. Fonts come from Google Fonts; if the guide's font isn't there,
a look-alike stands in and the notes say so. From a PDF or image guide it also cuts out the logo and the mark (white, dark and own-colour versions, background removed). Check everything, replace anything that's off, then Save.

## How the skills use it

- **studio-reel** (`01. Short-form/02. Skill/studio-reel/scripts/brand.py`): `build.py` adds one extra stylesheet after
  `brand.css` + `styles.css` when `reel.json` has `"brand": "<id>"`. It copies the kit's files into `assets/brand/<id>/`.
  Kits are found through `$STUDIO_BRANDS`, or any `03. Brands` folder above the project or the skill.
- **Long-form** (`02. Long-form/04. Editor/app/overlays.css`): colours and fonts are `--ov-*` variables, and each one
  falls back to the default value. `longform.json` `"brand": "<id>"` sets them through `brandkit.long_css()` in the editor
  preview (`/brands/<id>/long.css`) and the render (`render_long.py` copies the kit's files into its stage).
