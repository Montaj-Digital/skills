# Getting started with Studio AI

Studio AI turns raw talking-head recordings into finished, branded videos. It runs on your own Mac and opens in your browser.

- **Short-form:** Reels, TikTok, Shorts, plus feed, square and landscape versions, with captions, animated cards and an end screen.
- **Long-form:** 60+ minute YouTube and webinar videos, with chapters, lower thirds, overlays and cutting.
- **AI studio:** Claude builds clips (a trailer, a cold open, a testimonial cut) from several videos.

It comes with two Claude Code skills that do the planning and building. They're bundled inside the app, and the app uses its own copies:

- `01. Short-form/02. Skill/studio-reel/`
- `02. Long-form/02. Skill/studio-longform/`

## What you need

- A Mac on macOS 13 or newer (Apple silicon recommended)
- About 5 GB of free disk space, plus room for your videos
- A Claude account (Pro, Max, Team or Enterprise) with Claude Code installed

## Install

1. Put the `Studio AI` folder where you want to keep it, such as Documents.
2. Open `04. Installation`, right-click `Install Studio AI.command` and choose **Open**.
3. Follow the Terminal window. It installs FFmpeg, Node, whisper-cpp and the speech model, then adds a `Studio AI` shortcut to your Desktop.

The full guide is `04. Installation/INSTALL.md`. To check your setup at any point, run `04. Installation/Check setup.command`.

## Add your brand

The app ships with a neutral default look (Inter, blue and cyan, a placeholder logo). To use your own:

1. Open Studio AI and go to **Brands**, then **Add a client**.
2. Upload your brand guide (PDF) or enter your website. Claude reads your colours, fonts and tone of voice.
3. Check the kit, add your logo, and save it.

You can also edit the default kit directly in `03. Brands/default/brand.json`, which is documented in `03. Brands/README.md`.

## Make it your own

It's plain Python, JavaScript and HTML with no build step. Open the folder in Claude Code and ask for the changes you want. `CLAUDE.md` in each folder explains how the parts fit together.

## Fonts and licences

The bundled fonts are Inter, under the SIL Open Font License (`OFL-Inter.txt`). They're free to use. Fonts you add for your own brand are yours to licence.

## Social posting

The calendar can post to YouTube, Facebook, Instagram, TikTok and LinkedIn once you've added your own app keys for each platform under **Social settings**. Until then, it works as a planner with email reminders.
