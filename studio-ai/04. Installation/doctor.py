#!/usr/bin/env python3
"""Check that everything Studio AI needs is installed.

    python3 "04. Installation/doctor.py"            # quick check
    python3 "04. Installation/doctor.py" --claude   # also checks Claude Code is signed in (one tiny request)

Exit code 0 when everything required is in place.
"""
import json, os, platform, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent      # the Studio AI folder
HOME = Path.home()
PATH = os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin", str(HOME / ".local/bin"), os.environ.get("PATH", "")])
ENV = dict(os.environ, PATH=PATH)
G, R, Y, D, B, X = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
results = []


def which(name):
    return shutil.which(name, path=PATH)


def run(cmd, timeout=60, stdin=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=timeout, input=stdin)
        return (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"error: {e}"


def check(name, ok, detail="", fix="", required=True):
    results.append((name, ok, detail, fix, required))


# macOS
mac = platform.mac_ver()[0]
check("macOS", bool(mac) and int(mac.split(".")[0]) >= 13, f"{mac} on {platform.machine()}", "macOS 13 (Ventura) or newer is needed")

# Homebrew + tools
brew = which("brew")
check("Homebrew", bool(brew), brew or "", "Run the installer, or see 04. Installation/INSTALL.md")
ff = which("ffmpeg")
check("FFmpeg", bool(ff), (run([ff, "-version"]).splitlines() or [""])[0][:60] if ff else "", "brew install ffmpeg")
check("ffprobe", bool(which("ffprobe")), "", "brew install ffmpeg")
check("whisper-cpp (speech to text)", bool(which("whisper-cli")), which("whisper-cli") or "", "brew install whisper-cpp")
node = which("node")
nv = run([node, "--version"]) if node else ""
m = re.match(r"v(\d+)", nv)
check("Node.js 22+", bool(m) and int(m.group(1)) >= 22, nv, "brew install node")
check("npx", bool(which("npx")), "", "brew install node")

# Python + numpy (the lighting step)
py = which("python3")
npv = run([py, "-c", "import numpy; print(numpy.__version__)"]) if py else ""
check("Python 3", bool(py), run([py, "--version"]) if py else "", "xcode-select --install")
check("numpy", bool(re.match(r"\d+\.", npv)), npv if re.match(r"\d+\.", npv) else "", "python3 -m pip install --user numpy")

# Chrome (HyperFrames renders with it)
chrome = next((p for p in ["/Applications/Google Chrome.app", str(HOME / "Applications/Google Chrome.app")] if Path(p).exists()), None)
check("Google Chrome (for the editor)", bool(chrome), chrome or "", "Recommended: brew install --cask google-chrome", required=False)

# HyperFrames + the speech model
hf_cache = HOME / ".cache/hyperframes"
models = [p.name for p in hf_cache.rglob("ggml-medium.en*.bin")] if hf_cache.exists() else []
render_chrome = list((hf_cache / "chrome").glob("*/*")) if (hf_cache / "chrome").exists() else []
check("Render browser (HyperFrames)", bool(render_chrome), "cached" if render_chrome else "", "npx -y hyperframes@latest browser ensure")
check("Speech model (medium.en)", bool(models), models[0] if models else "",
      "Downloads on first use (about 1.5 GB), or re-run the installer", required=False)

# the skills: Studio AI uses its own bundled copies (never ~/.claude/skills)
skill = HERE / "01. Short-form/02. Skill/studio-reel"
ok_skill = (skill / "SKILL.md").exists() and (skill / "scripts/build.py").exists() and (skill / "scripts/brand.py").exists()
check("studio-reel skill (bundled)", ok_skill, "01. Short-form/02. Skill" if ok_skill else "", "The package is incomplete: unzip it again")
long_skill = HERE / "02. Long-form/02. Skill/studio-longform"
check("studio-longform skill (bundled)", (long_skill / "SKILL.md").exists(), "02. Long-form/02. Skill" if (long_skill / "SKILL.md").exists() else "",
      "The package is incomplete: unzip it again")
kit = HERE / "03. Brands/default/brand.json"
check("Brand kits", kit.exists(), f"{len(list((HERE / '03. Brands').glob('*/brand.json')))} kits" if kit.exists() else "",
      "The package is incomplete: 03. Brands/default is missing")
if sys.platform == "darwin":
    swift = which("swiftc")
    check("Swift (reads PDF brand guides)", bool(swift), swift or "", "xcode-select --install", required=False)
else:   # Windows / Linux: the Python versions of the PDF tools (03. Brands/pdftools.py)
    sys.path.insert(0, str(HERE / "03. Brands"))
    try:
        import pdftools
        gone = pdftools.missing()
    except ImportError:
        gone = ["03. Brands/pdftools.py"]
    check("PDF tools (read PDF brand guides)", not gone, "numpy, pypdfium2, Pillow" if not gone else "",
          "pip install numpy pypdfium2 pillow", required=False)
fonts = list((skill / "template/assets/fonts").glob("Display-*")) if ok_skill else []
check("Display brand font", bool(fonts), f"{len(fonts)} files" if fonts else "", "Comes with the skill; check the skill folder is complete")

# Claude Code
claude = next((c for c in [which("claude"), str(HOME / ".local/bin/claude")] if c and Path(c).exists()), None)
check("Claude Code", bool(claude), run([claude, "--version"])[:40] if claude else "",
      "curl -fsSL https://claude.ai/install.sh | bash", required=False)
if claude and "--claude" in sys.argv:
    out = run([claude, "-p", "Reply with the word OK only.", "--output-format", "text"], timeout=120, stdin="")
    signed = "ok" in out.lower() and "login" not in out.lower()
    check("Claude Code signed in", signed, "" if signed else out[:80], "Open Terminal, run: claude  then type /login", required=False)

# print
print(f"\n{B}Studio AI: setup check{X}\n")
for name, ok, detail, fix, req in results:
    mark = f"{G}✓{X}" if ok else (f"{R}✗{X}" if req else f"{Y}!{X}")
    print(f"  {mark} {name:30} {D}{detail}{X}")
    if not ok:
        print(f"      {Y}→ {fix}{X}")
missing = [n for n, ok, _, _, req in results if req and not ok]
optional = [n for n, ok, _, _, req in results if not req and not ok]
print()
if missing:
    print(f"{R}{B}Missing: {', '.join(missing)}{X}")
elif optional:
    print(f"{G}{B}Ready to edit videos.{X} {Y}Optional: {', '.join(optional)}{X}")
else:
    print(f"{G}{B}Everything is installed.{X}")
sys.exit(1 if missing else 0)
