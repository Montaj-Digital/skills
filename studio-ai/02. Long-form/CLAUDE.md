# Studio AI Long-form Video Editor: project handover

**Next work:** see `../ROADMAP.md` (phases agreed 2026-10-15: auto-filled takeovers, overlay video tracks short-form then long-form, polish).

**Status (2026-10-16, v0.5.0 adds overlay videos; 2026-10-15, v0.4.0 adds cutting; see "Cuts" below; earlier status 2026-10-08, v0.3.1):** Phases 1 to 3 built. Phase 1 ran on the real 77-min workshop video; the editor and the preview renders were tested on it; a FULL render has not been run yet (ask first).
See "Phase 1 as built" and "Phase 2 and 3 as built" at the end.
**Read first:** `../01. Studio AI Short-form Video Editor/CLAUDE.md`. The architecture, brand, UI conventions and
working rules there all apply here. This file only covers what is different for long-form.

## The goal

Turn a long talking-head recording (60+ minutes, usually landscape 16:9 for YouTube) into an edited, branded video:
- trim pauses and retakes,
- add chapters, lower-thirds and occasional brand cards,
- edit everything on a timeline,
- render the final MP4.

It is the long-form counterpart of the short-form editor (Reels, Feed, Square and short Landscape videos).

## Key decision: one dashboard, two sections

The team uses **one local app**: the short-form editor's server at http://127.0.0.1:4321, the same splash, header,
brand and light/dark theme. Long-form is a **separate section** of that dashboard, not a separate app or port.

- **Splash:** **Let's create** first asks **Short-form** (Reels and social, seconds to minutes) or **Long-form**
  (YouTube and webinars, 60+ min), as two large cards like the Clean/Takeover step. Short-form continues into the
  existing wizard unchanged. Long-form opens the long-form wizard.
- **Open / home:** a **Short-form | Long-form** switch at the top. Each shows its own library, with its own filter
  chips, its own New tile and its own Renders folder.
- **Header New:** starts the wizard for whichever section you're in.

Code ownership keeps the short-form editor stable:
- **All long-form code lives in this folder.** That covers its pipeline, server routes, front end, skill and docs.
- **The short-form folder gets only a small, guarded hook:**
  - In `server.py`: if `../02. Studio AI Long-form Video Editor/04. Editor/longform.py` exists, import it and hand
    it every `/long/…` and `/api/long/…` request in `do_GET` and `do_POST`. Add this before the existing routes, wrapped
    so that an import error only disables long-form.
  - Expose `GET /api/sections` → `{"long": true|false}` so the dashboard hides the switch when long-form isn't there.
  - In `app/flow.js` and `app/home.js`: the Short/Long choice and the library switch. Long-form screens load the
    script `/long/app/long.js`, so they keep using the shared helpers (`el`, `ic`, `icon`, toast, theme).
- **Never change short-form behaviour.** The short-form wizard, timeline, preview, render, the `reel.json` format and
  the studio-reel skill must work exactly as before. After any hook change, re-test the short-form flow (splash →
  Clean → upload → timeline) and open BROLL01416417 read-only.

## Folder layout (create it, same numbering as short-form)

```
02. Studio AI Long-form Video Editor/
├── 02. Skill/        bundled copy of ~/.claude/skills/studio-longform
├── 03. Tools/        make-package.sh (installer: reuse short-form's install.sh, all dependencies are the same)
├── 04. Editor/       longform.py (routes, called by the short-form server), pipeline_long.py, app/ (long.js, long.css), VERSION
├── 05. Projects/     one folder per long video (camera file is LINKED, not copied)
├── 06. Renders/      Long-form 16x9/ (+ Previous versions/)
├── 07. Packages/
├── README.md         user guide
└── CLAUDE.md         this file
```

Reuse short-form code by **copying it in and adapting** (for example the timeline from `app.js`, the pipeline steps from
`pipeline.py`). Don't import the short-form editor's internals at runtime, except through the hook above.

## What has to be different at 60+ minutes, and the plan

**Phase 1: long-form wizard and pipeline (start here)**
1. **Choose the video in place.** Browser upload copies 20–100 GB, so don't use it. Use a server-side Finder dialog
   (`osascript -e 'POSIX path of (choose file of type {"public.movie"})'`). Then symlink, or record the path, under
   `05. Projects/<name>/raw/`.
2. **Details:** name, notes for Claude and a **transcript**, either:
   - **Paste** plain text. It has no timings, so whisper still runs; the pasted text corrects whisper's words
     (names, brands, jargon) by aligning them with `difflib`.
   - **Upload SRT/VTT.** It has timings, so skip whisper. Spread word times evenly across each cue.
   - **None:** whisper as usual.
3. **Transcribe once.** Map word times onto the edited timeline through the cut list (`edl.json`). Don't transcribe
   the edit again; for an hour of video that saves 10–30 minutes.
4. **Cuts:** the pauses and retakes logic from `plan_cuts.py`. Gentle or no punch-in zooms for long-form.
5. **Claude plans in two passes**, because a whole hour is about 10k words, or 100k+ tokens:
   - (a) an outline: chapters with titles and times, from a compact sentence-level transcript;
   - (b) per chapter: lower-thirds, key-point cards and an occasional stat or list.
   Output YouTube chapter timestamps (`chapters.txt`) as well. Claude runs as `claude -p`, as in short-form.
6. **Captions:** burned-in word captions **off by default** (YouTube has its own). Optional on. Ask the user to
   confirm.

**Phase 2: editor at scale**
- **Windowed preview:** build only about ±2 minutes around the playhead, and rebuild as the playhead moves.
- **Virtualised timeline:** draw only the visible range, and zoom out to show the whole hour. Add a chapter track.
- Filmstrip and waveform: summarise them for the full hour and load detail on zoom.

**Phase 3: fast render**
- HyperFrames drawing 108k full frames in Chrome is too slow. Instead:
  - render only the overlays (cards, lower-thirds), segment by segment, as transparent MOV with
    `npx hyperframes render --format mov`;
  - composite them over the base edit with ffmpeg (`overlay` at each segment's time);
  - make it resumable, so finished segments are kept.
- Output goes to `06. Renders/Long-form 16x9/<name>.mp4`, plus `chapters.txt` next to it.

## The skill: studio-longform

Create `~/.claude/skills/studio-longform`:
- Reuse studio-reel's brand: `brand.css`, fonts, logo, and the card designs adapted to 1920×1080.
- Long-form rules: chapters, lower-thirds for names and topics, about one card every 1–3 minutes, calm motion, the end
  screen.
- Its own spec file (for example `longform.json`, read by its own `build.py`), so the studio-reel skill is never
  changed.
- Edit the installed copy; `make-package.sh` copies it into `02. Skill`.

## Working rules (same as short-form)

- **Long jobs:** ask before full renders or anything that takes a long time.
- **Test material:** a long test video can be made by looping `~/Desktop/01.mov` with ffmpeg in the scratchpad.
  Use 5–10 minute clips for most testing, and a full hour only for scale checks.
- **Real videos:** don't touch the user's real videos (`../01…/05. Projects/BROLL01416417`, the Video Callouts reels)
  beyond opening them read-only.
- **Code style:** Python 3.9 standard library only. Vanilla JS, no build step. Bundled Lucide icons. Brand tokens from
  the short-form `app.css`.
- **Release:** bump `04. Editor/VERSION`, update `README.md` and this file, and keep only the newest zip in
  `07. Packages`.
- **The user's style:** plain-English updates, and they like to see each phase working before moving on. Do Phase 1
  first, show it, then ask.

## Decisions (answered 2026-10-08)

- **Test video:** `~/Desktop/SFH - AI Workshop - Oct 5 2026.mp4` (77 min, 1280x720, a Zoom-style workshop, not a plain
  talking head). Use read-only; ask before running the full hour (transcribe + about 10 Claude calls).
- **Burned-in captions:** ON by default, with an on/off switch in the wizard and on the project screen (`captions.on`).
- **Packaging:** separate zips. `07. Packages/Studio-AI-Long-form-<version>.zip` is an add-on unzipped NEXT TO the short-form
  folder; `Install Long-form.command` installs the skill. The short-form hook finds it as a sibling folder named
  `02. Studio AI Long-form Video Editor` or `Studio AI Long-form Video Editor`.

## Phase 1 as built

- `04. Editor/longform.py`: routes (`/long/app/*`, `/api/long/*`: projects, choose-file/choose-transcript (Finder via osascript),
  start, status, retry, project, video (Range), words, thumb, captions, reveal, delete). `pipeline_long.py`: `LongJob`
  steps setup, transcript, retakes, cuts, words, outline, details, finish; state in `work/job.json`; every Claude result is
  cached in `work/` (`retakes.json`, `outline.json`, `details.json`), so a retry never repeats finished work.
- Transcript: whisper once on the raw file; paste mode aligns the pasted text with `difflib` (`align_paste`); SRT/VTT
  skips whisper (`parse_subtitles`, words spread evenly per cue, so pause trimming is gentler).
- Cuts: the skill's `scripts/plan_cuts.py` (copy with `--no-zoom`) -> `work/edl.json`. Words mapped to the edit
  (`map_to_edit`) -> `work/words-edit.json`. No base edit is rendered in Phase 1 (that is Phase 3).
- Claude: retakes in 10-minute windows; outline (sentence-level transcript) then one call per chapter. `check_overlays`
  enforces the house rules (inside chapter, no overlaps, spacing, limits). Outputs `longform.json` and `chapters.txt`.
- Front end: `app/long.js` (global `LF`, loaded on demand by `loadLong()` in short-form `flow.js`) + `long.css` (loaded when
  `/api/sections` says long is on). Project screen = rough preview: plays the raw file, skips cuts, draws overlays in HTML.
- Short-form hook (small, guarded): `server.py` (import + `/api/sections` + two dispatch lines), `app/flow.js`
  (`SECTIONS`, `section`, `loadLong`, `newInSection`, `openCreate`, `sectionSwitch`), `app/home.js` (switch in `showHome`,
  New button -> `newInSection`). Short-form flow re-tested: wizard, Open, BROLL01416417 opens read-only.
- Not done yet: a full-hour run, Claude-less path in the UI, dark-theme check of the project screen, Intel/clean-Mac install.

## Phase 2 and 3 as built (v0.3.1)

- **Editor** (`app/editor.js`, global `LFE`): preview that plays the raw file and skips cuts (edited time <-> raw time through `edl.json`),
  zoomable timeline (canvas ruler + waveform drawn for the visible range only, DOM blocks for chapters/lower-thirds/cards),
  inspector, undo/redo (JSON snapshots), save (`POST /api/long/save` -> `longform.json`, backup in `work/backups`, refreshes `chapters.txt`).
  Waveform = `work/peaks.json` (10/s of RAW time, built once by ffmpeg, mapped through the cut list). `S.dirty` is set so the short-form
  `leave()` prompt works. Chapter drags move blocks in place (re-rendering mid-drag kills pointer capture).
- **Graphics are shared:** `app/overlays.css` + `app/overlays.js` (`OV.lowerThird/card/endcard/caption`) draw the preview AND the render, sized in cqw.
  Card spec fields added: `pos` left|centre|right, `anim` slide|fade|pop|none (also on lower-thirds: `pos` left|right).
  Caption spec: `captions.size` and `captions.bottom` are px on a 1920x1080 frame.
- **Render** (`render_long.py`, `render_overlays.cjs`, `app/render.js` global `LFR`): NOT HyperFrames (a browser drawing 108k frames is too slow, and
  this ffmpeg has no libass/drawtext). Headless Chrome (hyperframes' chrome via `npx hyperframes browser path`, puppeteer-core found in the npx cache or
  installed to `~/.cache/studio-longform`) draws transparent PNG frames per lower-third/card (entrance, one held frame, exit) and one PNG band per
  highlighted caption word; then ONE ffmpeg pass: `select` the kept segments (cut list), scale to 1920x1080, `overlay` every graphic with
  `-itsoffset`, `tpad`/`apad` for the end screen (appended after the video), encode with h264_videotoolbox (settings.json `software_encode: true`
  for x264, `video_bitrate` default 10M). ffmpeg 7+ needs `-/filter_complex`; handled. Drawn frames are cached in `work/render/gfx` (hash of item + css/js).
  Previews (`mode: preview`, t0, length) seek the input first, so a preview at minute 50 costs the same as at minute 1.
- **Blur / redact regions** (v0.3.1): `longform.json` `redactions[]` = `{t, dur, type: blur|pixel|box, strength, w, h, track, keys:[{dt,x,y}]}` in 1920x1080 frame px
  (x,y = top-left; w,h shared by all keys; `track:false` keeps one key). Editor: Blur lane, draggable/resizable box on the preview (`rdDrag`), points
  added when Follow movement is on. Render: in `s_video`, per region `split` -> `crop` (x,y piecewise-linear in `t`, `exact=1`) -> `gblur`/pixelate/`drawbox` -> `overlay` with `enable=between(t,..)`,
  placed BEFORE the graphics overlays. The editor preview uses CSS `backdrop-filter` (an approximation, pixelate looks like a blur there).
- **Free placement** (v0.3.1): cards and lower-thirds take optional `x`,`y` (top-left, 1920x1080 frame px) that override the `pos` preset. `OV.place()` in `overlays.js` applies it for both the preview and the render; dragging on the preview is `ovDrag` in `editor.js` (moving must not rebuild the element, so `mount()` ignores x,y in its key).
- Routes added: save, peaks, words, render-start, render-status, render-stop, render-file.
- Not done: effects such as punch-in zooms (long-form default is none; `plan_cuts.py --no-zoom`), drag-to-position cards on the preview,
  a full-hour render, dark-mode check, timeline thumbnails.

## Cuts (v0.4.0, 2026-10-15)

- `app/editor.js`: a **Video** lane (`E.clLane`, `renderClips`) shows each segment of `E.segs`. Split (S), I/O marks + Delete
  (`removeRange`), clip delete (`E.clipSel`, separate from `E.sel`), edge drag (live on the block, applied on release) and the
  nudge buttons in `clipInspector`. Every cut applies immediately through `applyCut(newSegs)`: `remapper()` maps old edited
  time → raw → new edited time (a removed moment lands where playback carries on); lower-thirds, cards and blurs keep
  `t`/`dur` (dropped if less than 0.5 s is left); a chapter whose start lands within 1 s of the next is dropped; words are
  re-made from the camera transcript (`/api/long/words?raw=1` → `mapToEdit`), so brought-back material has words.
- Undo covers the cut list (`stateJ` = spec + segs). Save posts `segments` when `E.segsDirty`; `longform.py save_cuts()`
  clamps to the camera file, backs up `work/edl.json` to `work/backups/edl-<stamp>.json`, writes it, and rebuilds
  `work/words-edit.json` with `pipeline_long.map_to_edit`; `duration` comes from the new segments. No re-render: the preview
  plays the camera file through the cuts and the render reads `edl.json`.
- Note (2026-10-15): the camera files of `SFH AI Workshop Oct 5 2026` (Desktop) and `Test 6 min` (an old scratchpad) can't
  be found any more; their `raw/` links are broken.

## Overlay videos (v0.5.0, 2026-10-16)

- Same `overlays[]` shape as short-form, but `src` is an absolute path (linked, not copied). `POST /api/long/choose-overlay`
  (Finder), `GET /api/long/overlay-file?src=` streams it (Range) for the preview.
- `editor.js`: lane `ov` in `LANE_KEYS` (generic t/dur blocks; left trim moves `in`, right trim stops at the clip's end),
  `inspectorOv`, `syncOverlays()` (one `<video>` per overlay in `E.vLayer`, synced in `paint()`, main volume = lowest duck),
  `ovVidDrag` (move; bottom-right corner resizes). `applyCut` moves overlays.
- `render_long.py s_video`: each overlay in the window is an input (`-ss in -t len`), scaled/cropped, `fps`, rounded corners
  for pip via `geq` alpha, opacity, alpha fades, `setpts` to its start, `overlay … enable=between()`; placed before blurs.
  Unmuted + has audio → `aformat,volume,afade,adelay` and `amix` with the main audio; ducks → `volume='…':eval=frame` on it.
- Tested: 14 s preview render with a full overlay (sound on, speaker at 15%) and a pip on track 2: picture correct, audio graph
  correct. Seen on the stand-in camera file only: the preview's video stream came out 11.5 s for a 14 s window, with or
  without overlays (not from this change); check on real footage.

## Open questions for the user

- Run the full 77-minute video through the render (ask first; see benchmark in the final message)?
- Zooms/effects on the video itself (gentle punch-ins) for long-form: wanted?
