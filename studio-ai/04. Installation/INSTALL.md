# Installing Studio AI

Studio AI turns raw talking-head videos into finished, branded videos: short-form (Reels, Feed, Square, Landscape) and
long-form (60+ minute YouTube and webinar videos), in **your brand's look or a client's own brand**, and its AI
studio builds clips from several videos with Claude. It runs on your own Mac and opens in your browser.

This guide is for installing it on a Mac.

The bundled fonts are Inter (SIL Open Font License, free to use). Fonts you add for your own brand are your responsibility to licence.

---

## What you need

| | |
|---|---|
| Mac | macOS 13 (Ventura) or newer. Apple silicon (M1 and later) recommended; Intel works, but transcribing and rendering are slower |
| Disk space | About 5 GB for the tools, plus room for your videos (a 2-minute 4K clip is about 600 MB) |
| Internet | For the first install (about 3 GB of downloads), Claude, and Google Fonts for client brands |
| Accounts | A Claude account (Pro, Max, Team or Enterprise) for planning, takeover fills and reading brand guides. Everything else is free |
| Your Mac password | The installer asks for it once, to install Homebrew |

---

## Install (one click)

1. **Unzip** `Studio-AI-<version>.zip`.
2. **Move the `Studio AI` folder** where you want to keep it, e.g. your Documents folder. Do this
   *before* installing, because the Desktop shortcut points to it.
3. **Open `04. Installation`, right-click `Install Studio AI.command` → Open**, then click **Open**
   again in the warning. macOS asks this once because the file came from the internet; after that, a normal
   double-click works for everything in the folder.
4. **Follow the Terminal window.** Press Enter to start, and type your Mac password when asked (it won't show as you
   type). The first install takes 10–20 minutes.
5. **Sign in to Claude when asked.** Claude Code opens: type `/login`, finish signing in in your browser, then type
   `/exit` to return to the installer.
6. At the end, the installer checks everything and offers to open Studio AI.

The installer can be run again at any time. Anything already installed is skipped.

### What the installer does

| Step | What gets installed | Why |
|---|---|---|
| 1 | [Homebrew](https://brew.sh), plus Apple's command line tools | Installs the other tools; Swift (reads PDF brand guides) comes with the command line tools |
| 2 | FFmpeg, Node.js, whisper-cpp | Video cutting and grading; HyperFrames; speech to text |
| 3 | numpy, for the Mac's Python 3 | The lighting fix |
| 4 | Google Chrome, if missing | The recommended browser |
| 5 | HyperFrames, its render browser, and the `medium.en` speech model (about 1.5 GB) | Building and rendering videos; transcripts |
| 6 | Nothing: checks the bundled skills, the default brand kit and Swift | Studio AI uses its own skill copies and never changes `~/.claude/skills` |
| 7 | [Claude Code](https://claude.com/claude-code), plus a one-time sign-in | Plans videos, fills takeovers, reads brand guides |
| 8 | The project and render folders, a Desktop shortcut, and a final check | Where your videos are kept |

---

## Open Studio AI

Double-click **Studio AI** on your Desktop, or **`Open Studio AI.command`** in the main
folder. A Terminal window starts it and your browser opens at **http://127.0.0.1:4322**. The header says **Studio AI**.

- Keep that Terminal window open while you work. Close it, or press Ctrl+C, to stop Studio AI.
- If it's already running, the shortcut just opens the browser tab again.
- It only runs on your Mac; nobody else can reach it.

The `README.md` in the main folder explains how to use it. More detail is in
**README.md** in the main folder and in each editor's folder.

---

## Check your setup

Double-click **`04. Installation/Check setup.command`** to see a ✓ or ✗ for every tool, with the fix for anything
missing. It also confirms that Claude Code is signed in.

---

## Updating

1. Unzip the new version. Copy these over your existing folder:
   - its `01. Short-form` and `02. Long-form` folders, **except `05. Projects` and `06. Renders`**;
   - `03. Brands/default` and the files in `03. Brands` (not the folders of your client kits);
   - `05. Music/README.md`, `04. Installation`, `VERSION`, `README.md`
     and `Open Studio AI.command`.

   **Your videos, renders, client brand kits, music and `08. Planner` (scheduled posts, social settings, results) stay
   as they are.** Don't copy over `08. Planner`. Connections and app keys are in the Mac's Keychain and stay too.
2. Run **`04. Installation/Install Studio AI.command`** once.

## Where things are

```
Studio AI/
├── 01. Short-form/         Reels, Feed, Square, Landscape
│   ├── 02. Skill/          studio-reel: the template, card types, build scripts, brand.py
│   ├── 04. Editor/         the app: server.py (it also serves long-form and brands), pipeline.py, app/, VERSION
│   ├── 05. Projects/       one folder per video
│   └── 06. Renders/        finished videos: <format>/ for the default brand, <Client>/<format>/ for a client
├── 02. Long-form/          60+ minute videos (camera files are linked, not copied)
│   ├── 02. Skill/  04. Editor/  05. Projects/  06. Renders/   (same layout)
├── 03. Brands/             brand kits: default/ plus one folder per client
├── 05. Music/              music beds for AI studio clips (you add these)
├── 04. Installation/       Install …command, Check setup.command, install.sh, doctor.py, this guide
├── 08. Planner/            the social planner: settings, scheduled posts, covers, results (made when first used)
├── Open Studio AI.command
├── README.md
└── VERSION
```

| What | Where |
|---|---|
| Finished videos | `01. Short-form/06. Renders/…` and `02. Long-form/06. Renders/…`; client videos in a folder named after the client |
| Client brand kits | `03. Brands/<client>/` (they stay on this Mac; they aren't in the package) |
| Editor settings (optional) | `01. Short-form/04. Editor/settings.json` |
| Scheduled posts, social settings, results | `08. Planner/` (sign-ins and app keys: the Keychain, "Studio AI") |
| Downloaded models and render browser | `~/.cache/hyperframes` |

## Troubleshooting

**"…can't be opened because it is from an unidentified developer"**
Right-click the file → **Open** → **Open**. You only need to do this once; the installer clears the warning for the
rest of the folder.

**"Address already in use" when starting**
Studio AI is already running in another Terminal window. Open http://127.0.0.1:4322, or stop the other one with
Ctrl+C.

**New videos skip "Find retakes" and "Plan captions and cards"**
Claude Code isn't installed or isn't signed in. Run `claude` in Terminal and type `/login`, or run **Check setup**.
The video still gets made; only those steps are skipped.

**Importing a PDF brand guide fails with "needs the Xcode command line tools"**
Run `xcode-select --install`, then try again. Images and website links work without it.

**A render fails**
Run `npx -y hyperframes@latest doctor` in Terminal and fix anything it lists. The render log is shown in the Render
window.

**Homebrew installed but `brew` isn't found**
Open a new Terminal window, or run `eval "$(/opt/homebrew/bin/brew shellenv)"`, then run the installer again.

---

## Uninstalling

Delete the `Studio AI` folder and the Desktop shortcut. Your videos and client kits are inside the
folder, so keep a copy of `05. Projects`, `06. Renders` and `03. Brands` first if you want them. The tools are shared
with other tools, so only remove them (`brew uninstall ffmpeg node whisper-cpp`, `~/.cache/hyperframes`) if
neither app is used any more.
