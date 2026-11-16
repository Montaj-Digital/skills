"""Connections to the social platforms (ROADMAP phase 9.4): sign-in, app keys, status, and the scheduler's hand-off.

Every platform is a `Connector` with the same small shape (connectors.py has the real ones, 9.5 batch a: YouTube,
Facebook, Instagram, TikTok, LinkedIn; SOCIAL.md is the developer's guide to linking them):
  auth                "oauth" (sign in on the platform's page) or "password" (Bluesky: handle + app password)
  authorize_url(app, state, redirect)   exchange(app, code, redirect) -> tokens   refresh(app, tokens) -> tokens
  publish(app, tokens, post, video, cover) -> {"id", "link"}     results(app, tokens, remote_id) -> numbers
  delete(app, tokens, remote_id)
  tokens: {"access", "refresh", "expires_at", "account": {"id", "name"}}
With **Use the test platform** on (Social settings), a platform with a real connector runs that same code against its
own stand-in (standins.py, in the platform's shapes); the others use `TestConnector` (testplatform.py). No app keys or
accounts needed.

Where things are kept (team = "local" on a Mac, the team's name on the portal):
  the token store (vault.py)      "<team>/app:<platform>" the developer's app keys; "<team>/token:<platform>" sign-in tokens
  <planner>/connections.json      who is connected (account name, when, test or live). No secrets.
  <planner>/social.json           "connections": {"test_platform": true|false}
Callback address each platform must accept: <public address>/connect/callback/<platform>; the public address is
settings.json "public_url" (or STUDIO_PUBLIC_URL), else this Mac's http://127.0.0.1:<port>.

Routes: GET /api/connect/state · POST /api/connect/{test-platform,app,option,start,disconnect,check}
        GET /connect/callback/<platform>
Python 3.9 standard library only.
"""
import http.client, json, secrets, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import posting
import social
import vault
import workspace

PUBLIC = "http://127.0.0.1:4322"      # set by server.py from its port
settings = dict                        # set by server.py
REAL = {}                              # platform -> Connector class (9.5)
_pending, _plock = {}, threading.Lock()


class ConnectError(RuntimeError):
    pass


class Expired(ConnectError):
    pass


def public_url():
    import os
    try:
        mine = settings().get("public_url")
    except Exception:            # e.g. the scheduler's thread on the portal: no signed-in user, so the server-wide settings
        try:
            mine = json.loads((workspace.DATA / "settings.json").read_text()).get("public_url") if workspace.DATA else None
        except (OSError, ValueError, TypeError):
            mine = None
    return (mine or os.environ.get("STUDIO_PUBLIC_URL") or PUBLIC).rstrip("/")


def callback(platform):
    return f"{public_url()}/connect/callback/{platform}"


# ---------------------------------------------------------------- a small HTTP client (stdlib)
def request(method, url, *, json_body=None, form=None, data=None, file=None, part=None, headers=None, timeout=120, full=False):
    """-> (status, parsed JSON or text), or with full=True (status, body, headers as a lower-case dict).
    file: a path streamed as the body; part=(offset, length) sends only that piece of it."""
    u = urlparse(url)
    conn = (http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection)(u.netloc, timeout=timeout)
    hdr = dict(headers or {})
    if workspace.PORTAL and u.netloc == urlparse(PUBLIC).netloc:      # calling this same server (the test platform)
        import os
        hdr.update({"X-Studio-User": "testplatform", "X-Studio-Portal-Secret": os.environ.get("STUDIO_PORTAL_SECRET", "")})
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode(); hdr.setdefault("Content-Type", "application/json")
    elif form is not None:
        body = urlencode(form).encode(); hdr.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif data is not None:
        body = data
    target = u.path + (f"?{u.query}" if u.query else "")
    try:
        try:
            if file is not None:
                off, n = part or (0, Path(file).stat().st_size)
                hdr["Content-Length"] = str(n)
                with open(file, "rb") as fh:
                    fh.seek(off)
                    conn.request(method, target, body=_Piece(fh, n), headers=hdr)
            else:
                conn.request(method, target, body=body, headers=hdr)
        except (BrokenPipeError, ConnectionResetError):
            pass                     # the platform answered before the upload finished (an error): read that answer
        r = conn.getresponse(); raw = r.read()
    except OSError as e:
        raise ConnectError(f"Couldn't reach {u.netloc}: {e}")
    finally:
        conn.close()
    try:
        out = json.loads(raw or b"{}")
    except ValueError:
        out = raw.decode(errors="replace")
    return (r.status, out, {k.lower(): v for k, v in r.getheaders()}) if full else (r.status, out)


class _Piece:
    """A file-like view of `n` bytes from an open file's current position (http.client reads it in blocks)."""
    def __init__(self, fh, n):
        self.fh, self.left = fh, n

    def read(self, size=-1):
        if self.left <= 0:
            return b""
        b = self.fh.read(self.left if size is None or size < 0 else min(size, self.left))
        self.left -= len(b)
        return b


def wait_for(check, what, timeout=900, every=5):
    """Ask `check()` until it returns something other than None (platforms process a video before it can be posted)."""
    end = time.time() + timeout
    while True:
        r = check()
        if r is not None:
            return r
        if time.time() > end:
            raise ConnectError(f"{what}: the platform was still processing the video after {timeout // 60} minutes")
        time.sleep(every)


def check_reply(status, body, what):
    if status == 401 and isinstance(body, dict) and body.get("error") in ("token_expired", "invalid_token"):
        raise Expired(body.get("message") or "The sign-in has expired")
    if status >= 400:
        msg = body.get("message") or body.get("error") if isinstance(body, dict) else str(body)[:200]
        raise ConnectError(f"{what}: {msg} ({status})")
    return body


# ---------------------------------------------------------------- connectors
class Connector:
    """A real platform. HOSTS names its base addresses; with the test platform on, the same code talks to that platform's
    stand-in inside Studio AI (testplatform.py, /testplatform/<platform>/<host>/…), which answers in the platform's shapes."""
    auth = "oauth"
    live = True
    HOSTS = {}
    OPTIONS = []                  # choices shown under the platform in Social settings: [{key, label, default, choices}]
    POLL = 5                      # seconds between status checks while the platform processes a video

    def __init__(self, platform, test=False, options=None):
        self.platform, self.test = platform, test
        self.options = options or {}
        if test:
            self.POLL = 1

    def url(self, host, path=""):
        """An address the server calls."""
        return (f"{PUBLIC}/testplatform/{self.platform}/{host}" if self.test else self.HOSTS[host]) + path

    UPLOADS = {}                  # other addresses the platform hands out (upload URLs): {host name: real prefix}

    def follow(self, url):
        """An address the platform gave us (an upload URL). With the test platform on, it points at the stand-in."""
        if not self.test:
            return url
        for name, real in sorted({**self.HOSTS, **self.UPLOADS}.items(), key=lambda x: -len(x[1])):
            if url.startswith(real):
                return self.url(name, url[len(real):])
        return url

    def page_url(self, host, path=""):
        """An address the person's browser opens (the sign-in page)."""
        return (f"{public_url()}/testplatform/{self.platform}/{host}" if self.test else self.HOSTS[host]) + path

    def check(self, status, body, what):
        """Turn a platform's error reply into ConnectError / Expired. Connectors override it for their error shapes."""
        return check_reply(status, body, what)

    def caption(self, post, tags=True, limit=None):
        """The post's text with its hashtags on a line of their own."""
        f = post.get("fields") or {}
        text = (f.get("text") or "").strip()
        h = " ".join(f.get("hashtags") or []) if tags else ""
        out = f"{text}\n\n{h}".strip() if h and h not in text else text
        return out[:limit] if limit else out

    def delete(self, app, tokens, remote_id):
        raise ConnectError("Deleting a post isn't possible on this platform from Studio AI")


class TestConnector(Connector):
    """Every platform, against Studio AI's own test platform (testplatform.py)."""
    live = False

    @property
    def base(self):
        return f"{PUBLIC}/testplatform"

    def authorize_url(self, app, state, redirect, verifier=None):
        return f"{public_url()}/testplatform/oauth/authorize?" + urlencode({"client_id": app.get("client_id", "test"), "redirect_uri": redirect,
                                                                           "state": state, "platform": self.platform, "scope": "publish read"})

    def _tokens(self, b, old=None):
        return {"access": b["access_token"], "refresh": b.get("refresh_token") or (old or {}).get("refresh"),
                "expires_at": time.time() + int(b.get("expires_in", 3600)), "account": b.get("account") or (old or {}).get("account")}

    def exchange(self, app, code, redirect, verifier=None):
        s, b = request("POST", f"{self.base}/oauth/token", form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
                                                                 "client_id": app.get("client_id", "test"), "client_secret": app.get("client_secret", "test")})
        return self._tokens(check_reply(s, b, "Signing in"))

    def refresh(self, app, tokens):
        s, b = request("POST", f"{self.base}/oauth/token", form={"grant_type": "refresh_token", "refresh_token": tokens.get("refresh", ""),
                                                                 "client_id": app.get("client_id", "test"), "client_secret": app.get("client_secret", "test")})
        return self._tokens(check_reply(s, b, "Refreshing the sign-in"), tokens)

    def publish(self, app, tokens, post, video, cover):
        auth = {"Authorization": f"Bearer {tokens['access']}"}
        s, b = request("POST", f"{self.base}/api/upload", file=video, headers={**auth, "X-Filename": Path(video).name, "Content-Type": "video/mp4"}, timeout=1800)
        media = check_reply(s, b, "Uploading the video")["media_id"]
        s, b = request("POST", f"{self.base}/api/publish", json_body={"media_id": media, "platform": self.platform, "fields": post["fields"], "base": public_url()}, headers=auth)
        b = check_reply(s, b, "Publishing")
        return {"id": b["id"], "link": b["link"]}

    def results(self, app, tokens, remote_id):
        s, b = request("GET", f"{self.base}/api/results/{remote_id}", headers={"Authorization": f"Bearer {tokens['access']}"})
        return check_reply(s, b, "Reading the results")

    def delete(self, app, tokens, remote_id):
        s, b = request("POST", f"{self.base}/api/delete/{remote_id}", headers={"Authorization": f"Bearer {tokens['access']}"})
        return check_reply(s, b, "Deleting")


# ---------------------------------------------------------------- per team: mode, app keys, tokens, status
def team_of(planner_dir):
    return "local" if not workspace.PORTAL else Path(planner_dir).parent.name


def here():
    """(planner folder, team) for the current request."""
    d = workspace.current().planner
    return d, team_of(d)


def test_mode(d):
    try:
        return bool(json.loads((Path(d) / "social.json").read_text()).get("connections", {}).get("test_platform"))
    except (OSError, ValueError):
        return False


def set_test_mode(on):
    f = social.path()
    try:
        s = json.loads(f.read_text())
    except (OSError, ValueError):
        s = {}
    s.setdefault("connections", {})["test_platform"] = bool(on)
    f.write_text(json.dumps(s, indent=1, ensure_ascii=False))


def options(d, platform):
    """The platform's choices (Social settings), with their defaults."""
    cls = REAL.get(platform)
    try:
        saved = json.loads((Path(d) / "social.json").read_text()).get("connections", {}).get("options", {}).get(platform, {})
    except (OSError, ValueError):
        saved = {}
    out = {}
    for o in (cls.OPTIONS if cls else []):
        v = saved.get(o["key"])
        out[o["key"]] = v if v in [c[0] for c in o["choices"]] else o["default"]
    return out


def set_option(d, platform, key, value):
    cls = REAL.get(platform)
    opt = next((o for o in (cls.OPTIONS if cls else []) if o["key"] == key), None)
    if not opt or value not in [c[0] for c in opt["choices"]]:
        raise ConnectError("Unknown choice")
    f = Path(d) / "social.json"
    try:
        s = json.loads(f.read_text())
    except (OSError, ValueError):
        s = {}
    cur = options(d, platform).get(key)
    s.setdefault("connections", {}).setdefault("options", {}).setdefault(platform, {})[key] = value
    f.write_text(json.dumps(s, indent=1, ensure_ascii=False))
    if platform == "linkedin" and key == "as" and value != cur:
        disconnect(d, platform)          # a page and a profile sign in with different permissions


def connector(d, platform):
    cls = REAL.get(platform)
    if test_mode(d):
        return cls(platform, test=True, options=options(d, platform)) if cls else TestConnector(platform)
    if not cls:
        raise ConnectError(f"The {platform} connection isn't built yet; use the test platform for now")
    return cls(platform, options=options(d, platform))


SHARED_APP = {"instagram": "facebook"}     # Instagram signs in through the same Meta app as Facebook


def app_keys(d, platform):
    if test_mode(d):
        return {"client_id": "test", "client_secret": "test"}
    keys = vault.get(d, f"{team_of(d)}/app:{platform}") or {}
    if not keys.get("client_id") and platform in SHARED_APP:
        keys = vault.get(d, f"{team_of(d)}/app:{SHARED_APP[platform]}") or {}
    return keys


def meta(d):
    try:
        return json.loads((Path(d) / "connections.json").read_text())
    except (OSError, ValueError):
        return {}


def save_meta(d, m):
    (Path(d) / "connections.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))


def store_tokens(d, platform, tokens, mode):
    vault.set(d, f"{team_of(d)}/token:{platform}", tokens)
    lasts = tokens.get("refresh_expires_at") or (tokens.get("expires_at") if not tokens.get("refresh") else None)   # when someone must sign in again
    m = meta(d); m[platform] = {"account": (tokens.get("account") or {}).get("name") or "", "connected_at": time.time(), "mode": mode, "error": None,
                                "expires": lasts}
    save_meta(d, m)


def tokens_for(d, platform):
    """Fresh tokens for a platform (refreshed when they expire within a minute), or None if not connected."""
    m = meta(d).get(platform)
    if not m or m.get("mode") != ("test" if test_mode(d) else "live"):
        return None
    t = vault.get(d, f"{team_of(d)}/token:{platform}")
    if not t:
        return None
    if t.get("expires_at") and t["expires_at"] < time.time() + 60 and t.get("refresh"):
        t = connector(d, platform).refresh(app_keys(d, platform), t)
        vault.set(d, f"{team_of(d)}/token:{platform}", t)
    return t


def disconnect(d, platform):
    vault.delete(d, f"{team_of(d)}/token:{platform}")
    m = meta(d); m.pop(platform, None); save_meta(d, m)


# ---------------------------------------------------------------- the scheduler's side (posting.CONNECTORS)
class Channel:
    """What posting.tick() calls for one platform: is it connected, and post this."""
    def __init__(self, platform):
        self.platform = platform

    def connected(self, d):
        m = meta(d).get(self.platform)
        return bool(m and m.get("mode") == ("test" if test_mode(d) else "live"))

    def publish(self, d, post):
        con, app = connector(d, self.platform), app_keys(d, self.platform)
        video = post["video"].get("render")
        if not video or not Path(video).is_file():
            raise ConnectError("The rendered video isn't there any more: render it again")
        cover = Path(d) / "covers" / f"{post['id']}.jpg"
        for attempt in (1, 2):
            t = tokens_for(d, self.platform)
            if not t:
                raise ConnectError("Not connected any more: connect it again in Social settings")
            try:
                res = con.publish(app, t, post, video, str(cover) if cover.exists() else None)
                post["remote_id"], post["mode"] = res.get("id"), "test" if test_mode(d) else "live"
                return res
            except Expired:
                if attempt == 2:
                    raise
                t["expires_at"] = 0
                vault.set(d, f"{team_of(d)}/token:{self.platform}", t)     # force a refresh, then try once more

    def results(self, d, post):
        if not post.get("remote_id"):
            return None
        t = tokens_for(d, self.platform)
        return connector(d, self.platform).results(app_keys(d, self.platform), t, post["remote_id"]) if t else None


def install():
    import planner, connectors        # connectors fills REAL
    for p in planner.ORDER:
        posting.CONNECTORS[p] = Channel(p)


# ---------------------------------------------------------------- routes
def state():
    import planner
    d, team = here()
    test, m = test_mode(d), meta(d)
    ok, store = vault.check(d)
    out = {}
    for p in planner.ORDER:
        con = None
        try:
            con = connector(d, p)
        except ConnectError:
            pass
        c = m.get(p) if (m.get(p) or {}).get("mode") == ("test" if test else "live") else None
        has_app = test or bool(app_keys(d, p).get("client_id")) if ok else False
        out[p] = {"auth": (con.auth if con else (REAL[p].auth if p in REAL else "oauth")), "built": test or p in REAL, "app_keys": has_app,
                  "client_id": (vault.get(d, f"{team}/app:{p}") or {}).get("client_id", "") if ok and not test else "",
                  "connected": bool(c), "account": (c or {}).get("account"), "since": (c or {}).get("connected_at"), "error": (c or {}).get("error"),
                  "expires": (c or {}).get("expires"), "callback": callback(p),
                  "options": [dict(o, value=options(d, p)[o["key"]]) for o in (REAL[p].OPTIONS if p in REAL else [])]}
    return {"test_platform": test, "store": {"ok": ok, "what": store}, "public_url": public_url(), "platforms": out}


def start(platform):
    d, _ = here()
    con = connector(d, platform)
    app = app_keys(d, platform)
    if con.auth != "oauth":
        raise ConnectError("This platform signs in with a handle and app password")
    if not app.get("client_id"):
        raise ConnectError("Add the app keys first (App keys, for the developer)")
    st, verifier = secrets.token_urlsafe(18), secrets.token_urlsafe(48)        # verifier: PKCE, for platforms that use it
    with _plock:
        for k in [k for k, v in _pending.items() if v["at"] < time.time() - 900]:
            _pending.pop(k)
        _pending[st] = {"ws": workspace.current(), "platform": platform, "at": time.time(), "verifier": verifier}
    return con.authorize_url(app, st, callback(platform), verifier=verifier)


def finish(h, platform, q):
    st = q.get("state", [""])[0]
    with _plock:
        p = _pending.pop(st, None)
    if not p or p["platform"] != platform:
        return False, "This sign-in link has expired: press Connect again"
    if q.get("error"):
        return False, "Not connected: the sign-in was cancelled"
    workspace.use(p["ws"])
    d, _ = here()
    tokens = connector(d, platform).exchange(app_keys(d, platform), q.get("code", [""])[0], callback(platform), verifier=p["verifier"])
    store_tokens(d, platform, tokens, "test" if test_mode(d) else "live")
    return True, (tokens.get("account") or {}).get("name") or platform


def done_page(h, ok, msg):
    color = "#0f8a4a" if ok else "#c8312b"
    body = (f"<!doctype html><meta charset='utf-8'><title>Studio AI</title><body style='font:16px -apple-system,Inter,sans-serif;display:grid;place-items:center;height:90vh;background:#f5f3f3'>"
            f"<div style='background:#fff;padding:28px 34px;border-radius:16px;box-shadow:0 10px 30px rgba(18, 80, 90,.12);text-align:center;max-width:420px'>"
            f"<div style='font-weight:800;font-size:20px;color:{color}'>{'Connected' if ok else 'Not connected'}</div><p>{msg}</p>"
            f"<p style='color:#888;font-size:13px'>You can close this tab.</p></div>"
            f"<script>try{{window.opener&&window.opener.postMessage({{studioConnect:{json.dumps(ok)}}},'*')}}catch(e){{}};setTimeout(()=>window.close(),{900 if ok else 4000})</script>").encode()
    h.send_response(200); h.send_header("Content-Type", "text/html; charset=utf-8"); h.send_header("Content-Length", str(len(body))); h.end_headers(); h.wfile.write(body)


def handle(h, method, path, q):
    if not path.startswith(("/api/connect/", "/connect/callback/")):
        return False
    import planner
    try:
        if method == "GET" and path.startswith("/connect/callback/"):
            plat = path.rsplit("/", 1)[-1]
            try:
                ok, msg = finish(h, plat, q)
                done_page(h, ok, f"your brand's {planner.PLATFORMS[plat]['name']}: {msg}" if ok else msg)
            except (ConnectError, vault.VaultError, KeyError) as e:
                done_page(h, False, str(e))
            return True
        if method == "GET" and path == "/api/connect/state":
            h.send_json(state()); return True
        if method != "POST":
            return False
        b = h.body()
        plat = b.get("platform")
        if plat is not None and plat not in planner.PLATFORMS:
            raise ConnectError("Unknown platform")
        d, team = here()
        if path == "/api/connect/test-platform":
            set_test_mode(b.get("on")); h.send_json(state()); return True
        if path == "/api/connect/app":
            keys = {k: str(v).strip() for k, v in (b.get("keys") or {}).items() if str(v).strip()}
            cur = vault.get(d, f"{team}/app:{plat}") or {}
            if keys.get("client_secret", "").startswith("•"):
                keys.pop("client_secret")                    # the page shows a mask; unchanged
            vault.set(d, f"{team}/app:{plat}", {**cur, **keys}); h.send_json(state()); return True
        if path == "/api/connect/start":
            h.send_json({"url": start(plat)}); return True
        if path == "/api/connect/option":
            set_option(d, plat, b.get("key"), b.get("value")); h.send_json(state()); return True
        if path == "/api/connect/disconnect":
            disconnect(d, plat); h.send_json(state()); return True
        if path == "/api/connect/check":
            t = tokens_for(d, plat)
            h.send_json({"ok": bool(t), "account": (t or {}).get("account"), "expires_at": (t or {}).get("expires_at")}); return True
    except (ConnectError, vault.VaultError) as e:
        h.send_json({"error": str(e)}, 400); return True
    return False
