# reel.json

```json
{
  "duration": 44.28,            // seconds of base-edit.mp4
  "fps": 25,
  "video": "base-edit.mp4",
  "captions": { ... },
  "cards": [ { "type": "...", ... } ],
  "endcard": {"duration": 3.5, "lines": [{"text": "Follow"}, {"text": "for more", "bold": true}]},
  "sfx": []                      // off by default; [{"kind": "pop"|"tick", "t": 9.25, "volume": 0.3}]
}
```
All times are seconds on the **edited** timeline. Word indices refer to `transcript.json`.
The complete approved example is `example-reel.json`.

## brand — whose look the video uses (Studio AI)

`"brand": "<id>"` picks a client brand kit (`03. Brands/<id>/brand.json`: colours, fonts, logo, end screen). Leave it out
(or use `"default"`) for the default look; the build is then exactly the same as before. `scripts/brand.py` adds
the kit's stylesheet. Without `endcard.lines` (or `endcard.logo`), the end screen uses the kit's lines and light logo.

## format — reel, feed, square or landscape
| format | canvas | use | layout |
|---|---|---|---|
| `"reel"` (default) | 1080×1920 | Instagram, TikTok, Shorts | the full reel layout; cards use `top` |
| `"feed"` | 1080×1350 (4:5) | Instagram and LinkedIn feed | captions at y 660 (64 px); cards centred below at y 1040, scaled 86%; chips at y 92 |
| `"square"` | 1080×1080 (1:1) | feeds, ads, carousels | captions at y 560 (58 px); cards centred below at y 832, scaled 74%; chips at y 80 |
| `"landscape"` | 1920×1080 (16:9) | YouTube, LinkedIn, website | side panel, below |

Outside `reel`, a card's optional `"y"` is its vertical centre in px and `top` is ignored. Feed and square
keep the reel's style on a shorter frame: prefer compact cards and short text, and in square use fewer
cards (one idea every 6–10 s). `plan_cuts.py --format feed|square|landscape` sets the output size and
the zoom cycle (feed as reel; square 1.2× / 1.12×; landscape 1.15× / 1.1×).

In landscape:
- Cards keep their designs but are scaled (78%) into a **side panel**: `"layout": {"cards": "right"}`
  (default), `"left"` (speaker on the right) or `"centre"`. Chips sit along the top of the panel.
- A card's optional `"y"` is its vertical centre in px (default 470; chips 100). `top` is ignored.
- Captions sit as a lower third (`top` 880, `size` 60 by default).
- Fewer cards than a reel: one idea every 6–12 s. The end screen uses a shorter stack.
- The cut list is made with `plan_cuts.py --format landscape` (1920×1080, gentler 1.15× / 1.1× punch-ins);
  `edit.py` crops to the output's shape, so landscape footage is never squeezed.
```json
{"format": "landscape", "layout": {"cards": "right"}, "duration": 312.4, "fps": 25, "video": "base-edit.mp4", ...}
```

## endcard
Branded end screen added after the video (the reel gets `duration` seconds longer). The brand
gradient (`template/assets/brand/end-bg.jpg`) fades up over the last frame, the regular `lines`
rise in one by one (58 px), the `"bold": true` lines land as the big offer (118 px), then the white
logo. Put regular lines first and the offer last; text is plain (no `*` markup). The standard one
is in the example above. The older `headline` / `sub` pair still builds as two regular lines.
Optional `logo` names another file in `assets/brand/`. Omit `endcard` for no end screen.

## fx — effects on the video
Motion on top of the base edit's own punch-in zooms. Use sparingly: a punch on a word that needs
weight, a slow push on an opening or a key line, a flash on a hard turn. Never during a card's entrance.
```json
"fx": [{"kind": "push",  "t": 0.0,   "until": 5.35, "to": 1.08},
       {"kind": "punch", "t": 14.38, "until": 15.95, "to": 1.15},
       {"kind": "flash", "t": 65.4}]
```
| kind | what it does | fields |
|---|---|---|
| `punch` | snaps in over 0.14 s on the word at `t`, eases back out before `until` | `to` 1.05–1.4 (default 1.15) |
| `push` | slow drift in from `t` to `until`, then resets | `to` 1.02–1.2 (default 1.08) |
| `flash` | white flash at `t` fading over 0.35 s | `strength` 0.3–1 (default 0.85) |

## takeovers — gradient cutaways
Breaks away from the footage to the brand gradient for a key list, a number or a recap. Use 4–6 in a
60–100 s reel, a few seconds to ~10 s each, spaced between ordinary cards; never two in a row.
Captions under a takeover are left out (its own text carries the words), so give it the words being said.
```json
"takeovers": [
 {"mode": "pip", "t": 29.45, "out": 37.85, "kicker": "Connect via MCP", "title": "Plug it *all* in",
  "items": [{"logo": "ghl", "text": "GoHighLevel", "t": 30.8}, {"logo": "sm", "text": "Supermetrics", "t": 32.1},
            {"logo": "icon:plus", "text": "Anything, basically", "t": 36.48}]},
 {"mode": "full", "t": 56.6, "out": 64.95, "kicker": "The tool", "title": "*Pipeboard*", "t_title": 56.72,
  "items": [{"logo": "icon:plug", "text": "Connect Google Ads + Meta", "t": 59.3}]},
 {"mode": "full", "t": 89.75, "out": 92.35, "kicker": "Done for you",
  "stat": {"value": "80–90%", "count": 90, "prefix": "80–", "suffix": "%", "count_dur": 0.8, "size": 210,
           "t": 90.15, "bar": 0.9, "label": "of the boring work", "t_label": 91.5}},
 {"mode": "full", "t": 95.8, "kicker": "Recap", "title": "Two *big* things", "numbered": true,
  "items": [{"text": "Centralise your data with MCP", "t": 96.4}, {"text": "Let AI build your campaigns", "t": 97.1}]}
]
```
| field | meaning |
|---|---|
| `mode` | `full`: gradient wipes in as a circle while the footage pushes in, wipes up on the way out. `pip`: the footage shrinks into a rounded window (top half) and the text sits below; it grows back on the way out. `pip` is reel-only (other formats use `full`) |
| `t`, `out` | in and out; omit `out` on the last one to run straight into the end screen |
| `kicker` | small pill above the title |
| `title`, `t_title` | headline, word by word; `*word*` gets a white underline. Pip titles ≤ 22 characters, full ≤ 16 per line |
| `items` | rows landing on their words: `{"text", "t", "logo"}` (any logo key, or `icon:<lucide>`); `"numbered": true` puts 1, 2, 3 in the badges instead. Up to 5 in pip, 4 in full; text ≤ 28 characters |
| `stat` | a big number: `value`, optional count-up (`count`, `prefix`, `suffix`, `count_dur`), `bar` (0–1 fill), `label`, `size` px (300 default; ~210 for six characters like "80–90%") |

A takeover suits: a list being named (items on their words), a tool reveal (title + what it does), a
number (stat), a "that's one thing…" or closing recap (numbered). Keep fx punches off takeovers — the
transitions already move the footage. Full worked reel with six takeovers: `example-takeovers.json`.

## sfx — sound effects
Off by default (`"sfx": []`). `{"kind": "pop" | "tick", "t": 9.25, "volume": 0.3}`: a pop as a card lands,
a tick for a list item.

## captions

| key | meaning |
|---|---|
| `fix` | `{"30": "centralising", "93": "GoHighLevel"}` — display text for a word index |
| `drop` | indices to hide (e.g. "high", "level" once 93 reads "GoHighLevel") |
| `keywords` | indices shown in the gradient |
| `keyword_words` | alternative: words (any case, no punctuation) always in the gradient |
| `groups` | optional `[[first, last], ...]` index ranges; omit to auto-group (≤ `max_words`, breaks at sentence ends, pauses > 0.45 s, before a keyword) |
| `max_words` | auto-group size, default 3 |
| `lead` | seconds a word appears before it is heard, default 0.05 |
| `top`, `size` | caption y and font size in px (defaults 990, 70) |
| `weight` | caption font weight: 500 Medium, 600 SemiBold, 700 Bold, 800 ExtraBold (default) |

## overlays — other videos over the main one (inserts, B-roll, testimonials)

```json
"overlays": [{"src": "assets/overlays/testimonial.mp4", "name": "Testimonial", "t": 10, "dur": 5, "in": 1, "clip": 8,
              "track": 1, "mode": "full", "opacity": 1, "fade": 0.3, "muted": false, "volume": 1, "duck": 0.15}]
```

`src` relative to the project (the editor copies clips into `assets/overlays/`). `in` = start point inside the clip, `clip` its
full length. `mode` `full` (covers the frame) or `pip` (`x`, `y`, `w`, `h` canvas px, `radius`; rounded, with a shadow).
Higher `track` on top. `muted` (default true); unmuted plays its sound at `volume` (fades with `fade`). `duck` = the speaker's
volume while it plays (default 1; a HyperFrames volume lane on the main video). Overlays sit over the main video and under
blurs, cards, captions and takeovers. The planner does not add them.

## redactions — blur or cover part of the picture

```json
"redactions": [{"t": 6.0, "dur": 3, "type": "blur", "strength": 28, "w": 432, "h": 324,
                "track": false, "keys": [{"dt": 0, "x": 324, "y": 517}]}]
```

`type` `blur` (frosted, `strength` px) or `box` (solid black). `keys` x/y = top-left in canvas px, `dt` = seconds from `t`.
With `track: true` and 2+ keys the region glides between the points. Regions sit on the video, under cards, captions and
takeovers. Use them for faces, names, numbers or screens that must not be shown. The planner does not add them.

## Cards

Every card has `out` (when it has left; omit to stay to the end). Optional `top` (px) moves the
whole group vertically. Groups are centred horizontally automatically; optional `x` (px, canvas) puts the group's
centre somewhere else (the editor sets it when a card is dragged on the preview). Leave `x` out for the house layout.

Icons are [Lucide](https://lucide.dev/icons) names. Logos are `ghl`, `sm`, `meta`, `gads`,
`claude`, `si:<simple-icons slug>[:#hex]`, or `icon:<lucide name>`.

### questions — "people keep asking me…"
Stacked chat pills that land one by one, earlier ones dim.
```json
{"type": "questions", "items": ["What AI tools should we be using?", "What’s your AI stack?", "Best AI for marketing agencies?"],
 "times": [0.45, 1.0, 1.55], "dim_at": 2.4, "out": 4.95}
```

### hub — many sources into one place
Three icon tiles each side, a centre orb that pops, then curved lines draw in; optional pulse.
```json
{"type": "hub", "left": ["users", "volume-2", "chart-column"], "right": ["table", "mail", "globe"], "center": "database",
 "t": 8.25, "t_hub": 9.25, "t_lines": 10.3, "t_pulse": 11.5, "out": 12.75}
```

### statement — "it's all about X"
Kicker, an icon that draws itself, one big word with a gradient underline. Optional `leads` cycle in
the same spot before the final word so the card never sits waiting — use them whenever the main
word lands more than ~1.5 s after the card: `"leads": [{"text": "Writing", "t": 4.88}, {"text": "Producing", "t": 5.67}]`.
```json
{"type": "statement", "kicker": "Marketing is all about", "icon": "lightbulb", "word": "Insights",
 "t": 13.12, "t_icon": 13.55, "t_word": 14.1, "out": 14.95}
```

### compare — "what you think vs what the market thinks"
Two cards; optional swap where both answers flip (`then`, `t_swap`). `ok` true = blue tick, false = magenta cross.
```json
{"type": "compare",
 "left":  {"kicker": "What you think", "first": {"ok": true, "text": "This will work"}, "then": {"ok": false, "text": "This won’t work"}},
 "right": {"kicker": "What the market thinks", "first": {"ok": false, "text": "Not for us"}, "then": {"ok": true, "text": "Love it"}},
 "t_left": 15.5, "t_right": 17.62, "t_swap": 18.78, "out": 19.85}
```
Answers ≤ 16 characters; kickers ≤ 24.

### steps — a process
Up to 3 numbered cards with a progress bar; `t_highlight` lights the last one up and keeps it lit.
`badge_icon` adds a small icon beside the main one; `sub` adds a line under the label.
```json
{"type": "steps", "steps": [{"icon": "eye", "label": "Understand"}, {"icon": "layers", "label": "Contextualise"},
                            {"icon": "user", "badge_icon": "zap", "label": "Act", "sub": "with human judgement"}],
 "times": [20.2, 21.42, 23.5], "t_highlight": 25.05, "out": 26.1}
```
Labels ≤ 13 characters.

### chip — a short line at the top of frame
Sits above other cards. `*word*` = gradient, `->` = arrow.
```json
{"type": "chip", "text": "Insights -> *Action*", "t": 19.98, "out": 26.15}
{"type": "chip", "text": "So how*?*", "t": 26.25, "out": 29.95}
```

### feature — name a key term
Gradient icon tile, kicker, big title (gradient part + optional white part landing on its own word).
```json
{"type": "feature", "icon": "plug", "kicker": "Model Context Protocol", "title": "MCP", "title_rest": "servers",
 "t": 28.38, "t_title": 28.58, "t_rest": 28.8, "out": 30.05}
```

### tiles — a list of tools
Up to 4 tiles bouncing in on their words, optional "+ more" pill.
```json
{"type": "tiles", "items": [{"logo": "ghl", "label": "GoHighLevel"}, {"logo": "sm", "label": "Supermetrics"},
                            {"logo": "meta", "label": "Meta"}, {"logo": "gads", "label": "Google Ads"}],
 "times": [30.58, 31.6, 32.76, 34.06], "plus": "anything", "t_plus": 34.75, "out": 35.75}
```
Labels ≤ 13 characters.

### connect — tools plugged into one product
Centre tile (logo + name + badge) with four satellites and lines; `t_spin` turns the logo a quarter.
```json
{"type": "connect", "center": "claude", "label": "Claude", "badge": "MCP", "satellites": ["ghl", "sm", "meta", "gads"],
 "t": 35.88, "t_lines": 36.2, "t_spin": 36.9, "out": 37.65}
```

### chat — "you could just ask it"
An assistant window: question types itself, thinking dots, then a result line with source logos.
```json
{"type": "chat", "name": "Claude", "logo": "claude", "status": "4 sources connected",
 "question": "Which campaign brought in the most leads?", "sources": ["ghl", "sm", "meta", "gads"], "result": "Pulling data from",
 "t": 37.74, "t_type": 38.0, "t_type_end": 39.37, "t_dots": 39.45, "t_result": 40.02, "out": 40.55}
```
Question ≤ 42 characters.

### task — something that runs on its own
Icon tile, kicker, title, schedule line and a toggle that switches on.
```json
{"type": "task", "icon": "calendar-clock", "kicker": "Scheduled task", "title": "Weekly performance report",
 "sub": "Every Monday · 9:00 AM", "t": 40.75, "t_toggle": 41.85}
```

### text — any line of text you want on screen
Free text, as a glass card (`"style": "glass"`) or on its own over the video (`"style": "bare"`).
`*word*` = gradient. `anim`: `words` (one by one, default), `rise` (all together) or `pop`.
Optional `kicker` above it, `size` in px (default 64), `top` (default 1240; 288 = chip height).
```json
{"type": "text", "text": "Book your *free audit*", "kicker": "Next step", "style": "glass", "anim": "words",
 "size": 64, "top": 1240, "t": 32.4, "out": 36.0}
```

## Adding a card type
Add `r_<type>(cid, c)` (HTML) to `scripts/build.py`, `CARD.<type>(id, c)` (motion) to
`template/motion-lib.js`, styles to `template/styles.css`, and a section here. Use the helpers:
`gIn`/`gPop`/`gBounce`/`gOut` for glass, `cIn` for content, `draw` for SVG strokes, `glow` for the
outline flare. Elements with class `g` are glass and are what gets centred.
