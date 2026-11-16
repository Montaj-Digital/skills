# Studio AI Long-form Video Editor

> **Part of Studio AI.** Open it with `../Open Studio AI.command` (http://127.0.0.1:4322); install with `../04. Installation`. Client brands and the brand per video are described in `../README.md`. Where this guide mentions `01. Installation`, `03. Tools`, `07. Packages`, port 4321 or `~/.claude/skills`, that is the Studio AI short-form editor: Studio AI uses `../04. Installation` and its own skill copies in `02. Skill`.

The long-form section of the Studio AI short-form editor, for 60+ minute talking-head recordings (YouTube, webinars).
It runs inside the same app as the short-form editor: one dashboard, one brand, one light/dark theme.

**Version 0.8.0 (Studio AI):** Post it for long-form videos (YouTube descriptions with chapters) and the calendar. **0.7.0:** client brands, the AI studio and undoable inserts, ready for the team portal. **0.5.0:** overlay videos. **0.4.0:** wizard and pipeline, the timeline editor (now with cutting: split, trim, delete parts), and the render.

## Install (team)

1. Install **Studio AI short-form editor** (short-form) first. This is an add-on to it.
2. Unzip `Studio-AI-Long-form-<version>.zip` **next to** the `Studio AI short-form editor` folder (same parent folder).
3. Double-click **Install Long-form.command** once. It installs the `studio-longform` skill for Claude.
4. Open Studio AI short-form editor as usual. **Let's create** now asks Short-form or Long-form, and Open has a
   Short-form | Long-form switch.

## Use

1. **Let's create → Long-form.**
2. **Choose the video.** A Finder window opens. The file is linked where it is, never copied.
3. **Details.** Name, notes for Claude, and a transcript (optional):
   - *No transcript*: whisper listens to the video.
   - *Paste text*: whisper still listens for timings; your text fixes names, brands and jargon.
   - *SRT or VTT file*: it already has timings, so whisper is skipped (saves 10 to 30 minutes).
   - **Word captions** are on by default. Switch them off in the wizard or on the project screen.
4. **Create.** Steps run on their own; the transcript is made once on the raw video, and the cuts map the words onto the edit.
   An hour can take 20 to 40 minutes, mostly transcribing.
5. **Editor.** Opens when the video is ready:
   - Preview on top (plays your cuts), the inspector on the right, and a timeline for the whole hour underneath:
     waveform, **Chapters**, **Lower-thirds** and **Cards** lanes. Zoom with the slider or ⌘ + scroll; **Fit** shows it all.
   - Click an item to edit it. Drag to move, drag its ends to resize (it snaps to the start of a word; hold Alt to switch snapping off).
   - Inspector: text, type (key point, stat, list), position (left, centre, right), animation (slide, fade, pop, none), start and length.
     Chapter titles and start times too. Nothing selected: captions on/off, size and height.
   - **Move cards and lower-thirds anywhere:** drag them on the preview (Shift keeps the move level). They stay inside the frame.
     The Left / Centre / Right choice puts them back on a preset; X and Y in the inspector give exact positions.
   - **+ Blur** hides part of the picture (a face, a name, a number, a browser tab): **Blur**, **Pixelate** or **Black box**.
     Drag the box on the preview, drag its square handles to resize. Turn on **Follow movement**, move the playhead, drag the box
     again, and it glides between the points (small diamonds on the Blur lane). Blurs sit under the lower-thirds, cards and captions.
   - **Cut the video (trim and delete parts):** the **Video** track shows every clip of the edit.
     - **Split** (or **S**) cuts the clip at the playhead. Select a clip and press **Delete** to remove it.
     - To remove a part: press **I** at its start and **O** at its end (the part turns yellow), then **Delete** (or **Remove**).
     - Drag a clip's ends to trim it, or use the −1s … +1s buttons in the inspector. Dragging an end outwards brings back
       material the automatic edit cut out.
     - Everything after a cut moves with its words straight away; an item that sat only inside a removed part is deleted.
       ⌘Z undoes a cut. **Save** writes the new cut list (the old one is kept in `work/backups`). Nothing is re-rendered.
   - **+ Video** lays another video over this one (an insert, B-roll or a testimonial; linked where it is, not copied).
     It sits on the **Overlays** lane: drag to move, drag its ends to trim (the left end moves where the clip starts).
     **Full screen** or **Picture-in-picture** (drag the window on the preview, its bottom-right corner resizes). **Muted** by
     default; unmute to hear it, and **Speaker** lowers the main video while it plays (15% when you unmute). Opacity, fade,
     track (higher on top). Blurs, lower-thirds, cards and captions always sit above overlays.
   - **+ Lower-third / Card / Chapter** add at the playhead. **Delete** removes. ⌘Z undo, ⌘S save, Space play, ← → move 1 s.
   - **Copy for YouTube** is in the chapters file, `chapters.txt`, which Save keeps up to date.
6. **Render.**
   - **Preview**: about a minute from the playhead with the real graphics and captions (30 to 120 s). Takes under a minute.
   - **Full video**: the whole edit plus an end screen, 1920×1080, to `06. Renders/Long-form 16x9/<name>.mp4`
     with `<name> - chapters.txt` beside it. An older file moves to `Previous versions/`. Drawn graphics are cached, so a
     second render only redraws what you changed.

## What it makes

Inside `05. Projects/<name>/`: `longform.json` (the plan), `chapters.txt` (YouTube timestamps), `work/` (transcript,
`edl.json` cut list, edited word times, the plan steps). The camera file is a link in `raw/`. `work/render/` holds the drawn graphics and previews (safe to delete).

Claude Code (signed in once, in Terminal) is needed for retakes, chapters, lower-thirds and cards. Without it the
cuts and transcript still run.

## Folders

```
02. Skill/      bundled copy of the studio-longform skill
03. Tools/      make-package.sh, install-skill.sh
04. Editor/     longform.py (routes), pipeline_long.py, render_long.py + render_overlays.cjs, app/ (long.js, editor.js, render.js, overlays.*), VERSION
05. Projects/   one folder per long video
06. Renders/    Long-form 16x9/
07. Packages/   Studio-AI-Long-form-<version>.zip
```
