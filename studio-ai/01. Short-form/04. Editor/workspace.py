"""Whose videos, kits and settings a request works on (ROADMAP phase 7: ready for the team web portal).

On a Mac (the default) there is one workspace, "local": the folders inside Studio AI, exactly as before.

On the portal's server, set STUDIO_DATA to a storage folder. Every request then names its user (and team) in headers the
portal adds after its own sign-in; the browser never sends them itself:
    X-Studio-User      the signed-in user's id (letters, digits, . _ @ -)          required
    X-Studio-Team      the team whose brand kits and music library they share     optional, default "team"
    X-Studio-Portal-Secret   must equal STUDIO_PORTAL_SECRET when that is set (so only the portal can talk to this server)
Storage layout under STUDIO_DATA:
    settings.json                                   server-wide settings (claude_backend, claude_model, software_encode …)
    users/<user>/settings.json                      that user's own settings, on top of the server's
    users/<user>/01. Short-form/05. Projects, 06. Renders
    users/<user>/02. Long-form/05. Projects, 06. Renders
    users/<user>/Bin/                               deleted projects
    users/<user>/.uploads/                          uploads in progress (uploads.py)
    users/<user>/02. Long-form/Uploads/             long recordings and subtitle files uploaded for a new long-form video
    teams/<team>/03. Brands/<kit>/                  client brand kits (your brand always comes from the app itself)
    teams/<team>/05. Music/                         the team's music library
    teams/<team>/Planner/                           social settings and scheduled posts (social.py, posting.py)
    teams/<team>/Bin/                               deleted brand kits
The library location can't be changed by a user's settings there: everything stays inside their own storage.

The request's workspace is kept per thread; jobs started from a request use workspace.Thread so they keep it.
Each workspace has its own "open project", render and zoom job state (`slot()`), so users never see each other's.
"""
import hmac, json, os, re, sys, threading
from pathlib import Path

HERE = Path(__file__).resolve().parent           # 01. Short-form/04. Editor
STUDIO = HERE.parent.parent                      # 03. Studio AI
DATA = Path(os.environ["STUDIO_DATA"]).expanduser().resolve() if os.environ.get("STUDIO_DATA") else None
SECRET = os.environ.get("STUDIO_PORTAL_SECRET") or None
PORTAL = DATA is not None
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,63}")


class Denied(Exception):
    """The request didn't say (or prove) who it's for."""


def _read(f):
    try:
        return json.loads(Path(f).read_text()) if Path(f).exists() else {}
    except (OSError, ValueError):
        return {}


class Workspace:
    def __init__(self, user, team):
        self.user, self.team = user, team
        self.id = f"{team}/{user}" if PORTAL else "local"
        self._state, self._lock = {}, threading.Lock()
        if PORTAL:
            u, t = DATA / "users" / user, DATA / "teams" / team
            self.short_base, self.long_base = u / "01. Short-form", u / "02. Long-form"
            self.brands, self.music, self.planner = t / "03. Brands", t / "05. Music", t / "Planner"
            self.trash, self.kit_trash = u / "Bin", t / "Bin"
            self.recent_file, self.uploads, self.home = u / ".recent.json", u / ".uploads", u
            self.settings_files = {"short": [DATA / "settings.json", u / "settings.json"]}
            self.settings_files["long"] = self.settings_files["short"]
        else:
            self.short_base, self.long_base = STUDIO / "01. Short-form", STUDIO / "02. Long-form"
            self.brands, self.music, self.planner = STUDIO / "03. Brands", STUDIO / "05. Music", STUDIO / "08. Planner"
            import osutil
            self.trash = self.kit_trash = osutil.bin_folder()      # the Mac's Bin; Studio AI's Bin folder on Windows
            self.recent_file, self.uploads, self.home = HERE / ".recent.json", HERE / ".cache/uploads", STUDIO
            self.settings_files = {"short": [HERE / "settings.json"],
                                   "long": [self.long_base / "04. Editor" / "settings.json"]}

    def __repr__(self):
        return f"Workspace({self.id})"

    def settings(self, kind="short"):
        """Settings for this user: the server's, then their own (on a Mac: the editor's settings.json, as before)."""
        s = {"library": str(self.short_base)} if kind == "short" else {}
        for f in self.settings_files[kind]:
            s.update(_read(f))
        if sys.platform != "darwin":
            s.setdefault("software_encode", True)      # VideoToolbox (the default encoder) is macOS only
        if PORTAL:
            s["library"] = str(self.short_base)        # never outside their storage
            s.pop("claude_cmd", None)
        return s

    def inside(self, path):
        """Is this path inside the user's own storage? (Always true on a Mac, which has no such limit.)"""
        if not PORTAL:
            return True
        try:
            p = Path(path).resolve()
        except (OSError, ValueError):
            return False
        return any(p == r or r in p.parents for r in (self.short_base.resolve(), self.long_base.resolve(), self.brands.resolve()))

    def shown(self, path):
        """A path as the page may show it: on the portal, relative to the user's storage (never the server's folders)."""
        if not PORTAL or not path:
            return str(path) if path else path
        for r, label in ((self.home, ""), (self.brands.parent, "Team/")):
            try:
                return label + Path(path).resolve().relative_to(r.resolve()).as_posix()
            except ValueError:
                continue
        return Path(path).name

    def slot(self, name, make):
        """Per-workspace state (the open project, the render job …), made on first use."""
        with self._lock:
            if name not in self._state:
                self._state[name] = make()
            return self._state[name]


LOCAL = None if PORTAL else Workspace("local", "local")
_all, _all_lock, _here = {}, threading.Lock(), threading.local()


def for_request(headers):
    """The workspace a request is for (raises Denied when the portal's headers are missing or wrong)."""
    if not PORTAL:
        return LOCAL
    if SECRET and not hmac.compare_digest(headers.get("X-Studio-Portal-Secret") or "", SECRET):
        raise Denied("This server only takes requests from the portal")
    user, team = (headers.get("X-Studio-User") or "").strip(), (headers.get("X-Studio-Team") or "team").strip()
    if not ID.fullmatch(user) or not ID.fullmatch(team) or user in (".", "..") or team in (".", ".."):
        raise Denied("Sign in through the portal (no user on this request)")
    with _all_lock:
        if (team, user) not in _all:
            _all[(team, user)] = Workspace(user, team)
        return _all[(team, user)]


def use(ws):
    _here.ws = ws


def current():
    ws = getattr(_here, "ws", None) or LOCAL
    if ws is None:
        raise RuntimeError("No workspace for this thread (start jobs with workspace.Thread)")
    return ws


class Thread(threading.Thread):
    """A thread that works in the workspace of whoever started it."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._ws = getattr(_here, "ws", None)

    def run(self):
        use(self._ws)
        super().run()


class Slot:
    """An object whose attributes live in the current workspace (server.py's `P`: the open project)."""

    def __init__(self, name, **defaults):
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_defaults", defaults)

    def _ns(self):
        return current().slot(self._name, lambda: dict(self._defaults))

    def __getattr__(self, k):
        ns = self._ns()
        if k not in ns:
            raise AttributeError(k)
        return ns[k]

    def __setattr__(self, k, v):
        self._ns()[k] = v


class SlotDict(dict):
    """A dict that lives in the current workspace (server.py's `render` and `zoomjob`)."""

    def __init__(self, name, **defaults):
        super().__init__()
        self._name, self._defaults = name, defaults

    def _d(self):
        return current().slot(self._name, lambda: dict(self._defaults))

    def __getitem__(self, k): return self._d()[k]
    def __setitem__(self, k, v): self._d()[k] = v
    def __contains__(self, k): return k in self._d()
    def __iter__(self): return iter(self._d())
    def __len__(self): return len(self._d())
    def get(self, k, default=None): return self._d().get(k, default)
    def update(self, *a, **k): self._d().update(*a, **k)
    def items(self): return self._d().items()
    def keys(self): return self._d().keys()
    def values(self): return self._d().values()
    def copy(self): return dict(self._d())


class SlotLock:
    """A lock per workspace (one user's preview build never waits for another's)."""

    def __init__(self, name):
        self._name = name

    def __enter__(self):
        current().slot(self._name, threading.Lock).acquire()

    def __exit__(self, *a):
        current().slot(self._name, threading.Lock).release()


class Env(dict):
    """The environment for tools: the server's, plus STUDIO_BRANDS = this workspace's kits (studio-reel's brand.py)."""

    def __init__(self, base):
        super().__init__()
        self._base = dict(base)

    def _e(self):
        try:
            ws = current()
        except RuntimeError:
            return self._base
        return dict(self._base, STUDIO_BRANDS=str(ws.brands)) if PORTAL else self._base

    def __getitem__(self, k): return self._e()[k]
    def __contains__(self, k): return k in self._e()
    def __iter__(self): return iter(self._e())
    def __len__(self): return len(self._e())
    def get(self, k, default=None): return self._e().get(k, default)
    def items(self): return self._e().items()
    def keys(self): return self._e().keys()
    def values(self): return self._e().values()
    def copy(self): return dict(self._e())
