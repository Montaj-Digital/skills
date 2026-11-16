# Studio AI short-form editor

> **Part of Studio AI.** Open it with `../Open Studio AI.command` (http://127.0.0.1:4322); install with `../04. Installation`. Client brands and the brand per video are described in `../README.md`. Where this guide mentions `01. Installation`, `03. Tools`, `07. Packages`, port 4321 or `~/.claude/skills`, that is the Studio AI short-form editor: Studio AI uses `../04. Installation` and its own skill copies in `02. Skill`.

A local editor for default-brand videos in four formats: **Reel 9:16**, **Feed 4:5**, **Square 1:1**
and **Landscape 16:9**.
**New** turns a raw talking-head video into a drafted video by running the studio-reel skill's steps. **Open** lists every video on this Mac.
The timeline shows cards, chips, text, captions, effects, sounds, zooms and the end screen over
the video, transcript and waveform, with a live preview of the real composition.

**First time? See [INSTALL.md](INSTALL.md).** In short: right-click
`01. Installation/Install Studio AI short-form editor.command` → Open.

## Start it

Double-click **Studio AI short-form editor** on your Desktop, or **`Open Studio AI short-form editor.command`** in this folder.
The editor opens at http://127.0.0.1:4321. Keep the Terminal window open while you work.

From Terminal instead: `python3 server.py` in this folder, or `python3 server.py "<video folder>"`
to jump straight into one video.

## Opening the editor

It starts with a short **splash screen**: *Think it. Upload it. Create it.* Then **Let's create** starts a new
video, **Open a past video** goes to your library, and **Continue editing** goes back to the open video.
The splash shows once per browser session.

## New (a three-step wizard)

1. **Choose a look:** **Clean** (glass cards and captions) or **Takeover** (adds gradient cutaways for the key
   points). Each has a small animated preview.
2. **Upload and details:** pick the **format** (Reel 9:16, Feed 4:5, Square 1:1 or Landscape 16:9), drop in the raw
   video (the drop zone takes the format's shape and plays your clip), give it a name and, optionally,
   notes for Claude (what the cards should say, takes to drop, a different call to action). **Create video**.
3. **Create:** the video is copied to `05. Projects/<name>/raw/`, and the steps below run while your clip plays
   alongside. When they finish, the timeline opens.

**New** in the header and the **New video** tile on the home screen both start the wizard.

| Step | What runs |
|---|---|
| Set up the project | `hyperframes init edit` |
| Transcribe the raw video | whisper `medium.en` → `work/transcript.json` |
| Even out the lighting | `grade.py` |
| Find retakes and false starts | Claude reads the transcript → `work/retakes.json` |
| Plan cuts and zooms | `plan_cuts.py` (pause trimming, retakes removed, punch-ins for the format) |
| Render the base edit | `edit.py` → `edit/base-edit.mp4` |
| Transcribe the edit | whisper → `edit/transcript.json` |
| Plan captions and cards | Claude writes `reel.json` from the skill's rules, spec and the example for the chosen look. A plan that doesn't build is sent back once with the error |
| Build the video | `build.py` → `index.html` |

If a step fails, the wizard shows why and offers **Retry from that step**; reloading the page picks the job
back up at step 3. Without Claude Code, the two Claude steps are skipped and everything else still runs.

### Templates

Pick a **template** under New, as well as the format:
- **Clean:** glass cards and captions over the footage.
- **Takeover:** adds **gradient cutaways** for the key points: a list being named, a tool reveal, a big
  number, a "thing one", a closing recap. In a Reel they alternate full-screen and picture-in-picture
  (the speaker in a window above the text); other formats use full-screen. Claude also adds a few
  punch-in effects.

Takeovers sit on their own **Takeovers** track. Click one to edit its mode, kicker, title, items (each
lands on its word) or big number. **+ Takeover** adds a list, a picture-in-picture list, a big number or a
recap at the playhead, in any video, whichever template it started with.

### Feed 4:5 and Square 1:1

The Reel format's style on a shorter frame: captions at chest height, cards centred below them and scaled to
fit, chips at the top, and a shorter end screen. Each card's **Vertical centre** moves it up or down.
Square uses gentler zooms (1.2× / 1.12×), and Claude keeps cards compact and less frequent. A
portrait camera file works well for both: it's cropped from the centre.

### Landscape 16:9

Built from the same brand cards, laid out for a wide frame:
- Cards sit in a **side panel**, scaled to fit. With nothing selected, choose **right**, **left** or **centre**
  under Layout. Each card's **Vertical centre** moves it up or down.
- Chips run along the top of the panel. Captions are a lower third.
- Zooms are gentler (1.15× / 1.1×), and Claude plans fewer cards (one idea every 6–12 s).
- Landscape footage works best. A portrait video is cropped to 16:9, and the first step tells you so.

## Open

Every video in the library, recently opened, or found by Spotlight, with a thumbnail, length,
card count, last edited and a Rendered badge. Filter by format with the chips at the top; videos
from elsewhere on your Mac are listed under **Elsewhere on this Mac**. Rendered videos have a **Show in Finder** button that
jumps to the finished MP4. Search by name, use **Browse…** to pick a folder, or **Finished videos** to open `06. Renders`.
Hover over a video and click 🗑 to **delete** it. The whole video folder goes to the Trash, so it
can be put back.

## Editing

| Do this | How |
|---|---|
| Move a card, effect or sound | Drag the block. It snaps to words; hold **Alt** to drag freely |
| Change when it starts or ends | Drag its left or right edge |
| Retime one part of a card | Drag its ◆ marker, or edit Timing in the panel |
| Edit card text, icons, logos | Select the block; the panel lists every field |
| Add text, a chip, a card, a takeover, an effect | **+ Text**, **+ Chip**, **+ Card**, **+ Takeover**, **+ Effect** add at the playhead; Card, Takeover and Effect open a list to pick from |
| Fix a caption | Click it, then a word: change its text, make it a keyword, hide it, split the caption |
| Add a takeover | **+ Takeover** → List, Picture-in-picture list, Big number, Recap or **Big text**. Claude writes it from what's said at the playhead (the text, and each part landing on its word) while a placeholder pulses; ⌘Z goes back to the placeholder. **Fill from what's said** in the panel refills one. Needs Claude Code signed in; without it, the title comes from the sentence at the playhead |
| Lay another video over this one | **+ Video** picks a clip (an insert, B-roll or a testimonial); it's copied into the video's `assets/overlays/`. It sits on the **Overlays** track (V2, V3 …; drag a block up or down to change track, drag its ends to trim). **Full screen** or **Picture-in-picture** (drag the window on the preview, drag a corner to resize). **Muted** by default: unmute it to hear its sound, and the **Speaker** slider lowers the main video while it plays (15% when you unmute). Opacity, fade, start, length, and where in the clip it starts |
| Move a card | Select it, then drag it on the preview (Shift keeps the move level; it snaps to the middle). **Centre it again** in the panel puts it back |
| Blur part of the picture | **+ Blur** adds a box at the playhead: drag it over a face, name or screen, drag its corners to resize. **Blur** or **Black box**, strength, start and length in the panel. **Follow movement**: move the playhead, drag the box again, and it glides between the points. Blurs have their own **Blur** track |
| Cut the video | The **Video** track shows each clip. **Split** (or **S**) cuts at the playhead; select a clip and press ⌫ to delete it; drag a clip's edges (or use the −0.5s … +0.5s buttons in the panel) to trim. To remove a part: **I** at its start, **O** at its end, then ⌫. Dragging an edge outwards brings back material the automatic edit cut out |
| Apply a cut | Removed parts show in red and the preview skips them straight away. **Apply cut** re-renders the base edit from the camera file (a minute or two); captions, cards, effects and sounds move with their words, and anything that sat only inside a removed part is deleted. The previous version is kept in `edit/.editor/backups/cuts-<date>/` |
| Change a zoom | Click a block on the **Zoom** track, set the scale, then **Apply** (re-renders the base edit, about 1–2 min) |
| End screen | Click it at the end of the Cards track: regular and bold lines, reorder, reset to standard |
| Undo / redo / save | ⌘Z / ⇧⌘Z / ⌘S. Saving keeps the previous `reel.json` in `edit/.editor/backups/` |
| Render | **Render** saves, then renders the delivery MP4 into `06. Renders/<format>/<name>.mp4` (Reel 9x16, Feed 4x5, Square 1x1, Landscape 16x9). An earlier render with the same name moves to `Previous versions`. **Show in Finder** when it's done |

**Resize the panels:** drag the top edge of the timeline, or the left edge of the side panel. Each browser remembers the
sizes; double-click an edge to reset it.

**Light or dark:** the ☾ / ☀︎ button in the header switches the whole editor between the default light
theme (the default, as on example.com) and dark mode. Each browser remembers its choice.

Keys: Space play or pause, ←/→ one frame, ⇧←/→ one second, Home/End start or end, ⌫ delete the
selected block, clip or marked part, S split, I / O mark a part to remove, Esc deselect. Press **?** (or the keyboard button in the header) for the full list.

**Tracks:** Takeovers, Text, Chips, Cards, Captions; **Effects** (punch in, slow push, flash) and
**Sounds** (pop, tick); **Zoom** (the punch-ins baked into the base edit); **Video** (a filmstrip with
cut markers); **Audio** with the words over the waveform (click a word to jump to it). Each track
header shows how many items it has, and empty tracks shrink to a slim row until you use them.

## Settings

Optional `settings.json` in `04. Editor`:

```json
{ "library": "/Users/you/Shared/Studio", "claude_cmd": "/path/to/claude", "claude_model": "opus" }
```

`library` is where `05. Projects` and `06. Renders` live (default: this folder, so everything stays in one place). `claude_cmd` is only needed if
`claude` isn't found automatically. `claude_model` is passed to `claude --model`.

## What's in this folder

Everything lives here, including your videos and finished renders:

```
Studio AI short-form editor/
├── 01. Installation/       Install Studio AI short-form editor.command, Check setup.command, INSTALL.md
├── 02. Skill/              studio-reel: the brand template, card types and build scripts
├── 03. Tools/              install.sh, doctor.py (the setup check), make-package.sh
├── 04. Editor/             the editor: server.py, pipeline.py, app/, VERSION
├── 05. Projects/           one folder per video: raw/ (camera file), work/ (cuts, lighting), edit/
├── 06. Renders/            finished videos, filed by format
│   ├── Reel 9x16/
│   ├── Feed 4x5/
│   ├── Square 1x1/
│   └── Landscape 16x9/
│       └── Previous versions/   an earlier render with the same name moves here
├── 07. Packages/           the zip to share with the team
├── Open Studio AI short-form editor.command
├── README.md
└── CLAUDE.md               project handover: how it's built, decisions, status (Claude Code reads it automatically)
```

**How it works:** each edit is built into `05. Projects/<video>/edit/.editor/preview/` with the skill's own
`build.py`, so the preview is the real composition, and `reel.json` only changes when you
press Save. Claude runs through Claude Code in headless mode (`claude -p`) with your own login.

## Making a new package

```bash
"03. Tools/make-package.sh"
```

This copies the current `~/.claude/skills/studio-reel` into `02. Skill` and writes
`07. Packages/Studio-AI-Short-form-<VERSION>.zip`, without your videos. Bump `04. Editor/VERSION` first.

## Not yet

Matching a reference video from New, and the full-screen
"takeover" cards.
