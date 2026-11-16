# Studio AI short-form editor: project handover

**Next work:** see `../ROADMAP.md` (phases agreed 2026-10-15: auto-filled takeovers, overlay video tracks short-form then long-form, polish).

A local, browser-based timeline editor for your brand talking-head videos, built on top of the
**studio-reel** Claude skill and **HyperFrames** (HTML → MP4 renderer).
Read this first; `README.md` (using it) and `01. Installation/INSTALL.md` (installing it) are the user docs.

**Location (since 2026-10-08):** `02. Claude/04. Studio AI short-form editor/01. Studio AI Short-form Video Editor`
(formerly `02. Claude/04. the default brand Reels Timeline`). Its sibling `02. Studio AI Long-form Video Editor` is a
separate project for 60+ min videos. Both share **one dashboard** (this server, port 4321): the splash asks Short-form
or Long-form, and Open has a Short-form | Long-form switch. Long-form code lives in its own folder and plugs in through a
small guarded hook here (`server.py` hands `/long/…` and `/api/long/…` to its `04. Editor/longform.py` when present;
`GET /api/sections`). Short-form behaviour must not change. See that folder's CLAUDE.md for the plan.

## Folder layout (everything lives here, including videos and renders)

```
01. Installation/  Install Studio AI short-form editor.command (runs 03/install.sh), Check setup.command, INSTALL.md
02. Skill/         studio-reel: bundled copy of ~/.claude/skills/studio-reel (refreshed by make-package.sh)
03. Tools/         install.sh (one-click installer), doctor.py (setup check), make-package.sh
04. Editor/        server.py, pipeline.py, app/ (index.html, app.js, home.js, app.css, preview-shim.js), VERSION
                   local state: .recent.json, .cache/thumbs, settings.json (optional; not packaged)
05. Projects/      one folder per video: raw/ (camera file), work/ (transcript, grade, edl.json, retakes.json), edit/
06. Renders/       finished MP4s by format: Reel 9x16, Feed 4x5, Square 1x1, Landscape 16x9 (+ Previous versions/)
07. Packages/      Studio-AI-Short-form-<version>.zip for the team
Open Studio AI short-form editor.command   → starts 04. Editor/server.py on http://127.0.0.1:4321
```

**The skill is the source of truth for the look.** It's installed at `~/.claude/skills/studio-reel`
(scripts/build.py, plan_cuts.py, edit.py, grade.py; template/motion-lib.js, styles.css, brand.css;
references/reel-spec.md, example-reel.json, example-takeovers.json). Edit the installed copy, then
`03. Tools/make-package.sh` copies it into `02. Skill`. Never edit only `02. Skill`.

## How it works

- **server.py** (Python 3.9 standard library only, no pip deps): serves the app; `P.proj` = the open
  project's `edit/` folder. Every edit POSTs the spec to `/api/preview`, which writes it into a shadow
  copy `edit/.editor/preview/` (symlinks to the video, transcript and assets) and runs the skill's
  `build.py` there, so the preview is the real composition and `reel.json` only changes on Save
  (`/api/save` backs up to `edit/.editor/backups/`). Other endpoints: project/reels (Spotlight discovery via
  `mdfind`), thumbs, peaks (ffmpeg waveform), filmstrip, edl (zoom segments), zoom apply (re-renders the base
  edit with edit.py into a temp file, swapped in only on success), new-video upload/start/status,
  render (→ `06. Renders/<format>/`), reveal (Finder), delete (moves the project to ~/.Trash, keeps renders),
  brand assets (`/brand/*`: fonts, white logo, light logo + favicon mark generated from the white logo SVG).
- **pipeline.py** (New): setup (hyperframes init) → transcribe raw (whisper medium.en) → grade.py →
  retakes (Claude) → plan_cuts.py `--format` → edit.py → transcribe edit → plan (Claude writes reel.json) →
  build. Claude runs as **`claude -p`** (Claude Code headless, the user's own login; no API key, no SDK:
  the Mac only has Python 3.9). Missing/signed-out Claude → those two steps are skipped, everything else runs.
  The plan prompt includes SKILL.md step 6, house style, reel-spec.md, the example for the chosen template,
  format guidance, notes and the indexed transcript; a plan that fails to build is sent back once with the error.
- **Layout (UI pass, v1.9):** header (logo · Video Editor · name · status chip | undo/redo, shortcuts, theme,
  New, Open, Save, Render) → grid of a big centred preview (`fitScreen()` fits any format into `.stage-in`) with
  an icon playback bar, plus a 380px side panel → timeline (height `clamp(240px, 37vh, 440px)`, draggable).
  Icons: `app/icons.js` = bundled Lucide SVGs; `<i data-ico="name">` in HTML, `icon(name)` (string) or
  `ic(name)` (element) in JS. Track headers show counts; empty Takeovers/Text/Chips/Effects/Sounds go slim
  (`laneCounts()`); words are drawn over the audio waveform. Panel buttons get icons via `decorateButtons()`.
- **Entry flow (v2.0):** `app/flow.js` = splash (once per browser session, `sessionStorage.splashSeen`) →
  wizard overlay `#wizard` (① look Clean/Takeover with CSS mock-ups → ② format, drop zone, name, notes →
  ③ upload + live steps) → `openReel()` loads the timeline. `resumeWizardJob()` resumes step ③ after a reload.
  `openWizard()` is used by the header New button and the New video tile. The older in-editor New screen
  (`enterNew`/`newForm`/`startNew`/`showJob` in home.js) is no longer reached; safe to delete later.
- **app/** (vanilla JS, no build step): `app.js` = timeline, inspector, drag/snap, captions, zoom, effects,
  takeovers, save/render, theme; `home.js` = Open (library) and New (format + template pickers, upload,
  step progress, resume after reload); `preview-shim.js` is injected into the preview page only.
- **Cuts (v2.2):** the Video track draws one `.clipb` per cut-list segment (`work/edl.json`, raw camera times). Split (S),
  I/O marks + ⌫, clip delete and edge trims (drag, snaps to words; or nudge buttons in `clipPanel`) change a working copy
  `S.cut.segs` (part of undo via `stateJSON`). Removed parts show as `.cutzone`, and the shim's `setSkips()` jumps over them
  in the preview. **Apply cut** → `POST /api/cuts/apply {segments}` → `apply_cuts()` in server.py: `cuts.py` maps every
  old edited time → raw → new edited time (a cut moment lands at the next kept frame), rewrites `edit/transcript.json`
  (old words keep their text; brought-back material takes words from `work/transcript.json`), caption indices
  (fix/drop/keywords/groups), every reel.json time (`_refs`, mirrors `refs()` + out/until) and `duration`; items whose
  start was cut are dropped unless ≥0.8 s of them is left. edit.py re-renders the base edit (same job dict as zooms,
  `kind: "cuts"`); files are swapped only on success; backups in `edit/.editor/backups/cuts-<stamp>/`. Pending zoom
  edits are folded into the working segments. The planner's last segment can run past the camera file; segments are
  clamped to the file's duration (`raw_dur` from `/api/edl`).
- **Moving cards and blurs (v2.3):** `#ovl` overlay over the preview (`drawOverlay`, `ovPointerDown`). Card boxes are measured
  in the active iframe (`cardBox`: union of the host's `.g` rects, canvas px); dragging sets the host's CSS `translate` live,
  then saves `x` (group centre, read by `centreCards()` in motion-lib via `data-x`) and moves `top` (reel) or `y` (other
  formats). Blur regions = `redactions[]` (same shape as long-form, `type` blur|box only: Chrome's backdrop-filter can't
  pixelate), drawn by build.py as `.redact` divs after the video (z-index 1, under cards) with `backdrop-filter`; `track` +
  keys glide via `redact()` in motion-lib. `rdPos()` mirrors that for the overlay. Blur lane `rd`, `rdPanel`, `startRdDrag`.
  `cuts.py remap_spec` moves redactions too. Checked with `hyperframes snapshot`: blur and moved cards render.
- **Auto-filled takeovers (v2.4):** `fill.py` + `POST /api/takeover/suggest {kind, t, spec}`: words from t-1 s to t+25 s,
  the spec's takeover section and example-takeovers.json go to `claude -p`; reply `{"takeover": {...}}`. Fallback (no Claude /
  signed out) = sentence at the playhead. Kinds list|pip|stat|recap|headline ("Big text", title only). `addTakeover()` inserts
  the template, then `fillTakeover(obj)` swaps in the reply if that same object is still there (undo-safe); panel button refills.
  Signed-out detection also matches "Failed to authenticate / session expired" (also in pipeline.py).
- **Overlay videos (v2.4):** `overlays[]` (see reel-spec). build.py: `<video class="clip overlay">` with data-media-start,
  muted / data-has-audio + data-volume + data-fade-in/out, placed after the main video and before blurs; `ovfade()` in
  motion-lib fades opacity; `duck` < 1 becomes a `data-automation` volume lane on `#a-roll`. Preview shim mirrors each
  overlay onto its own canvas (`ovs`, `ovSync`, clip-path hides the element), syncs time/play/mute, applies the volume lane
  to the main video; `restyle()` for live drags. Editor: `+ Video` → `/api/overlay/pick` (Finder, copies to
  `edit/assets/overlays/`), Overlays lane (`--ovrows` rows, `startOvDrag`), `ovPanel`, pip drag/resize via `#ovl` (`dragOv`).
  cuts.py moves overlays (a cut start advances `in`). Full HyperFrames render tested (2026-10-16): overlay picture, its sound
  (a test tone at -9 dB only while it plays) and the speaker ducking (about -12 dB) all come through. Gliding blurs move by
  transform (x/y from the first key), not left/top: HyperFrames lint flags left/top tweens as stuttery.
- **Preview quirk (important):** Chrome stops compositing a large scaled `<video>` inside an iframe after a
  seek (goes black), so the shim mirrors frames onto a canvas in the video's place. The canvas copies the
  video's inline transform/left/top/width/height/borderRadius each frame (punch/push effects, takeover pip)
  and re-sizes itself to stay cover-fitted. The video URL is versioned (`?v=mtime`) so re-renders aren't cached.

## reel.json (spec) keys the editor uses

`format` reel|feed|square|landscape · `layout.cards` right|left|centre (landscape) · `template` clean|takeover ·
`captions` {fix, drop, keywords, groups, lead, size, top, max_words} · `cards[]` (11 types incl. `text`;
`top` in reel, `y` vertical centre in other formats) · `takeovers[]` (full|pip; kicker, title, items[{text,t,logo}],
numbered, stat{value,count,prefix,suffix,bar,label}) · `fx[]` punch|push|flash · `sfx[]` pop|tick ·
`endcard` {duration, lines[{text,bold}]}. Unknown keys are preserved. Full spec: `reel-spec.md` in the skill.

The short-form keydown handler returns early while `#lfview` (the long-form editor) is open; long-form has its own keys.

Formats (build.py `FORMATS`, mirrored in app.js `FMTS`): reel 1080×1920; feed 1080×1350 (captions y660,
cards cy1040 ×0.86); square 1080×1080 (y560, cy832 ×0.74, zooms 1.2/1.12); landscape 1920×1080 (side panel
cx1400/520/960, cy470 ×0.78, captions lower third y880, zooms 1.15/1.1). Non-reel formats scale card groups
onto a panel point in `centreCards()`; reels are unchanged (verified by diffing builds).

## Decisions and why

- Local app (not Vercel yet): FFmpeg/whisper/HyperFrames/Claude Code must run on a real machine. Team
  plan discussed: option 1 = one cloud server + team login (Google, @example.com) on a hidden subdomain
  like studio.example.com; option 2 = Vercel front end + workers + storage. Not started; needs to know
  what example.com is built on. Native macOS wrapper (Swift WKWebView) discussed, not built.
- Library inside this folder (user wanted one place); updates = copy 01–04 over, never touch 05/06.
- Renders never overwrite: an existing file moves to `Previous versions/<name> — <date>.mp4`.
- Brand: forced **light** theme by default matching example.com (bg #f5f3f3, white 16px cards, ink #2d3136,
  Trustline #2563eb, gradient 255.6deg #22d3ee→#2563eb, pill buttons, Display + Inter served locally), with a
  ☾/☀︎ toggle to dark (remembered per browser). Product name: **Video Editor**; "Reel 9:16" stays a format name.
- End screen default: lines Follow + bold for more
  (the old `headline` with `*…*` rendered literal asterisks).
- Add buttons stay separate (+ Text, + Chip, + Card, + Takeover, + Effect); their drop-downs are single-column.

## Git (since 2026-10-16)

- One repository at `04. Studio AI short-form editor/` (both editors, Team Package scripts, README, ROADMAP). `.gitignore`
  keeps out 05. Projects, renders, 07. Packages zips, Team Package/Packages, `.recent.json`, `.cache`, `settings.json`.
- Each installed skill has its own repository: `~/.claude/skills/studio-reel`, `~/.claude/skills/studio-longform`.
  Commit skill changes there; `02. Skill/` copies (refreshed by make-package) are tracked in the main repo as snapshots.
- The package scripts exclude `.git`, `.gitignore`, `.gitkeep`. Tags: `short-v<version>`, `long-v<version>` on releases.
- Local only (no remote). The Display font is licensed: never push these repositories to a public host.
- Author: the owner <you@example.com> (set per repository, not globally).

## Working conventions (from the user)

- Ask before long jobs (full renders) — the user once declined a test render. Prefer short test clips
  (15–40 s cut from `~/Desktop/01.mov`, portrait 4K) and do test work in a scratch folder, not the library.
- Don't touch the user's real videos (e.g. `05. Projects/BROLL01416417`, the Video Callouts reels in
  `../00. Cloned Repos/03. Video Callouts`) beyond opening them read-only.
- Bump `04. Editor/VERSION`, run `bash "03. Tools/make-package.sh"`, keep only the newest zip in 07.
- Use a safe-rm pattern in scripts (`"${VAR:?}/path"`); a blanket rm on variables is blocked.

## How to test

- Start: `bash "Open Studio AI short-form editor.command" --no-open` (or `pkill -f server.py` first to restart).
- Pipeline without Claude: import `pipeline`, `Job(root, raw, "", skill, env, {}, fmt, template)`, set
  `j.claude = None`, `j.start()`. Claude prompts can be checked with a stand-in script via
  `settings {"claude_cmd": <stub>}` that saves stdin and prints JSON.
- Layout QA: build a reel.json with every card type, then
  `npx -y hyperframes@latest snapshot --at <times> --no-end --describe false -o ../snaps` and read the contact sheets.
- Setup: `python3 "03. Tools/doctor.py"` (add `--claude` to test the sign-in).
- Package: unzip `07. Packages/*.zip` somewhere temporary, run its installer with `printf '\nn\nn\n' |`.

## Status (v2.4.1, 2026-10-16)

v2.4.0 adds auto-filled takeovers (+ Big text) and overlay videos (ROADMAP phases 1, 2, 4). v2.3.0 adds moving cards on the preview and blur/box regions (skill: build.py `data-x` + redactions, motion-lib
`centreCards` x + `redact()`; reel builds without them are unchanged, verified by diff). v2.2.1 fixes the side panel (the New wizard's mock-up used a global `.row` class that overrode every inspector row;
mock-up styles are now scoped under `.phone`, keep it that way) and makes the side panel resizable (`.vresizer`, `--insp-w`,
300–760px; timeline height and panel width are remembered per browser in localStorage `tlHeight`/`inspWidth`; double-click
a handle to reset). v2.2.0 adds cutting (split, trim, delete parts) to the timeline; tested on a 25 s test clip (delete a range, trim both
ends, bring material back) and in long-form. v2.1.0 added the Long-form hook (section choice, Open switch, `/api/sections`, guarded import in `server.py`). The team zip with both editors is built by `../Team Package/Build team package.sh`.


Done and tested: splash + 3-step New wizard (end to end with a stand-in Claude) · UI pass (layout, icons, home filters) · New (4 formats × 2 templates) · Open/search/delete/Show in Finder on rendered cards · timeline (takeovers, text, chips,
cards, captions, effects, sounds, zoom, video filmstrip, words, audio) · caption word editing · zoom
re-render · effects + sounds in preview · takeovers incl. pip · end screen lines · light/dark ·
Projects/Renders layout · installer, setup check, package.

**Not yet verified:** a full render into `06. Renders` with the new layout; Claude's real plans for landscape,
feed, square and takeover templates; real landscape footage; a first install on a clean Mac; Intel Macs.

**Next ideas:** matching a reference reel from New; team hosting;
drag-to-reposition cards in the preview; user-arrangeable panels.
