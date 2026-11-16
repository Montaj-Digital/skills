"""What macOS and Windows do differently (ROADMAP phase 8: Studio AI on Windows). Everything else in Studio AI is the same.

On a Mac every function here does exactly what the editor did before (osascript dialogs, Finder, symlinks, Homebrew's
PATH). On Windows:
  - text is UTF-8 everywhere: the server restarts itself in Python's UTF-8 mode, and every tool gets PYTHONUTF8=1;
  - tools come from PATH plus Studio AI's own Tools folder (the installer puts FFmpeg and whisper there); npx is npx.cmd;
  - file and folder pickers are Windows dialogs (PowerShell + Windows Forms), on top of the browser;
  - "Show in Finder" opens Explorer with the file selected;
  - links are symlinks when Windows allows them, else hard links (files) or junctions (folders);
  - replacing a file another reader still has open is retried for a few seconds;
  - stopping a job stops its whole process tree (npx.cmd starts node, which starts Chrome).
Python 3.9 standard library only.
"""
import os, shutil, subprocess, sys, time
from pathlib import Path

WINDOWS = os.name == "nt"
MAC = sys.platform == "darwin"
STUDIO = Path(__file__).resolve().parent.parent.parent      # 03. Studio AI
TOOLS = STUDIO / "Tools"                                      # Windows: FFmpeg, whisper … put here by the installer


# ---------------------------------------------------------------- text and tools
def ensure_utf8():
    """Windows reads and writes text in its own code page unless Python runs in UTF-8 mode: restart in it once."""
    if WINDOWS and not sys.flags.utf8_mode and os.environ.get("PYTHONUTF8") != "1":
        env = dict(os.environ, PYTHONUTF8="1")
        sys.exit(subprocess.call([sys.executable, "-X", "utf8"] + sys.argv, env=env))


def tool_dirs():
    if WINDOWS:
        home = Path.home()
        dirs = [TOOLS] + sorted(TOOLS.glob("*/bin")) + sorted(p for p in TOOLS.glob("*") if p.is_dir())
        dirs += [home / ".local/bin", Path(os.environ.get("APPDATA", home)) / "npm"]
        return [str(d) for d in dirs]
    return ["/opt/homebrew/bin", "/usr/local/bin", f"{Path.home()}/.local/bin"]


def tool_env(base=None):
    """The environment tools run in: the usual one plus the places the installer puts tools (and UTF-8 on Windows)."""
    base = dict(os.environ if base is None else base)
    if WINDOWS:
        base["PATH"] = os.pathsep.join(tool_dirs() + [base.get("PATH", "")])
        base["PYTHONUTF8"] = "1"
    else:
        base["PATH"] = ":".join(tool_dirs()) + ":" + base.get("PATH", "")
    return base


if WINDOWS:   # the server itself finds programs on its own PATH (Windows doesn't look at the env= given to a tool)
    os.environ.update(tool_env())

NPX = "npx.cmd" if WINDOWS else "npx"


def claude_candidates():
    home = Path.home()
    if WINDOWS:
        return [str(home / ".local/bin/claude.exe"), str(home / ".claude/local/claude.exe"),
                str(Path(os.environ.get("APPDATA", home)) / "npm/claude.cmd")]
    return [str(home / ".local/bin/claude"), str(home / ".claude/local/claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]


def kill_tree(p):
    """Stop a running tool and everything it started."""
    if p is None or p.poll() is not None:
        return
    if WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        p.kill()


def stop_tree(p):
    """Ask a tool to stop (terminate on a Mac, as before; the whole tree on Windows)."""
    if p is None or p.poll() is not None:
        return
    if WINDOWS:
        kill_tree(p)
    else:
        p.terminate()


# ---------------------------------------------------------------- pickers (on the user's own computer only)
def _ps(script):
    """Run a PowerShell snippet in a single-threaded apartment (Windows Forms dialogs need one); its output as UTF-8."""
    pre = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Add-Type -AssemblyName System.Windows.Forms; " \
          "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false}; "
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", pre + script], capture_output=True, text=True, encoding="utf-8")
    return [x.strip() for x in r.stdout.splitlines() if x.strip()]


WIN_FILTERS = {
    "video": "Videos|*.mp4;*.mov;*.m4v;*.mkv;*.webm|All files|*.*",
    "subtitles": "Subtitles|*.srt;*.vtt|All files|*.*",
    "any": "All files|*.*",
}
MAC_TYPES = {"video": ["public.movie"], "subtitles": ["srt", "vtt"], "any": []}


def pick_files(prompt, kind="video", multiple=False):
    """Choose files in Finder / a Windows file dialog. → list of paths ([] when cancelled)."""
    if WINDOWS:
        title = prompt.replace("'", "''")
        return _ps(f"$d = New-Object System.Windows.Forms.OpenFileDialog; $d.Title = '{title}'; "
                   f"$d.Filter = '{WIN_FILTERS[kind]}'; $d.Multiselect = ${str(multiple).lower()}; "
                   "if ($d.ShowDialog($owner) -eq 'OK') { $d.FileNames }")
    types = MAC_TYPES[kind]
    of_type = (" of type {" + ", ".join(f'"{t}"' for t in types) + "}") if types else ""
    if multiple:
        script = (f'set fs to choose file{of_type} with prompt "{prompt}" with multiple selections allowed\n'
                  'set out to ""\nrepeat with f in fs\nset out to out & POSIX path of f & linefeed\nend repeat\nreturn out')
    else:
        script = f'POSIX path of (choose file with prompt "{prompt}"{of_type})'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return [x for x in r.stdout.splitlines() if x.strip()]


def pick_folder(prompt):
    if WINDOWS:
        title = prompt.replace("'", "''")
        out = _ps(f"$d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = '{title}'; "
                  "if ($d.ShowDialog($owner) -eq 'OK') { $d.SelectedPath }")
        return out[0] if out else None
    r = subprocess.run(["osascript", "-e", f'POSIX path of (choose folder with prompt "{prompt}")'], capture_output=True, text=True)
    return r.stdout.strip() or None


def reveal(target):
    """Show a file (selected) or open a folder in Finder / Explorer."""
    target = Path(target)
    if WINDOWS:
        subprocess.run(["explorer", f"/select,{target}"] if target.is_file() else ["explorer", str(target)])
    elif MAC:
        subprocess.run(["open", "-R", str(target)] if target.is_file() else ["open", str(target)])
    else:
        subprocess.run(["xdg-open", str(target if target.is_dir() else target.parent)])


def can_search():
    """Spotlight (mdfind) exists only on a Mac."""
    return MAC and shutil.which("mdfind") is not None


def bin_folder():
    """Where deleted projects and kits go on this computer: the Mac's Bin, or a Bin folder in Studio AI on Windows."""
    return Path.home() / ".Trash" if MAC else STUDIO / "Bin"


# ---------------------------------------------------------------- links and swaps
def is_link(p):
    """A symlink, or (Windows) a junction."""
    p = Path(p)
    if p.is_symlink():
        return True
    if WINDOWS:
        try:
            import stat
            return bool(os.lstat(p).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except (OSError, AttributeError):
            return False
    return False


def remove(p):
    """Remove a link (never what it points to), a file or a folder."""
    p = Path(p)
    if is_link(p):
        os.rmdir(p) if (WINDOWS and p.is_dir()) else p.unlink()
    elif p.is_file():
        p.unlink()
    elif p.exists():
        shutil.rmtree(p)


def link(target, dst, copy_ok=False):
    """dst points at target. Windows without symlink rights: a hard link (file, same drive) or a junction (folder);
    copy_ok also allows a copy when neither works. Returns how: "symlink" | "hardlink" | "junction" | "copy"."""
    target, dst = Path(target), Path(dst)
    try:
        dst.symlink_to(target, target_is_directory=target.is_dir())
        return "symlink"
    except (OSError, NotImplementedError):
        if not WINDOWS:
            raise
    if target.is_dir():
        import _winapi
        _winapi.CreateJunction(str(target.resolve()), str(dst))
        return "junction"
    try:
        os.link(target, dst)
        return "hardlink"
    except OSError:
        if not copy_ok:
            raise
    shutil.copy2(target, dst)
    return "copy"


def same_link(dst, target):
    """Does dst already point at target (a link to it, or the same file)?"""
    dst, target = Path(dst), Path(target)
    try:
        if dst.is_symlink():
            return dst.resolve() == target.resolve()
        return WINDOWS and dst.exists() and target.exists() and os.path.samefile(dst, target)
    except OSError:
        return False


def replace(src, dst, wait=15.0):
    """os.replace that waits while Windows still has dst open (the preview streaming the old video)."""
    end = time.time() + (wait if WINDOWS else 0)
    while True:
        try:
            return os.replace(src, dst)
        except PermissionError:
            if time.time() > end:
                raise
            time.sleep(0.25)
