# Installing the studio-reel skill

Turns a raw talking-head video into a finished your brand reel: even lighting, tightened
cuts and punch-ins, brand captions and animated callout cards. Runs in **Claude Code**
(terminal, desktop app or IDE) on your own machine, because it needs FFmpeg, Node and Chrome
to render video. It does not work in the claude.ai chat, which can't run these tools.

## 1. Install the tools (once per Mac)

Install Homebrew if you don't have it (it asks for your Mac password):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the "Next steps" it prints, then:

```bash
brew install node ffmpeg whisper-cpp
```

You also need Google Chrome and Python 3 with numpy (`python3 -m pip install numpy` if
`python3 -c "import numpy"` fails).

## 2. Install the skill

Unzip `studio-reel.zip` into your Claude skills folder so you end up with
`~/.claude/skills/studio-reel/SKILL.md`:

```bash
mkdir -p ~/.claude/skills && unzip studio-reel.zip -d ~/.claude/skills/
```

Start a new Claude Code session so it picks the skill up.

## 3. Use it

Open Claude Code in a folder containing your raw clip and ask, for example:

- "Make a reel from 05.mov"
- "Recreate this edit from 01.mov, matching `Reel 1.mp4`"
- "Add captions and cards to this clip"

Claude shows you the cut list and a storyboard of cards to approve before it renders.
The first run downloads the speech model (a few minutes).

## Notes

- **Fonts:** the skill includes your brand's licensed Display font. Keep the skill inside the team.
- **Brand:** fonts and colours are in `template/brand.css`.
- **Camera:** the lighting fix assumes a camera on a tripod.
