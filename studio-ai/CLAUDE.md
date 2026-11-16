# Studio AI: project handover

**What it is:** the next generation of the Studio AI short-form editor, where ROADMAP phases 5-7 are built (client brand kits,
the AI studio, ready for the team web portal). It started on 2026-10-16 as a copy of short-form v2.4.1 and long-form
v0.5.0. The stable editors in `../01. Studio AI Short-form Video Editor` and `../02. Studio AI Long-form Video
Editor` stay as they are and keep serving the team until Studio AI replaces them. Plan: `../ROADMAP.md`.

**Read next:** `01. Short-form/CLAUDE.md` and `02. Long-form/CLAUDE.md`. They describe how everything works. Their
architecture, rules and conventions apply here, with the differences below.

## Folder layout

```
03. Studio AI/
├── 01. Short-form/      02. Skill (studio-reel, Studio's own copy), 04. Editor (server.py hosts the dashboard,
│                        long-form and brands), 05. Projects, 06. Renders
├── 02. Long-form/       02. Skill (studio-longform), 04. Editor, 05. Projects, 06. Renders
├── 03. Brands/          brand kits (<id>/brand.json + assets), brandkit.py, pdfpages.swift, logocrop.swift
├── 04. Installation/    install.sh, doctor.py, the two .command files, INSTALL.md, Build Studio package.sh,
│                        Packages/ (the team zip; not in git)
├── Open Studio AI.command   → http://127.0.0.1:4322
├── README.md, PORTAL.md (the portal handover), SOCIAL.md (linking the social channels), VERSION (Studio 0.8.0; short-form 2.7.0, long-form 0.8.0 in their 04. Editor/VERSION)
└── CLAUDE.md            this file
```

The editors' own `01. Installation`, `03. Tools` and `07. Packages` were removed (2026-10-16): they installed and
refreshed skills through `~/.claude/skills`, which belongs to the stable editor. Studio installs and packages only from
`04. Installation`.

## Differences from the stable editors

- **Port 4322** (stable: 4321), so both can run side by side.
- **Own skill copies:** `server.py` uses `01. Short-form/02. Skill/studio-reel`, `longform.py` uses
  `02. Long-form/02. Skill/studio-longform` (env `STUDIO_REEL_SKILL` / `STUDIO_LONGFORM_SKILL` override). In Studio
  these copies are the source of truth; edit them here. `~/.claude/skills/*` belongs to the stable editor.
- **Long-form hook** also finds the sibling folder `02. Long-form`.
- `.gitignore` rules use `**/` so the nested folders here are ignored too.

## Release v0.8.0 (2026-10-18)

Phase 9 (the social planner: Post it, Calendar, Social settings, email notifications, connections for YouTube,
Facebook, Instagram, TikTok and LinkedIn, Results), the user guide's chapter 08 "Post and plan", and phase 8's Windows
groundwork (phase 8 itself dropped). Short-form 2.7.0, long-form 0.8.0. The package also carries `SOCIAL.md` and
`08. Planner/README.md`, and now leaves out files git doesn't track (so the studio-reel icons the skill downloads on
demand stay out). Tag `studio-v0.8.0`.

## Release v0.7.0 (2026-10-16)

Phases 6 (AI studio, inserts) and 7 (ready for the team portal). Short-form 2.6.0, long-form 0.7.0. The package now also
carries `PORTAL.md`; README and INSTALL describe the AI studio and the portal. Tag `studio-v0.7.0`.

## Release (v0.5.0, 2026-10-16)

- `04. Installation/install.sh` is the stable installer with step 6 changed: it checks the bundled skills, the default brand
  kit and Swift, and never writes to `~/.claude/skills`. The Desktop shortcut is `Studio AI.command`.
- `doctor.py` checks the bundled skills, brand kits and Swift (optional) instead of `~/.claude/skills`.
- `Build Studio package.sh` → `04. Installation/Packages/Studio-AI-<VERSION>.zip`: both editors without
  projects/renders/caches/local state, only the `default` kit (client kits stay on the Mac), the installer.
- The header, splash and page titles say **Studio AI**, so it's never mistaken for the stable editor.

## Phase 5 (client brand kits): progress

Done (2026-10-16):
- `03. Brands/default/` made from today's look (colours from `brand.css`, Display + Inter, white logo, end-bg.jpg,
  the standard end screen lines, house tone of voice).
- **studio-reel reads a brand:** `scripts/brand.py` + a few lines in `build.py`. `reel.json` `"brand": "<id>"` appends
  one generated stylesheet:
  - the `:root` tokens are redefined;
  - client fonts are registered under the template family names "Display" / "Inter" (nearest weight per used weight;
    no files → Helvetica/Arial, never Display);
  - the rules in `styles.css` with literal colours are restated: `.g::before`, glows, `.orb`, icon tints, `.ubub`,
    `.tkbg` + blobs, `.tkb`, and the end screen / takeover background;
  - the hub line gradient (`#gLine`), the end screen logo and the default end screen lines come from the kit.
  - No brand or default → nothing changes. **Verified byte-for-byte** against the stable skill on six builds
    (BROLL01416417's spec, example-reel in all four formats, takeovers). A test client kit (teal/orange, Trebuchet,
    own logo and lines, no background image) was snapshotted with `hyperframes snapshot`: captions, cards, pip and full
    takeovers and the end screen all take the brand.
- **Long-form `overlays.css`:** colours and fonts are `--ov-*` variables whose fallbacks are the old values (not yet
  screenshot-compared, but by CSS rules the look is the same).

Done (2026-10-16, second pass):
- **Shared module `03. Brands/brandkit.py`** (stdlib): list/load/save (old brand.json → `<kit>/.backups/`), new kit from a
  name, safe uploads into fonts/logos/images, contrast ratio, and `long_css()` (the `--ov-*` variables + `@font-face` under
  unique family names "Brand Display <id>", so the editor's own UI fonts are never replaced).
- **Long-form reads the brand:** `longform.json` `brand`. Editor preview: `applyBrand()` in `editor.js` adds
  `<link id="lf-brand" href="/brands/<id>/long.css">` (removed on close). Render: `render_long.py s_prepare` copies the kit's
  fonts/logo/background into `stage/brand/`, appends `long_css(kit, "brand/")` to the stage's `overlays.css` (so the graphics
  cache hash changes with the brand) and uses the kit's light logo on the end screen. `render_overlays.cjs` loads every
  declared font face. Checked on a scratch project: stage files and CSS correct; default stage CSS is identical to the app's.
- **Brands API** `04. Editor/brands.py` (guarded import in `server.py`, like long-form; `/api/sections` reports `brands`):
  routes listed in its docstring. Google Fonts come from Fontsource (api.fontsource.org, no key): catalogue cached 7 days
  in `.cache/fontsource.json`; picking a family downloads the latin woff2 files for the weights the templates use
  (display 500-800, body 400/700, nearest available).
- **Brand screen** (`app/brands.js` in its own scope + `app/brands.css`; header button **Brands**): kit list + Add a
  client; form for client, 12 colour pickers with live WCAG contrast chips, fonts (Fontsource search with each result shown
  in its own font, or upload files; weight guessed from the file name), logos light/dark/mark + background image, caption
  keyword style and weight, end screen lines + CTA, tone of voice. Save/unsaved state; the default brand is read-only.
- **Live preview:** `/brandstage/index.html?t=` is a real composition: a sample reel built once by the skill's
  `build.py` into `.cache/brand-stage/` (rebuilt when build.py/styles/motion-lib change), seeked to 4 moments (caption +
  questions card, statement card, full takeover, end screen). The draft's CSS (`POST /api/brands/<id>/css`, which calls the
  skill's `brand.reel_css(copy=False)`) is posted into each iframe with the end screen lines, logo and line gradient.
  `/brandstage/long.html` draws a lower-third, stat card and caption, or the end screen, with `overlays.css` + `long_css`.
- Tested in the browser (light and dark): new kit, colour changes update all six previews, Poppins search → download → used
  in the preview, save, read-only default kit. Full-size checks of the card, takeover, end screen and long-form graphics.
  default reel builds still byte-for-byte identical (six specs).

Done (2026-10-16, third pass): **a brand per video.**
- **New wizard, step 1 "Who is this video for?"** (short-form and long-form): `brandStep()` in `brands.js` draws the default brand +
  client tiles + Add a client; the steps after it moved up by one. The choice goes to `/api/new/start` (`brand`) and
  `/api/long/start` (`brand` in `project.json`).
- **The spec:** `pipeline.Job(..., brand)` puts `brand` in `reel.json` (client brands only, so default specs are unchanged)
  and starts with the kit's end screen lines; `pipeline_long` puts it in `longform.json` with the kit's end screen.
- **Claude:** `brandkit.voice_note()` adds a "THIS VIDEO IS FOR A CLIENT" block (name, website, tone of voice, call to
  action; never mention the default brand) to the reel plan, takeover fill (`fill.py`, read from `spec.brand`), long-form outline and
  per-chapter prompts. They name the client instead of your brand. A client plan whose end screen mentions the default brand
  (copied from the example reel) gets the kit's end screen instead. Checked with a stand-in Claude that records the prompts.
- **Header:** `#brandChip` shows the open video's brand; its menu switches it (undoable). The end screen follows when it
  still shows the old brand's standard lines; otherwise it asks. "Reset to standard" and re-adding the end screen use the
  brand's lines (`standardEnd()` in app.js). Long-form: a brand select in the editor's top bar, same rule; the short-form
  chip is hidden while the long-form editor is open.
- **Open:** a client filter (shown once any video uses a client brand; remembered per browser tab) and a client badge on
  thumbnails, in both libraries (`/api/reels` and `/api/long/projects` return `brand`).
- **Renders:** a client's videos go to `06. Renders/<Client name>/<format>/` (`renders_dir(fmt, brand)` in server.py,
  `render_long.renders_dir`); the default brand keeps `06. Renders/<format>/`.
- Tested in the browser: wizard steps (both), header switch both ways + undo + live preview rebuild with the client end
  screen, Open filter and badge. Not run: a full New pipeline (whisper + real Claude) for a client video.

Done (2026-10-16, fourth pass): **import a brand guide.**
- Brand screen (client kits): "Import a brand guide" with a PDF/image and/or a website link → `POST /api/brands/<id>/import`
  → `04. Editor/brand_import.py` (`ImportJob`, one per kit, polled with `GET …/import`).
- PDFs: no poppler on these Macs, so `03. Brands/pdfpages.swift` (PDFKit) turns pages into PNGs (+ text layer when
  there is one). It's compiled once with `swiftc` into `04. Editor/.cache/pdfpages` (needs the Xcode command line tools,
  which Homebrew already requires). Work files live in `<kit>/.import/` (git-ignored) and are deleted afterwards.
- `claude -p --output-format stream-json --allowedTools Read,Glob,Grep[,WebFetch]` in that folder: Claude reads the
  contents page, then only the pages it needs. The UI shows "Looking at page N" from the tool-use events. The reply is
  the brand.json fields + `notes` + a Google Fonts look-alike per font.
- Fonts: exact Google Fonts (Fontsource) match first, else Claude's look-alike (recorded as `brand_font` + a note), never
  Display. The result loads as **unsaved** changes with the notes on top; nothing is saved until Save.
- No background image in a kit → end screen / takeover background is a gradient from the dark `takeover_bg` into the
  primary colour (bright brand colours made white text unreadable).
- Tested with GitHub's 89-page brand guide (no text layer): 60 s, 12 pages read, the right palette with hex codes, Mona
  Sans (on Google Fonts, downloaded), tone of voice from the brand attributes, end screen from the guide's own words,
  honest notes (no CTA in the guide, logos not read). Kit saved as `03. Brands/github` (a test kit, git-ignored).

End-to-end run (2026-10-16): a 25 s clip cut from BROLL01416417's camera file → New with brand `github` and the Takeover
look via the same API calls as the wizard → whisper, real Claude retakes + plan (80 s in all: 3 cards, 2 takeovers, 14
keywords, GitHub's end screen, no mention of the default brand) → HyperFrames render (2 min) into
`01. Short-form/06. Renders/GitHub/Reel 9x16/GitHub brand test.mp4`. Snapshots and frames from the MP4 show green
keywords, green-tinted glass, Mona Sans, dark-to-green takeovers. The test project is `05. Projects/GitHub brand test`.

Done (2026-10-16, fifth pass): **logos from a guide.** Claude's reply also gives `logos.primary` / `logos.mark` as
`{file: "<pdf>/page-NNN.png" | image, box: [x, y, w, h]}` (fractions of the page image from the top left; a plain-background
example with nothing else in the box). `03. Brands/logocrop.swift` (compiled like pdfpages) redraws that box from the PDF's
vectors at 1800 px, keys out the plain background (the commonest border colour; it refuses a busy background), trims, and
writes `-crop` (for checking), `-color` (own colours, edges un-blended), `-light` (white) and `-dark` (#111). Claude then
reads the crops once and may correct a box (`"ok"`, a new box, or null). The kit gets `logos/logo-{light,dark,color}.png`
(end screen uses `light`) and `logos/mark-color.png` + `mark-light.png`; a brand with only a mark uses it as the logo too.
Every box is logged ("Cutting primary from … at […]") and kept in `brand.json` `import.logos`.
Tested on the GitHub guide: lockup from page 18 and Invertocat from page 17, clean white versions, 72 s for the whole import.
(Bug found and fixed on the way: the mark-only fallback tested the wrong dict and overwrote the lockup.)

Long-form with a client brand (2026-10-16): the 25 s test clip through the long-form wizard route with brand `github` (56 s:
2 chapters, a lower-third, a card, GitHub's end screen) and a full render into
`02. Long-form/06. Renders/GitHub/Long-form 16x9/`. It found **two long-form render bugs that are also in the stable editor**:
1. `setpts=N/(30*TB)` after the cut gave every frame 30 fps timing, so 25 fps footage played 20% fast against its sound
   (25 s of camera became 20.9 s of picture). Now `setpts=N/FRAME_RATE/TB`, and `fps=30` converts.
2. Chrome saves fully opaque graphics frames (the end screen, the end of a fade) as RGB PNGs and the rest as RGBA. The
   format change mid-stream made ffmpeg rebuild the filter graph, which cut the picture short at the end screen (the sound
   carried on). Now `rgba_frames()` turns every graphics PNG into RGBA (it reads the PNG header; only the RGB ones are
   converted) and every graphics input gets `-reinit_filter 0`. Both are needed: either alone still failed.
After the fixes, picture and sound both run 31.07 s, and the end screen fades in over the frozen last frame as designed.

To do:
1. READMEs and versions (Studio AI release).

Known limits: Fontsource downloads the latin subset only; an uploaded font's weight comes from its file name (check it
for odd names); caption words mid-reveal can look off-centre in the static preview (they're centred as a group when
all are shown).

## Phase 6 (AI studio): progress

Done (2026-10-16), short-form, slice 1 of 2:
- **`04. Editor/studio.py`** (guarded import in server.py like brands; `/api/sections` reports `studio`). Per project,
  `<project>/studio/media/<id>/` (source.<ext>, meta.json, transcript.json, scenes.json, sheet.jpg, thumb.jpg) and
  `studio/clips/<id>/` (job.json, plan.json, title-N.png, filter.txt, clip.mp4, thumb.jpg). Routes are in its docstring.
- **Media bin:** PUT upload (copied, as in short-form); `MediaJob` probes it, makes a contact sheet (≤30 thumbnails, 6 a
  row, one every `sheet_step` s), finds scene changes (`select=gt(scene,0.3)`), and transcribes with the same whisper
  call as the New pipeline (skipped for silent videos). About 4 s per 15 s clip.
- **Ask:** `claude -p --allowedTools Read,Glob` in `studio/`, with each video's length, size, sound, scene times,
  sentence-level transcript (`sentences()`) and contact sheet path, the format, the brand's voice
  (`brandkit.voice_note`), the target length, title cards on/off, and for **Change it** the previous plan. Reply
  `{title, summary, parts:[{video,in,out,why}], titles:[{before,kicker,text,dur}]}`; `clean_plan()` clamps parts to each
  video's length and drops anything shorter than 0.5 s.
- **Build:** title cards are HTML in the brand (kit background or dark-to-primary gradient, display font, kicker colour;
  the default brand = end-bg.jpg + Display) screenshotted by HyperFrames' Chrome (`--headless=new --screenshot`). ffmpeg: each part
  `-ss/-t` → scale/crop to the format, 30 fps; silent parts and cards get `aevalsrc` silence; `xfade` + `acrossfade`
  (0.25 s; 0.04 s when a part is too short); optional music from `05. Music/` (looped, 0.5 volume, fades, ducked by
  `sidechaincompress` keyed on the speech); `loudnorm` (I=-16); VideoToolbox or x264 (`software_encode`).
- **Panel** (`app/studio.js` + `studio.css`, header button **AI studio**): media bin (add/remove, pick which videos to
  use), prompt + length + title cards + music (library or upload), progress, the clip with its title, summary and cut
  list, **Make another**, **Change it**, **Add at playhead** (copies the clip to `edit/assets/overlays/` and adds a full
  overlay with its sound on and `duck: 0`, one undo step), Download, earlier clips, delete.
- Tested with four clips cut from BROLL01416417 (three talking, one silent): a 20 s trailer with 3 GitHub title cards and
  the stand-in music bed in 33 s (Claude 24 s, build 6 s), 1080x1920, streams equal length, music audible on the cards
  and ducked under speech; **Change it** ("faster, ~12 s, open on the speaker") gave 11.98 s in 21 s; Add at playhead
  and undo checked in the browser.
- Fixed on the way (Studio only): undoing everything still showed "Unsaved changes" because drawing the overlay lane adds
  `overlays: []` (`ovList()`); `change()` now compares with an empty overlays list ignored. The stable editor has the
  same harmless quirk.

Done (2026-10-16), slice 2: **true inserts** (short-form).
- `edl.json` segments may have `"src"` (a file, relative to the project folder) with in/out in that file: an insert.
  **edit.py** adds each insert as an input (fill the frame, 30 fps → output rate, its own sound or `aevalsrc` silence,
  no zoom or grade); a cut list without inserts produces the identical filter script (checked).
- **Virtual camera time** (cuts.py): in memory, an insert's in/out are moved to `vbase(src)` = 100000 × (1 + crc32(src)
  % 9000) and up, so Timeline/find/split/trim/remap compare ranges unchanged and an insert never overlaps the camera.
  `to_virtual()` / `to_real()` convert at the edges (`/api/edl` returns the virtual view with `vbase` and `clip`;
  apply_cuts converts the stored list, the editor's list is already virtual, and edl.json is written real). Every insert
  is copied under its own name (`edit/assets/inserts/<clip>-<stamp>.mp4`), so two inserts never share a range.
  `Timeline.to_edit` only looks for "the next kept moment" in the same range; `remapper` lands anything that was inside
  a removed insert where the insert was (and marks it cut, so remap_spec drops it).
- **`POST /api/cuts/insert {clip, t}`** → `insert_clip()`: copies the AI studio clip, splits the camera clip at t (or
  puts it before/after when t is within 0.1 s of a cut, or after another insert), then `apply_cuts()` (re-render +
  remap). Not undoable; the backup in `edit/.editor/backups/cuts-*` is the way back, and the insert can be deleted from
  the Video track like any clip (then Apply cut).
- Editor: inserts are drawn as **Insert** blocks in the brand gradient on the Video track; trims stay inside the clip's
  own file (`vbase`…`vbase + clip`); the clip panel says it's an inserted clip. AI panel: **Insert at playhead** (asks
  first; saves pending edits; refuses while a cut is waiting or a re-render runs).
- Tested on a copy of the GitHub test project ("GitHub insert test"): the 11.98 s clip inserted at 12.1 s → 25.08 → 37.04 s,
  cards/takeovers/words after it moved +11.98 s, base edit picture and sound both 37.04 s, the Video track and preview
  show it; deleting it on the Video track and applying returned every timing exactly. A full HyperFrames render of an
  insert wasn't run (the base edit already contains it; the composition is unchanged).

- **Items across the insert point** (studio.js `insertPlan`): before inserting, everything on screen at the playhead
  is checked (cards incl. text and chips via `span()`, takeovers, effects via `fxSpan()`, overlays, blurs; sounds are
  instants). If something would stay on screen over the whole clip, a dialog names it and offers the nearest clean
  spot just before or just after the block of overlapping items (the block grows while anything overlaps it), plus
  "Insert here anyway". Every insert point is moved to the middle of the nearest pause between words (`wordGap`), so a
  word is never split. Tested: playhead at 8 s inside the takeover 3.4–12.0 → offered 12.20 (after) / 2.70 (before);
  inserted after, the takeover kept 3.4–12.0. The test copy keeps that insert.
- **Server fix:** `ThreadingHTTPServer.request_queue_size` 5 → 128. A page load fires dozens of requests at once and
  the default queue overflowed, resetting one of them now and then (once it was app.css: a page without styles).
  60 parallel requests now all succeed. **The stable editor's server.py has the same default.**

Done (2026-10-16), slice 3: **the AI studio in long-form** (without inserts).
- `studio.py` works on a `Ctx` (project folder, spec file, kind): `short_ctx(edit)` from server.py, `long_ctx(root)` from
  longform.py, which forwards `/api/long/studio/…?root=` and `/long/studio/…?root=` (before it reads the body; server.py
  now passes the query string to long-form POST routes). Long-form clips are 1920x1080 in the project's brand.
- **Linked media:** `POST …/media/pick` opens Finder (several files at once) and symlinks each as `source.<ext>`; deleting
  from the bin never touches the original. Short-form keeps the upload (copy). The music library routes need no project.
- **Panel host** (studio.js): every URL and action goes through `H()`: short-form built in; the long-form editor sets
  `window.LF_STUDIO` in `show()` ({api, file, pickMedia, overlay}) and long.js `close()` removes it and closes the panel.
  Long-form **Add at playhead** (`addAiOverlay` in editor.js) adds an overlay linking `studio/clips/<id>/clip.mp4` with
  sound on and `duck: 0`; Insert isn't offered there yet. The panel goes above the long-form view (z-index 45).
- Tested: four clips linked into "GitHub long test" (analysed in a few seconds), a 15 s cold open with Claude (14.55 s,
  1920x1080, ends on a GitHub title card) in 15 s, Add at playhead in the long-form editor, then short-form re-checked.

Done (2026-10-16), slice 4: **long-form inserts** (undoable, unlike short-form).
- **Editor** (editor.js): the AI panel's **Insert at playhead** (host `insert`) → `insertClip()`: the same clean-spot
  check as short-form (lower-thirds, cards, overlays, blurs; the insert point lands in a pause between words) →
  `POST /api/long/insert-clip {root, clip}` copies the clip to `work/inserts/<clip>-<stamp>.mp4` and returns its virtual
  range (`vbase`, `clip`) → the camera clip is split at the playhead in `E.segs` → `applyCut()` (⌘Z undoes it; Save
  writes it). Insert blocks in the brand gradient; the clip inspector says what it is.
- **Order, not camera time:** with inserts the segment list keeps the editor's order (applyCut and save_cuts only sort
  when there are none). `remapper` finds segments by range in the same space (an item inside a removed insert lands
  where it was), `mapToEdit` / `pipeline_long.map_to_edit` map camera words through the camera clips only (each with its
  own place on the timeline), `removeRange` works clip by clip on the edited timeline, and trims are limited by the
  nearest clips from the same file.
- **Preview:** playback follows the segment list (`E.k`); `advance()` moves to the next clip and jumps the camera video
  only when it isn't straight after; an insert plays in its own `<video>` (`E.insV`, over the camera video, under the
  graphics) via `/api/long/overlay-file`. `seekTo`, `toggle`, `editedNow`, `loop` handle both. `LFE.seek(t)` /
  `LFE.info()` exist for testing.
- **Save:** `save_cuts` converts inserts back to their file's seconds (`cuts.to_real`); `/api/long/project` returns the
  virtual view (`cuts.to_virtual`). longform.py imports the short-form `cuts.py` (same server process).
- **Render** (render_long.py): pieces in order; without inserts the old single-select path is unchanged; with inserts
  `joined_graph()` splits the camera input into one select per run of camera clips, adds each insert as its own input
  (`-ss/-t`, its sound or silence), brings all to 1920x1080, 30 fps, yuv420p, 48 kHz stereo, concatenates, then the end
  screen pad as before.
- Tested on "GitHub long test": at 8 s (inside a card) the dialog offered 0:05 before / 0:12 after; inserted after →
  25.31 → 39.88 s; preview plays camera → insert → camera at the right times; saved edl.json (real seconds), words and
  the second chapter moved +14.57 s; a full render 45.6 s (39.65 + 6 s end screen), picture and sound equal, insert with
  its title card in the middle, captions and card in the right places. The test project keeps the insert.

To do:
1. Long-form "Unsaved changes" stays after undoing everything (it marks any edit as unsaved); compare with the saved
   spec as short-form now does.
2. Phase 6 is otherwise done.

## Phase 7 (ready for the team web portal): progress

Done (2026-10-16), step 1: **one way to call Claude.** `01. Short-form/04. Editor/claude_client.py` is the only place
that talks to Claude; the New pipelines (`pipeline.py`, `pipeline_long.py`, which adds the short-form editor folder to
`sys.path`), takeover fills (`fill.py`), the AI studio (`studio.py`) and brand import (`brand_import.py`) all call
`ask_json(creds, prompt, cwd=, tools=, files=, web_url=, on_event=, timeout=, effort=, should_stop=)` and get one JSON
object back (`ClaudeError`, `NotSignedIn`).
- **Back ends:** `cli` = `claude -p --output-format stream-json --verbose --allowedTools …` (the Mac, as before; Claude
  reads files named in the prompt; progress from the tool-use events). `api` = the Anthropic SDK
  (`client.beta.messages.stream`, model `claude-opus-5-5` unless set, `output_config.effort`, server-side fallback beta
  with `fallbacks="default"`, `web_fetch_20260209` when there's a website, `pause_turn` resumed up to 6 times). The API
  can't open files, so callers also pass `files`: images and PDFs are attached as base64 blocks, text inline, up to 30 MB.
  Brand import picks pages in two passes for the API (contents pages first, then at most 17 pages). The SDK needs
  Python 3.10+, so it's for the portal server, not these Macs.
- **Credentials per request:** `creds_from(headers, settings)`: header `X-Claude-Api-Key` (+ optional `X-Claude-Model`)
  → api with that key; else `settings.json` `claude_backend: "api"` → the server's `ANTHROPIC_API_KEY`; else `claude -p`.
  Jobs keep the Creds they were started with (New, long-form start/retry, studio ask, brand import, takeover fill). A
  key is never written to disk or a log (`repr` hides it).
- Tested: real `claude -p` through the client (takeover fill 14 s, a studio clip 21 s on "GitHub brand test"); the API
  path with a stand-in `anthropic` module (request shape, attachment blocks, pause_turn loop, auth/rate-limit/refusal/
  max_tokens errors, no key → NotSignedIn). Not run: a real API call (no SDK on this Mac).

Done (2026-10-16), step 2: **per-user settings.** `01. Short-form/04. Editor/workspace.py` decides whose storage a
request works in. On a Mac nothing changes (one workspace, "local", the folders inside Studio AI). With **`STUDIO_DATA`**
set (the portal's server), each request must carry `X-Studio-User` (+ `X-Studio-Team`, default "team") and, when
`STUDIO_PORTAL_SECRET` is set, `X-Studio-Portal-Secret`; otherwise 401. Layout and rules are in workspace.py's docstring:
- `users/<user>/`: `settings.json` (on top of `STUDIO_DATA/settings.json`; `library` and `claude_cmd` can't be set there),
  `01. Short-form` and `02. Long-form` (05. Projects, 06. Renders), `Bin/`, `.recent.json`.
- `teams/<team>/`: `03. Brands` (client kits; **your brand always comes from the app's own `03. Brands`** and can't be
  replaced or deleted), `05. Music`, `Bin/` (deleted kits).
- How: `H.parse_request` picks the workspace per request (thread-local). Server state that was global is per workspace:
  `P` (the open project) is a `workspace.Slot`, `render` / `zoomjob` are `SlotDict`s, `build_lock` a `SlotLock`. Every job
  thread is a `workspace.Thread` (keeps its starter's workspace; a plain thread on the portal fails loudly). `ENV` is a
  `workspace.Env`: on the portal it adds `STUDIO_BRANDS` = the team's kits, which studio-reel's `brand.py` reads first.
  `brandkit.root()` / `bin_dir()` are set by server.py to the workspace's folders (`brandkit.HOME` = the app's own folder,
  the Swift tools and the default kit). Long-form's `base()` and `settings()`, the AI studio's `music_dir()` and brand-import
  jobs (keyed by kit folder) follow the workspace. `/api/open` refuses folders outside the user's storage; Open lists only
  their library (no Spotlight, no recent paths elsewhere). `--host` sets the listen address; beyond 127.0.0.1 portal mode
  refuses to start without `STUDIO_PORTAL_SECRET`.
- Tested: the Mac mode as before (library, Open, preview build, kit files, render folder, studio state). Portal mode in the
  scratchpad on port 4330 with users alice/bob (team acme) and carol (team beta): missing user, wrong secret and `../bob`
  → 401; each sees only their own videos and open video; alice can't open a Mac path; acme sees its own `github` kit
  (renamed "GitHub ACME" to tell it apart) and alice's preview build used it, not the app's copy; beta sees only the default brand,
  makes and deletes its own kit (into `teams/beta/Bin`), can't read acme's kit, can't delete the default brand; renders go to
  `users/alice/01. Short-form/06. Renders/GitHub ACME/…`; long-form and studio music come from her storage / team; an AI
  studio upload was analysed in a workspace thread into her project; settings merge (user over server).

Done (2026-10-16), step 3: **no Mac-only bits on the server.** On a Mac every Finder dialog and "Show in Finder" stays
as it was. On the portal (`window.PORTAL`, put into the page's `<head>` by server.py):
- **Resumable uploads:** `04. Editor/uploads.py` (`POST /api/upload/start`, `PUT /api/upload/<id>?offset=`,
  `GET /api/upload/<id>`; parts in the workspace's `uploads` folder, removed after 3 days untouched) and `app/upload.js`
  (`uploadFile()` in 8 MB pieces; after a failure it asks how much arrived and carries on, up to 8 tries with back-off;
  `pickFiles()`, `pickAndUpload()`, `downloadFile()`). A route that needs the file gets `{"upload": id}` and moves it with
  `uploads.take()` (an upload can be taken once; an unfinished one is refused).
- Each Finder dialog has an upload instead: New (`POST /api/new/upload {upload, name, file}` → the new project's raw/),
  overlay video (`/api/overlay/pick {upload}`), the raw camera file for zooms (`/api/zoom/locate {upload}` → the project's
  raw/; refused files are deleted), AI studio media (`POST …/studio/media/add {upload, name}`, short- and long-form; the
  long-form host has no `pickMedia` on the portal), long-form's video (`choose-file {upload}` → `02. Long-form/Uploads/`,
  then **moved** into the project by `create_project`, not linked), its subtitle file (`choose-transcript`) and overlays
  (`choose-overlay {upload, root}` → `<project>/media/`). Without an upload these routes refuse on the portal.
- **Download instead of Show in Finder:** `GET /api/download?path=` (inside the user's storage only; a file in the library
  or a finished MP4; `Content-Disposition: attachment`). Rendered cards, the render window (both editors) offer Download;
  the folder buttons (Browse…, Finished videos, the long-form project folder) are hidden. `/api/reveal`, `/api/browse` and
  long-form `reveal` refuse on the portal.
- **Paths:** every path that comes in is checked against the user's storage (`open`, `thumb`, `download`, long-form
  `overlay-file`, `create_project`'s video and subtitles). Paths the page only shows (`library`, `projects`, render
  `folder`, the raw video, long-form `folder`/`renders`, a deleted kit's `bin`) are relative to the user's storage
  (`Workspace.shown()`; the team's folders as `Team/…`). Paths used as ids (a project's `path`, long-form `root`) are still
  absolute under `STUDIO_DATA`; the portal should treat them as opaque.
- `caps()` on the portal says whether this request has Claude (`the Claude API` with a key, else the server's Claude Code).
- Tested in portal mode (scratchpad, port 4330, and a stand-in portal proxy on 4331 that adds the user headers, in the
  browser): wrong offset → 409 with the size; a dropped piece resumed (server test and the page's `uploadFile` with a
  forced network error: 148 MB arrived byte for byte, 1.4 s); New/overlay/locate/studio/long-form video and subtitles
  from uploads; taking an upload twice or unfinished refused; a too-short camera file deleted; downloads of her MP4 work,
  `/etc/hosts`, another user's file and an outside `overlay-file` are 404; the page hides Browse/Finished videos and shows
  Download; her editor opens through the proxy. Mac mode re-checked: Browse…, Finished videos and Show in Finder are back.

Done (2026-10-16), steps 4 and 5: **`PORTAL.md`** (Studio AI's main folder), the handover for the portal's developer:
how it fits (a reverse proxy adds the user headers), requirements and start command, environment variables and
settings, the headers and proxy settings (timeouts ≥ 5 min, Range pass-through, body sizes), the storage layout, uploads
and downloads, every endpoint, the jobs (what starts them, status routes, steps and tools, typical times, load,
one-at-a-time rules, what survives a restart), and running several users safely (one process per machine, route by team).
Small fixes on the way: `software_encode` defaults to true off macOS (VideoToolbox is Mac-only; the skill's edit.py
already uses libx264), and `/api/new/status` / `/api/new/raw` only answer for the user's own projects.

To do (phase 7): ask the developer what the first portal runs on and fit to it. Known gaps listed in PORTAL.md: PDF
brand-guide import needs macOS (Swift PDFKit; a Linux fallback would use poppler and port logocrop); no server-wide job
limit; video ids are absolute paths under STUDIO_DATA.

## Phase 8 (Windows: a boxed, signed desktop app, building "the same app as on the Mac" first): progress

Plan and decision: `../ROADMAP.md` phase 8.

Done (2026-10-16), plan steps 1-5 (code only; **nothing has run on Windows yet**):
- **`01. Short-form/04. Editor/osutil.py`** holds everything macOS and Windows do differently. On a Mac every function
  does what the code did before (checked: the tools' environment is identical, preview links are still symlinks,
  Spotlight and the Bin as before).
  - `ensure_utf8()` (server.py's first lines): Windows restarts the server in Python's UTF-8 mode; `tool_env()` adds
    `PYTHONUTF8=1` for every tool, so the 165 text reads and writes and the tools' output need no edits.
  - Tools: `tool_env()` builds PATH per OS (Windows: `<Studio>/Tools`, `Tools/*/bin`, `~/.local/bin`,
    `%APPDATA%/npm`; also put on the server's own PATH, since Windows looks up programs there); `NPX` is `npx.cmd` on
    Windows; `claude_candidates()`. `pipeline.find_claude` and `pipeline_long.find_claude` now use
    `claude_client.find_claude`.
  - `pick_files(prompt, kind, multiple)` / `pick_folder()`: osascript on a Mac; a Windows Forms dialog through PowerShell
    (STA, top-most owner, UTF-8 output). It returns paths, so long recordings stay linked. `reveal()`: Finder / Explorer
    `/select,`. `can_search()`: Spotlight only on a Mac. `bin_folder()`: `~/.Trash` on a Mac, `<Studio>/Bin` elsewhere.
  - `link(target, dst, copy_ok)`: a symlink, else (Windows without the right) a hard link for a file or a junction for a
    folder (a copy when allowed: AI studio media). `is_link` / `same_link` / `remove` never delete what a link points
    to. `replace()` retries for 15 s while Windows has the old file open. `kill_tree()` / `stop_tree()` stop a tool and
    everything it started (`taskkill /T`), because npx.cmd → node → Chrome.
- Callers switched: server.py (pickers, reveal, Spotlight, preview links, the two file swaps, render stop, npx),
  longform.py, studio.py, pipeline.py, pipeline_long.py, render_long.py, claude_client.py, workspace.py.
- Paths written into project files use `/` (`as_posix()`: insert `src`, kit file lists, shown paths), so a project
  moves between a Mac and Windows. The page reads Windows paths too (file names split on `/` or `\`, absolute
  `C:\…` paths recognised in long-form).

Done (2026-10-16), plan step 6: **the PDF tools in Python.** `03. Brands/pdftools.py` does what pdfpages.swift and
logocrop.swift do, with the same arguments and output (`pages <pdf> <out> [max] [width]`, `logo <file> <page> x y w h <out>
<name>`), using numpy, pypdfium2 (Google's PDFium; wheels for Windows, macOS, Linux) and Pillow. `brand_import.pdf_tool()`
picks Swift on a Mac (as before; Python if Swift can't build) and Python elsewhere; `STUDIO_PDF_TOOLS=python` forces Python
for testing. Missing packages give a clear error. doctor.py checks them off macOS; PORTAL.md updated.
- Compared on a 3-page test guide made with Chrome (text, a gradient vector logo on white and on dark green): the same page
  count and text layer ("—", "✓" included), the same background colours, logo sizes within 1-3 px, edges about 1.4/255
  apart, and the cut-outs look the same. A full import with real Claude through the Python tools (scratch portal server):
  51 s, colours from the guide, primary logo and mark cut out cleanly.
- Installed on this Mac for testing: `pip install --user pypdfium2 pillow` (pypdfium2 5.14.0, Pillow 11.3.0).

**Dropped (2026-10-18), by the user, to finish the project.** Studio AI stays a Mac app (plus the portal). Steps 1-6
stay in the code: they're the Mac's behaviour unchanged, and `osutil.py` / `pdftools.py` serve the portal on Linux.
Not built: the Windows trial, steps 7-9 (`.bat` launchers, `install.ps1`, the Windows zip) and step 10 (the boxed,
signed app). The plan is kept in `../ROADMAP.md` phase 8.

## Phase 9 (our own social planner, your brand only): progress

Plan and design: `../ROADMAP.md` phase 9, and `07. Concepts/` (the agreed screens).

Done (2026-10-18), 9.1: **Post it** (composer and post pack).
- `01. Short-form/04. Editor/planner.py` (stdlib; the same plug-in pattern as `studio.py`, using its `Ctx`):
  - `PLATFORMS`: ten platforms with their fields and limits (Instagram, TikTok, YouTube, Facebook, LinkedIn, X, Threads,
    Pinterest, Google Business, Bluesky). Text fields count characters; `hashtags` and `tags` are lists, counted as
    items.
  - `DEFAULTS` per format.
  - `draft()`: one Claude call (`claude_client.ask_json`, effort medium) for all enabled platforms, or `only` one.
    The prompt has the transcript (edit words; long-form `words-edit.json`, up to 9,000 words), the on-screen texts,
    the format and length, the team's note, and the voice: your brand's tone and CTA from the `default` kit, or for a
    client `brandkit.voice_note()`. YouTube gets `chapters.txt` appended by code (Claude is told not to list them); a
    9:16 video's YouTube title ends with #Shorts; Pinterest gets the website as its link.
  - Saved in `<project>/planner/pack.json` (edits autosave), `cover.jpg` (ffmpeg frame at t), and `post-pack.zip` (MP4,
    cover, one `<Platform>.txt` each, README) on download.
  - The video: the newest finished render (short-form `.editor/renders.json` → `server.latest_render`; long-form
    `longform.latest_render`, newest `<name>*.mp4` in its renders folder), else the edit (short-form base edit) for
    drafting and the cover.
- Routes: `/api/planner/{state,draft,save,cover,download}`, `/planner/{video,cover.jpg}`; long-form forwards
  `/api/long/planner/…?root=` and `/long/planner/…`. `/api/sections` reports `planner`. `send_file` gained `filename`.
- Page: `app/planner.js` + `planner.css` (theme tokens; light and dark), platform logos in `app/platforms/*.svg`
  (Simple Icons, CC0).
  - **Posts** in the header works for the open short-form or long-form video. The long-form host
    `window.LF_STUDIO` now carries `root`.
  - **Prepare posts** appears when a render finishes (both editors).
  - Four candidate cover frames are taken in the browser from the video.
  - The right column says scheduling comes with the Calendar (9.3), or, for a client video, to hand over the pack.
- Tested on the scratch copy of Studio AI with the demo videos:
  - the default reel (with a stand-in render): draft, rewrite one, hand edits saved, cover, zip contents;
  - the Acme Dental feed video (the prompt in Acme's voice and CTA, never the default brand);
  - the long-form webinar (not rendered: posts still drafted, chapters in the YouTube description);
  - the screen in Chrome for both editors.
  - First with a stand-in Claude (Claude Code was signed out, which Post it reported correctly), then with **real
    Claude** after signing in:
    - the default reel on all ten platforms in 22 s, each written for its platform, true to the transcript, your brand's
      tone and CTA;
    - Acme Dental in 18 s, in Acme's voice and CTA, never the default brand;
    - the long-form webinar's YouTube post in 16 s, with chapters.
    - All fields within their limits.

Done (2026-10-18), 9.2 **Social settings** and 9.3 **planner, calendar and scheduler**.
- **Where:** the workspace's `planner` folder: `<Studio AI>/08. Planner/` on a Mac (git-ignored except its README; not
  in the package), `teams/<team>/Planner/` on the portal. It holds `social.json`, `posts/<id>.json` and
  `covers/<id>.jpg`.
- **`social.py`** (stdlib + zoneinfo):
  - your brand's channels (on/off, account, profile link, usual times like "Tue 09:00", extra hashtags), the
    standard hashtags and the time zone (default Europe/London). Times are normalised; bad ones dropped; unknown
    zones refused.
  - `suggest(platform, after, taken)`: the next usual slot, skipping taken ones.
  - Routes `/api/social`, `/api/social/suggest`.
  - For default videos, Claude's prompt now asks for the standard and per-platform hashtags (checked with real Claude).
  - **Moved to 9.4:** the encrypted token store (no tokens exist until the connections).
- **`posting.py`** (stdlib):
  - One post = one video × one platform × one time.
  - Posts scheduled together share a `group`; the calendar shows one card per group and minute.
  - Statuses: scheduled → due (no connection: post by hand) / posting → live, or failed; posted (marked by hand);
    cancelled. Each change goes into the post's `history`.
  - **The scheduler:** `posting.start()` (server.py, at launch) runs `tick()` every 30 s for every planner folder
    (`planner_dirs()`: the Mac's, or each team's on the portal).
    - Posts whose time has come go to `CONNECTORS[platform]` (filled by 9.5); retries 5/10/20 min, then failed.
    - Without a connector a post becomes **due** and the team is emailed once (see Email notifications below). A due
      post appears in the calendar with **Copy** and **Mark posted**.
    - Everything is on disk, so nothing is lost on a restart.
  - Times from the page's date-time fields carry no zone and are read in the team's zone (`parse(ts, tz)`).
  - Routes: `/api/calendar/{posts,summary,reschedule,cancel,posted,post-now}`, `/calendar/cover/<id>.jpg`.
- **Post it** (`planner.py` `schedule_state` / `schedule`, route `/api/planner/schedule`):
  - the When column: a suggested time per channel, "Same time everywhere", what's already scheduled for this video,
    and **Schedule N posts**;
  - only for rendered default-brand videos (client videos and unrendered ones are refused, with the reason);
  - every platform needs its post written first; past times are refused; the post copies the pack's text and the
    cover.
- **Page:** `app/calendar.js` + `calendar.css`.
  - **Calendar** in the header, with an amber due count.
  - Week view, 06:00-23:00: cards with cover, platforms, time and status. Drag a card to move it (15-minute snap; the
    image's own drag is turned off, it cancelled the pointer). Click to select it.
  - Month and List views; filters by format; your brand's channels; the week's counts.
  - The details panel: per-platform rows, Copy / Mark posted for due ones, Move to a date and time, Cancel, Open video.
  - **Social settings** screen (from the calendar, or "usual times" in Post it).
  - Badges on Open's cards in both libraries ("Next Tue 09:00", "1 due", "Live on 2").
  - Global hooks: `window.openCalendar`, `openSocialSettings`, `refreshPlanner`, `plannerBadge(root)`.
- **Tested** on the scratch copy:
  - settings save and validation;
  - suggestions per platform;
  - scheduling three platforms (client video, past time and unwritten post refused);
  - moving by the API and by dragging in Chrome (Mon 09:00 → Tue 10:00);
  - a post due a minute later becoming "due" by itself in 45 s;
  - mark posted, cancel (refused once posted), the summary and badges;
  - posts surviving a restart;
  - two teams on the portal kept apart;
  - all screens in Chrome.

Done (2026-10-18), 9.4 **the token store, the connection framework and the test platform**.
- **`vault.py`:**
  - macOS Keychain (service "Studio AI"; written through `security -i` so secrets never appear in the process
    list; values base64 JSON);
  - Windows DPAPI via ctypes (written, not yet run on Windows);
  - the portal: Fernet (needs `cryptography` + `STUDIO_SECRET_KEY`);
  - `STUDIO_VAULT=file`, a plain 0600 file, for tests only.
  - Keys: `<team>/app:<platform>` (the developer's app keys), `<team>/token:<platform>` (sign-ins).
  - Checked: the Keychain round trip, quotes and spaces, delete.
- **`connect.py`:**
  - `Connector` (auth, `authorize_url`, `exchange`, `refresh`, `publish`, `results`, `delete`); `REAL` for 9.5;
    `TestConnector` for every platform while **Use the test platform** is on (`social.json` `connections.test_platform`).
  - Who's connected: `<planner>/connections.json` (no secrets).
  - Sign-in: `/api/connect/start` → the platform's page in a small window → `/connect/callback/<platform>` (state
    checked, 15 min) → tokens to the vault → `postMessage` back to the page.
  - Callback address: `public_url` (settings / `STUDIO_PUBLIC_URL`), else `http://127.0.0.1:<port>`.
  - `Channel` objects fill `posting.CONNECTORS`. They refresh tokens that expire within a minute. On an expired-token
    reply they refresh and try once more.
  - Stdlib HTTP client `request()`: streams the video; reads the platform's answer even if it stops the upload early.
  - Routes `/api/connect/{state,test-platform,app,start,disconnect,check}`.
- **`testplatform.py`:** under `/testplatform/` on the same server (on the portal only with `STUDIO_TEST_PLATFORM=1`).
  - A sign-in page (Allow / Deny); tokens that live 2 minutes; upload, publish, results (growing numbers), delete.
  - A feed of what was posted at `/testplatform/`.
  - `/testplatform/control {fail_next, count}`: rate_limit, expired, too_long, server.
- **Screens:**
  - Social settings: per-platform connection status with Connect / Disconnect; the test-platform switch; where
    sign-ins are kept; **App keys (developer)…** (app ID and secret per platform, and the callback address to
    register, with Copy).
  - The calendar marks connected channels.
- **posting.py:** Post now and Cancel are refused while a post is uploading (it could post twice).
- **Tested** on the scratch copy, with the file vault:
  - connect in Chrome through the sign-in window;
  - Deny;
  - three posts due a minute later: the connected one went live by itself (link to the test platform's post);
  - an injected rate limit moved the post 10 minutes on with a clear message, and Post now then made it live;
  - an injected expired token: refreshed and posted by itself;
  - a refresh through Check;
  - Disconnect;
  - a non-test platform refused until 9.5.

**Email notifications** (2026-10-18, instead of Mac notifications, so they work on the portal and reach people away
from the Mac):
- **`mailer.py`** (stdlib smtplib) sends through the team's mail server (Google Workspace, Microsoft 365, or a sending
  service):
  - settings in `social.json` `notifications` (`emails`, `on_live`, `smtp` host, port, security, username, from);
  - the password in the token store (`<team>/smtp`);
  - on the portal, `STUDIO_SMTP_*` can set the server.
- **What's sent:**
  - "Time to post" when a post comes due unconnected;
  - "A post failed" after the last retry;
  - "Live", if chosen.
  - One email per video and moment, plain text plus a branded HTML version, with each post's text to copy and a link
    to `<public url>/#calendar` (which opens the calendar).
  - A mail problem is written into the posts' history; it never stops the scheduler.
- Social settings → **Email notifications**: who gets them, also-when-live, the server, Save password, **Send a test
  email**.
- `social.save()` now keeps the file's other sections (it used to drop `connections`, the test-platform switch).
- **Tested** with a local stand-in mail server (Python's smtpd DebuggingServer; no real email sent):
  - a bad address refused;
  - the test email;
  - due (YouTube, unconnected), live (Facebook, connected) and failed (LinkedIn, last try) each sent their email;
  - the branded email rendered;
  - `#calendar` opens the calendar.

Done (2026-10-18), 9.5 **batch a: YouTube, Facebook, Instagram, TikTok, LinkedIn** (batch b, X / Threads /
Pinterest / Google Business / Bluesky, set aside by the user; they stay reminders on the generic test platform).
- **Research:** each platform's current docs (2026-10-18), written up for the developer in **`SOCIAL.md`** (Studio AI's
  main folder): what app to create, permissions, callbacks, review, limits, what to check on the first live post.
- **`connectors.py`:** the five connections on `connect.Connector`, registered in `connect.REAL`.
  - `HOSTS` are each platform's real servers; `url()` / `page_url()` / `follow()` (upload URLs the platform hands
    out) point at the stand-in when the test platform is on, so **the same code** runs in both modes.
  - `check()` turns each platform's error shape into `ConnectError` / `Expired` with a plain reason.
  - Everything posts at the scheduled time (no platform-side scheduling).
  - Per platform:
    - **YouTube:** PKCE, offline access, resumable upload (public), cover as thumbnail (best effort), Shorts link for
      reels.
    - **Facebook:** Facebook Login → long-lived user token → Page token (never expires); vertical 3-90 s → Reel
      (`video_reels` + rupload + status poll), else a Page video (streamed multipart with `thumb`).
    - **Instagram:** the same Meta app (`SHARED_APP`); the Page's linked professional account; publishing-limit check,
      resumable container upload, status poll, `media_publish` (never twice), first comment, 30-hashtag cap.
    - **TikTok:** hex PKCE; `OPTIONS` mode **inbox** (default: TikTok won't audit own-account tools, and unaudited
      direct posts are private) or **direct** (creator_info check, chunked upload of 10 MB parts above 64 MB, status
      poll). An inbox post returns `handoff`: posting.tick makes it **due** with a `note`, and the team gets a
      "waiting in the TikTok app" email.
    - **LinkedIn:** `OPTIONS` post **as** page (Community Management scopes, `organizationAcls` → the page) or profile
      (OpenID `userinfo`); Videos API parts + ETags, finalize, wait for AVAILABLE, `/rest/posts` (`x-restli-id`),
      `little` text escaping, `LINKEDIN_VERSION`. 60-day sign-ins: `connections.json` `expires`, and Social settings
      warns 15 days ahead with **Connect again**.
- **`connect.py`:**
  - PKCE verifier per sign-in (`start` / `finish`);
  - `options()` / `set_option()` (`social.json` `connections.options`; changing LinkedIn's "as" signs it out) and
    `/api/connect/option`;
  - `request(part=, full=)` (file ranges, response headers) and `wait_for()`.
- **`standins.py`:** each platform's stand-in under `/testplatform/<platform>/<host>/…`, in its own shapes: sign-in
  pages, token endpoints (YouTube and TikTok tokens live 2 minutes; Meta's never expire; LinkedIn's 60 days with no
  refresh), uploads checked byte for byte, processing delays, results, delete. The failure switch answers in each
  platform's error shape and hits API calls, not sign-in. server.py routes PUT and DELETE to the test platform too.
- **Screens:** Social settings shows the per-platform choices (TikTok "How it posts", LinkedIn "Post as") and the
  sign-in warning. A due post's details show its note.
- **Tested on the stand-ins** (scratch copy, file vault):
  - connect all five, with PKCE checked;
  - a 46 MB reel through the scheduler: live on YouTube, Facebook (Reel), Instagram and LinkedIn; TikTok to the
    inbox, with its email;
  - a 16:9 video (Facebook Page video with cover, LinkedIn with escaped characters, YouTube);
  - TikTok direct with 70 MB in chunks;
  - Instagram hashtag cap and first comment;
  - LinkedIn as a profile;
  - results and delete for each;
  - failures: an expired YouTube sign-in renewed and posted; a LinkedIn rate limit and a TikTok server error retried
    later; an expired Facebook sign-in asks to connect again.
- **Not run:** any real account (needs the developer's keys).

Done (2026-10-18), 9.6 **Results**.
- **`results.py`** (stdlib):
  - The scheduler's thread calls `maybe_collect(d)` after each tick (at most every 10 minutes per planner folder).
  - `collect()` pulls a live post's numbers through `posting.CONNECTORS[platform].results()` when due: `TARGETS` =
    1 h, 6 h, 24 h, daily to 30 days, weekly to 90 days, with a half-hour pause after a failed try.
  - Each pull is kept in `<planner>/results/<post id>.json` (`samples`, `dur` from ffprobe, `error`, `tried`).
  - An all-empty reply counts as an error, not a reading.
  - A post remembers whether it went out on the test or the live connection (`post["mode"]`, set in
    `connect.Channel.publish`); results never ask the other one.
  - `report(days, platform, kind)`: totals and engagement; views gained per day per channel (differences between
    pulls, by day in the team's time zone); each channel; top videos (grouped by video root); what works (views per
    post by format and by length bucket); `best_times()`.
  - Best times use every post: views in the first 24 hours (the pull nearest 24 h, once one is at least 20 h after
    posting), grouped by weekday + hour. A channel needs 4 measured posts (`MIN_POSTS`); slots with 2+ posts are
    preferred, and each shows % against the channel's average.
  - Routes `GET /api/results`, `POST /api/results/refresh` (force; all or `ids`). `/api/sections` reports `results`.
- `posting.public()` adds a live post's latest `numbers`; the calendar's post rows show them (`numLine`).
- **Page:** `app/results.js` + `results.css`, opened from the calendar header (**Results**), `window.openResults`, or
  `#results`. It shows:
  - range (7/30/90 days/All), channel and format filters, **Update now**;
  - the totals cards;
  - a stacked SVG bar chart in platform colours;
  - best times, with **+** to add a slot to the channel's usual times;
  - the channel table, the what-works bars, the top videos, and every post.
  - New icons: chart-column, trending-up, refresh-cw, clock.
  - Watch out: the editor has a global `.top` class (its main area); don't reuse that name.
- **Tested:**
  - the pull schedule (unit cases), the 10-minute throttle, and the test/live guard;
  - real pulls from the five stand-ins after posting; posts the stand-ins had forgotten recorded as errors;
  - the screen in light and dark with 29 backdated demo posts and readings (scratch copy only, mode "demo"):
    best times found Facebook's planted Wed 09:00 (+44%); Instagram's planted Fri 18:00 had only one post, so it was
    rightly not suggested;
  - the calendar's numbers.
- **Not shown:** follows gained (per account, not per post).

Done (2026-10-18), 9.7 **handover**.
- **`SOCIAL.md`:** "The order to do it in", and "Review screencasts": which reviews are needed for your brand's own
  channels, the form wording, and a shared 9-step screencast script.
  - YouTube: the audit only if uploads come out private.
  - Meta: App Review only for Advanced access.
  - LinkedIn: the Community Management request text and the Standard-tier recording.
  - TikTok: don't apply; the audit wants TikTok's per-post screen, which a scheduler doesn't have.
- **`PORTAL.md` section 10:** the planner on the portal (`teams/<team>/Planner/`). It covers the scheduler,
  `STUDIO_PUBLIC_URL`, `STUDIO_SECRET_KEY`, `STUDIO_SMTP_*`, `STUDIO_SCHEDULER`, `STUDIO_SCHEDULER_TEAMS`,
  `STUDIO_TEST_PLATFORM`, the outbound hosts, the endpoints, and how to check it. The intro and the env table were
  updated to match.
- **posting.py, one post, one poster:** `tick()` claims a post (`posts/<id>.claim`, `O_EXCL`) and re-reads it before
  changing it; the claim stays until the new status is written.
  - A claim is stale after 3 h, or when its pid on this host is gone. A "posting" post whose claim is stale becomes
    **failed** ("Studio AI stopped while posting this. Check the platform…") and is emailed.
  - `STUDIO_SCHEDULER=0` turns the scheduler off; `STUDIO_SCHEDULER_TEAMS` limits it to some teams.
  - Tested: 3 processes ticking 6 due posts with a slow upload → each posted exactly once, no claims left; a post
    left by a stopped process → failed.
- `connect.public_url()` reads `STUDIO_DATA/settings.json` itself when there's no signed-in user (the scheduler's
  thread on the portal), so email links are right.
- **Calendar:** **Post now** in a card's details (scheduled and failed posts; due ones aren't connected).
- **The final run in Chrome** on the scratch copy, test platform on, five stand-ins connected:
  - Post it → **Schedule 10 posts** at their suggested usual times;
  - **Post now** on each card;
  - YouTube, Facebook, Instagram and LinkedIn live; TikTok to the inbox; X, Threads, Pinterest, Google Business and
    Bluesky due;
  - the matching emails (local stand-in mail server);
  - Results → **Update now** showed the numbers.

Phase 9 is done apart from batch b (X, Threads, Pinterest, Google Business, Bluesky), set aside. Next: the developer
links the real channels (SOCIAL.md). The user guide doesn't cover Post it, the Calendar and Results yet.

## User guide (2026-10-16)

`06. User Guide/Studio AI - User Guide.pdf`: 25 pages, A4 landscape, in the default look (cover and chapter
openers on the end-screen background, Display headings, Inter text, the brand gradient, numbered callouts). Chapters:
welcome and Open, New short-form, the editor (tour, timeline, captions, cards, takeovers, cuts/zooms/overlays/blur/end
screen, shortcuts), render, long-form, brand kits and client videos, the AI studio, good to know. It's in the team
package (`06. User Guide/`, PDF only). Source and how to rebuild or refresh screenshots: `06. User Guide/source/README.md`.
The screenshots are of demo videos made in a scratch copy of Studio AI (fictional client "Acme Dental"), never the
team's real videos. Update the guide when screens change.

## Working rules

Same as the stable editors: ask before full renders; test in the scratchpad with short clips; never touch the user's
real videos beyond reading them; Python 3.9 standard library, vanilla JS, no build step; plain-English updates; show
each phase working before moving on.
