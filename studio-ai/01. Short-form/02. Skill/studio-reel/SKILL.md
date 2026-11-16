---
name: studio-reel
description: Turn a raw talking-head video into a finished default-brand social reel (1080×1920) with even lighting, tightened cuts and punch-in zooms, word-by-word brand captions, and animated violet-glass callout cards (questions, data hub, statement, compare, steps, chips, feature, tool tiles, connect hub, AI chat, scheduled task) synced to what is said. Can copy the cuts and zooms of an already-edited reel. Use when asked to edit, cut, caption, add cards, overlays or callouts to, or "make a reel" from a talking-head clip, or to "recreate", "match" or "do it like" an existing edited reel.
---

# default reel

Raw talking-head clip → graded, cut, captioned reel with brand callout cards, rendered
with HyperFrames. Everything is driven by two files you write per reel: `edl.json` (the
edit) and `reel.json` (captions + cards). `references/example-reel.json` is a complete,
approved reel ("AI tools for marketing agencies") — copy its patterns.

`SKILL` below = this skill's folder (`~/.claude/skills/studio-reel`).

**Formats:** a vertical **reel** (1080×1920, the default), **feed** 4:5 (1080×1350), **square** 1:1
(1080×1080) or **landscape** 16:9 (1920×1080). For anything but a reel, pass `--format <name>` to
`plan_cuts.py`, init HyperFrames with `--resolution square` / `landscape` (portrait for feed), and put
`"format": "<name>"` in reel.json (see "format" in `references/reel-spec.md`).

## Requirements

Node 22+, FFmpeg, whisper-cpp (`brew install whisper-cpp`), Python 3 with numpy, Chrome.
`npx hyperframes doctor` checks them. On a Mac with Homebrew the tools live in
`/opt/homebrew/bin` — if a command isn't found, prefix it with `export PATH="/opt/homebrew/bin:$PATH";`.
First-time setup on a new machine: `INSTALL.md`.

## Workflow

### 1. Intake
Collect: the raw video, an optional **reference** (a finished reel to match), and anything
the person wants said on cards. Make a project folder next to the video, e.g.
`<name>/` with `work/` for analysis and `edit/` for the HyperFrames project:

```bash
cd <name> && HYPERFRAMES_SKIP_SKILLS=1 npx -y hyperframes@latest init edit --example blank --resolution portrait --non-interactive
```

### 2. Lighting
```bash
python3 SKILL/scripts/grade.py <raw> work --end <last raw second used + 1>
```
Finds the parts of frame that never move (walls, table), tracks their colour, and writes
per-frame gains back to the brightest, most neutral stretch (highlights never clip). Read
`work/grade-report.txt`; a static area under 3% means the camera moves, so check the
result by eye. The person wants lighting **consistent across the whole clip** — always do
this, even when a reference edit kept a lighting change.

### 3. The cut list (`work/edl.json`)
**With a reference reel:**
```bash
python3 SKILL/scripts/match_reference.py <raw> <reference> work
```
Recovers the cuts (from the audio, to 10 ms), punch-in zooms (hard punches split to the
exact frame) and any drifting reframe (pan). Read `work/match-report.txt`; low match
scores near captions/cards are normal.

**Without one:** transcribe the raw, read it for false starts and retakes ("let me say that
again", a sentence restarted, an outtake after the natural ending), then draft the cut list:
```bash
npx hyperframes transcribe <raw> -d work -m medium.en -l en --engine whisper
python3 SKILL/scripts/plan_cuts.py <raw> work/transcript.json work --remove 6.6-11.9 [more A-B ranges]
```
It trims pauses (silence below -40 dB for 0.3 s+, never where a word starts) to ~0.16 s,
removes the `--remove` ranges with edges snapped into silence, and alternates framing
1.3× → 1.0× → 1.22× → 1.0× every ~5.5–8 s at a cut, else a sentence start, else a gap between
words. Read `work/cut-report.txt`, adjust `edl.json` by hand if needed, and show the person
the cut list (what is removed, total length) before rendering. This speaker pauses little,
so most of the tightening comes from removed retakes.

### 4. Base edit
```bash
python3 SKILL/scripts/edit.py <raw> work/edl.json edit/base-edit.mp4 --grade work/grade-cmds.txt
```
One ffmpeg pass: grade → cut → punch-in → 1080×1920, 12 ms audio fades at joints,
a keyframe every second (the renderer needs it to seek).

### 5. Transcript of the edit
```bash
cd edit && npx -y hyperframes@latest transcribe base-edit.mp4 -m medium.en -l en --engine whisper
```
Use **medium.en** — small.en drifts by up to a second. Spot-check that words just after a cut
land just after the cut time.

### 6. Plan captions and cards (`edit/reel.json`)
Spec format and every card type: `references/reel-spec.md`. Print the transcript with word
indices first; write captions:
- **fix**: UK spelling (centralising, judgement), product names (Claude, GoHighLevel,
  Supermetrics), mis-hearings; **drop** words folded into a fix;
- **keywords** (gradient): the nouns that carry the point — tools, outcomes, the key verb;
- groups of 1–3 words; break at sentence ends; a keyword can stand alone.

Cards: one idea every 4–8 s, chosen from what is said (lists → tiles/questions, process →
steps, "X vs Y" → compare, a key term → feature/statement, tools joining → hub/connect,
"just ask it" → chat, recurring work → task, a turn in the argument → chip at top).
Never let a card sit waiting: if its main word lands more than ~1.5 s after the card, fill the gap
with what is being said — `leads` on a statement, an extra step/tile/pill on its own word.
Timing: a card lands on its trigger word (word start − 0.1 s); its parts land on their own
words; it leaves ~0.2 s before the next card; never two card groups at once (a chip may
sit above a card). Keep cards off the false starts and cuts.

For a livelier reel (or when asked for "more effects"), add **takeovers** — gradient cutaways for a
named list, a tool reveal, a big number or a recap (`"takeovers"` in `references/reel-spec.md`) — and a
few **fx** punches on words that need weight. Alternate `pip` and `full`; 4–6 per minute and a half.

Finish with the **end screen** (`"endcard"` in reel.json): 3.5 s on the brand gradient with the
white logo and the lines "Follow", then "for more" in bold (the `lines` example in `references/reel-spec.md`) — the default call to action
unless the person asks for another.

Show the person a storyboard table (time · what is said · card · on-card text) and get a
yes before building. If they want to adjust it by hand, open the timeline editor on the project.
It previews the real composition, lets them drag cards, edit captions and add text, and writes
`reel.json` on Save. It comes in the Studio AI short-form editor package: double-click
`Open Studio AI short-form editor.command` in its main folder, or run `python3 server.py <project>` in `04. Editor`.
New videos made there live in `05. Projects/<name>/`; renders go to `06. Renders/<format>/`.

### 7. Build, check, look
```bash
python3 SKILL/scripts/build.py edit
cd edit && npx -y hyperframes@latest check
npx -y hyperframes@latest snapshot --at <one time per card> --no-end --describe false -o ../work/snaps
```
Look at every snapshot (crop the card area and view it). Check: text never touches a card
edge, card contents centred, nothing overlaps the captions (captions sit at y≈990–1090,
cards from y≈1190, chips at y≈288).

### 8. Render and verify
```bash
npx -y hyperframes@latest render -q delivery --output "../<Title>.mp4"
ffmpeg -i "../<Title>.mp4" -vf blackdetect=d=0.04:pix_th=0.08 -an -f null - 2>&1 | grep -c black_start   # expect 0
```
Pull a 1-frame-per-second contact sheet and look at it before handing over.

## House style (from the person's feedback — keep)

- Cards: violet-tinted charcoal glass, **rounded corners only** (no cut corners), soft
  shadow, gradient outline that **flares as a card lands and settles** to a faint glow.
- Every card group is **centred on the frame** (done automatically from its real width);
  contents of larger cards are **centred with even padding** — nothing off-balance, no text
  near an edge.
- Captions: Display ExtraBold 70 px, white, centred at chest height, words blur in one by one
  as spoken, keywords in the magenta→violet gradient. No trailing commas.
- **No sound effects** by default (`"sfx": []`). Pop/tick files exist in the template if asked.
- Brand voice on cards: sentence case, no emoji, no exclamation marks, UK spelling.
- Brand values (fonts, colours) live in `template/brand.css` — the only file to change for
  another brand. Display is a licensed brand font; keep it in this skill only.

## Gotchas

- Never put `filter` or `opacity` on an ancestor of a glass element — it kills the backdrop
  blur. motion-lib.js animates glass elements themselves and blurs only their content.
- FFmpeg 9 takes filter scripts with `-/filter_complex <file>`; `.mov` files from iPhones or
  Resolve print stream info twice (scripts take the first line).
- Render at the source frame rate (`"fps": 25` for these clips).
- `npx hyperframes check` warns about track density and "heavy overlay" counts on a full
  reel; harmless here — confirm with the blackdetect step.
- Logos: ghl/sm are close redraws; meta/gads/claude are official marks. Any other brand:
  `"si:<simple-icons name>:#hex"`; any Lucide icon: `"icon:<name>"`.
