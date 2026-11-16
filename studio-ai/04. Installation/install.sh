#!/bin/bash
# Studio AI: one-click install of everything it needs, on macOS.
# Safe to run again: anything already installed is skipped. Run it from "04. Installation/Install Studio AI.command".
# Studio AI uses its own copies of the skills (01. Short-form/02. Skill, 02. Long-form/02. Skill), so it never changes
# ~/.claude/skills: the Studio AI short-form editor on the same Mac keeps working as it is.

APP="$(cd "$(dirname "$0")/.." && pwd)"     # the Studio AI folder
cd "$APP" || exit 1
P='\033[1;35m'; G='\033[32m'; Y='\033[33m'; R='\033[31m'; D='\033[2m'; X='\033[0m'
step() { printf "\n${P}==> %s${X}\n" "$1"; }
ok()   { printf "  ${G}✓${X} %s\n" "$1"; }
note() { printf "  ${Y}!${X} %s\n" "$1"; }
die()  { printf "\n${R}✗ %s${X}\n\nNothing else was changed. See INSTALL.md → Troubleshooting.\n" "$1"; exit 1; }

clear
printf "${P}Studio AI installer${X}\n"
printf "${D}Installs: Homebrew, FFmpeg, Node, whisper-cpp, Python numpy, HyperFrames (render browser + speech model),\n"
printf "and Claude Code. Takes 10–20 minutes the first time (about 3 GB of downloads).${X}\n"
printf "\nYou may be asked for your Mac password (it won't show as you type).\n"
read -r -p "Press Enter to start, or Ctrl+C to cancel. " _

[ "$(uname)" = "Darwin" ] || die "This installer is for macOS."
MAJOR=$(sw_vers -productVersion | cut -d. -f1)
[ "$MAJOR" -ge 13 ] || die "macOS 13 (Ventura) or newer is needed; this Mac has $(sw_vers -productVersion)."

# so the files from the download open without warnings next time
xattr -dr com.apple.quarantine "$APP" 2>/dev/null

# ------------------------------------------------------------ 1. Homebrew
step "1/8  Homebrew (the Mac package manager)"
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
if command -v brew >/dev/null; then
  ok "Homebrew is installed"
else
  echo "  Installing Homebrew (it also installs Apple's command line tools)…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || die "Homebrew didn't install."
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
  command -v brew >/dev/null || die "Homebrew installed but isn't on the PATH."
  LINE="eval \"\$($(command -v brew) shellenv)\""
  grep -qsF "$LINE" ~/.zprofile || echo "$LINE" >> ~/.zprofile
  ok "Homebrew installed"
fi

# ------------------------------------------------------------ 2. command line tools
step "2/8  FFmpeg, Node and whisper-cpp"
for f in ffmpeg node whisper-cpp; do
  if brew list --formula "$f" >/dev/null 2>&1; then ok "$f is installed"
  else echo "  Installing $f…"; brew install "$f" || die "Couldn't install $f."; ok "$f installed"; fi
done

# ------------------------------------------------------------ 3. Python + numpy
step "3/8  Python 3 and numpy (used by the lighting step)"
command -v python3 >/dev/null || die "python3 is missing. Run: xcode-select --install, then run this installer again."
if python3 -c "import numpy" 2>/dev/null; then ok "numpy is installed"
else
  python3 -m pip install --user --quiet numpy || python3 -m pip install --user --quiet --break-system-packages numpy || die "Couldn't install numpy."
  ok "numpy installed"
fi

# ------------------------------------------------------------ 4. Chrome
step "4/8  Google Chrome (recommended browser for the editor)"
if [ -d "/Applications/Google Chrome.app" ] || [ -d "$HOME/Applications/Google Chrome.app" ]; then ok "Chrome is installed"
else brew install --cask google-chrome && ok "Chrome installed" || note "Chrome didn't install; the editor still works in Safari or another browser."; fi

# ------------------------------------------------------------ 5. HyperFrames
step "5/8  HyperFrames (renders the videos) and the speech model"
npx -y hyperframes@latest --version >/dev/null 2>&1 && ok "HyperFrames is ready" || die "HyperFrames couldn't be downloaded (check the internet connection)."
npx -y hyperframes@latest browser ensure >/dev/null 2>&1 && ok "Render browser is ready" || note "Render browser will download on the first render."
if ls "$HOME"/.cache/hyperframes/whisper/models/ggml-medium.en*.bin >/dev/null 2>&1; then ok "Speech model is ready"
else
  echo "  Downloading the speech model (about 1.5 GB)…"
  T=$(mktemp -d)
  ffmpeg -v error -f lavfi -i "sine=frequency=440:duration=2" "$T/tone.wav" \
    && npx -y hyperframes@latest transcribe "$T/tone.wav" -d "$T" -m medium.en -l en --engine whisper >/dev/null 2>&1
  rm -rf "$T"
  ls "$HOME"/.cache/hyperframes/whisper/models/ggml-medium.en*.bin >/dev/null 2>&1 && ok "Speech model downloaded" \
    || note "The speech model will download on the first new video instead."
fi

# ------------------------------------------------------------ 6. the bundled skills and the PDF tools
step "6/8  The skills and the brand-guide reader"
[ -f "$APP/01. Short-form/02. Skill/studio-reel/SKILL.md" ] || die "The studio-reel skill is missing from this package (01. Short-form/02. Skill)."
[ -f "$APP/02. Long-form/02. Skill/studio-longform/SKILL.md" ] || die "The studio-longform skill is missing from this package (02. Long-form/02. Skill)."
ok "Skills are bundled (Studio AI never changes ~/.claude/skills)"
[ -f "$APP/03. Brands/default/brand.json" ] || die "The default brand kit is missing (03. Brands/default)."
ok "default brand kit is in place"
if command -v swiftc >/dev/null; then ok "Swift is ready (reads PDF brand guides and cuts out logos)"
else note "Swift is missing: run xcode-select --install to import PDF brand guides. Everything else works without it."; fi

# ------------------------------------------------------------ 7. Claude Code
step "7/8  Claude Code (plans the cards and removes retakes)"
export PATH="$HOME/.local/bin:$PATH"
if command -v claude >/dev/null; then ok "Claude Code is installed ($(claude --version 2>/dev/null | head -1))"
else
  curl -fsSL https://claude.ai/install.sh | bash && export PATH="$HOME/.local/bin:$PATH"
  command -v claude >/dev/null && ok "Claude Code installed" || note "Claude Code didn't install. New videos will still work, without Claude's card plan."
fi
if command -v claude >/dev/null; then
  OUT=$(claude -p "Reply with the word OK only." --output-format text </dev/null 2>&1)
  if echo "$OUT" | grep -qi "login\|not logged"; then
    printf "\n  ${Y}Claude Code needs you to sign in once.${X}\n"
    printf "  Claude Code will open now: type ${P}/login${X}, finish signing in in your browser,\n"
    printf "  then type ${P}/exit${X} to come back here.\n\n"
    read -r -p "  Press Enter to open Claude Code… " _
    claude
    OUT=$(claude -p "Reply with the word OK only." --output-format text </dev/null 2>&1)
    echo "$OUT" | grep -qi "login\|not logged" && note "Still not signed in. Run 'claude' in Terminal and type /login later." || ok "Signed in to Claude Code"
  else
    ok "Signed in to Claude Code"
  fi
fi

# ------------------------------------------------------------ 8. shortcut + check
step "8/8  Finishing up"
chmod +x "$APP"/*.command "$APP"/*/*.command "$APP/04. Installation"/*.sh 2>/dev/null
mkdir -p "$APP/01. Short-form/05. Projects" "$APP/01. Short-form/06. Renders" "$APP/02. Long-form/05. Projects" "$APP/02. Long-form/06. Renders" \
  && ok "Videos are kept in 01. Short-form and 02. Long-form: 05. Projects (working files) and 06. Renders (finished videos; clients get their own folder)"
read -r -p "  Add a 'Studio AI' shortcut to your Desktop? [Y/n] " A
if [ "${A:-y}" != "n" ] && [ "${A:-y}" != "N" ]; then
  ln -sf "$APP/Open Studio AI.command" "$HOME/Desktop/Studio AI.command" && ok "Desktop shortcut added"
fi
python3 "$APP/04. Installation/doctor.py"
CODE=$?
echo
if [ $CODE -eq 0 ]; then
  read -r -p "All set. Open the editor now? [Y/n] " A
  [ "${A:-y}" = "n" ] || [ "${A:-y}" = "N" ] || exec "$APP/Open Studio AI.command"
else
  echo "Something is still missing (see above). Fix it, then run the installer again."
fi
