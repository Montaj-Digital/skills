"""The test platform (ROADMAP phase 9.4): a stand-in social platform inside Studio AI, so the planner can be built,
tested and shown with no real accounts. It behaves like a platform's API, including its errors:
  GET  /testplatform/oauth/authorize?client_id&redirect_uri&state&platform   a sign-in page: Allow / Deny
  POST /testplatform/oauth/token          grant_type=authorization_code | refresh_token  → access (expires in 2 min), refresh
  POST /testplatform/api/upload           the video (raw body, Bearer token) → {media_id, bytes}
  POST /testplatform/api/publish          {media_id, platform, fields} → {id, link}
  GET  /testplatform/api/results/<id>     views, likes, comments, shares, watch time (they grow over time)
  POST /testplatform/api/delete/<id>
  GET  /testplatform/                     everything posted, like a feed; /testplatform/p/<id> one post
  POST /testplatform/control {fail_next: rate_limit|expired|too_long|server, count}   make the next calls fail
Errors: 401 {"error": "token_expired"}, 429 rate_limit, 400 video_too_long, 500 server_error.
Platforms with a real connection (9.5) each have their own stand-in under /testplatform/<platform>/… (standins.py),
answering in that platform's own shapes; the routes above serve the platforms that don't have one yet.
On the team portal it only answers when STUDIO_TEST_PLATFORM=1. Kept in memory (a restart forgets it).
Python 3.9 standard library only.
"""
import hashlib, html, json, os, secrets, threading, time
from urllib.parse import parse_qs, urlencode, urlparse

import workspace

STANDINS = ("youtube", "facebook", "instagram", "tiktok", "linkedin")    # platforms with their own stand-in (9.5)
TOKEN_LIFE = 120          # seconds: short, so token refresh gets exercised
S = {"codes": {}, "tokens": {}, "refresh": {}, "media": {}, "posts": {}, "fail": [], "lock": threading.Lock()}
NAMES = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube", "facebook": "Facebook", "linkedin": "LinkedIn",
         "x": "X", "threads": "Threads", "pinterest": "Pinterest", "google": "Google Business", "bluesky": "Bluesky"}


def enabled():
    return not workspace.PORTAL or os.environ.get("STUDIO_TEST_PLATFORM") == "1"


def _page(h, body, code=200):
    data = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Test platform</title><style>
body{{margin:0;font:15px/1.5 -apple-system,Segoe UI,Inter,sans-serif;background:#f3f1f6;color:#222}}
.w{{max-width:440px;margin:60px auto;background:#fff;border-radius:18px;padding:28px;box-shadow:0 10px 40px rgba(18, 80, 90,.12)}}
.tag{{display:inline-block;font:700 11px sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#4ce3f5;background:#eafbfe;padding:4px 9px;border-radius:99px}}
h1{{font-size:22px;margin:14px 0 6px}} .acc{{display:flex;gap:12px;align-items:center;background:#f7f5fa;border-radius:12px;padding:12px;margin:16px 0}}
.av{{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#22d3ee,#2563eb)}}
.b{{display:flex;gap:10px;margin-top:18px}} a.btn{{flex:1;text-align:center;padding:11px;border-radius:99px;text-decoration:none;font-weight:700}}
.ok{{background:linear-gradient(255deg,#22d3ee,#2563eb);color:#fff}} .no{{border:1px solid #ddd;color:#333}}
ul{{color:#555;padding-left:18px}} .post{{border-top:1px solid #eee;padding:14px 0}} img{{max-width:120px;border-radius:10px}} small{{color:#888}}
</style></head><body><div class="w">{body}</div></body></html>""".encode()
    h.send_response(code); h.send_header("Content-Type", "text/html; charset=utf-8"); h.send_header("Content-Length", str(len(data)))
    h.send_header("Cache-Control", "no-store"); h.end_headers(); h.wfile.write(data)


def _fail(h):
    """If a failure was asked for, answer with it and return True (after reading the request, as a real server does)."""
    with S["lock"]:
        if not S["fail"]:
            return False
        kind = S["fail"].pop(0)
    left = int(h.headers.get("Content-Length", 0) or 0)
    while left > 0:
        chunk = h.rfile.read(min(1 << 20, left))
        if not chunk:
            break
        left -= len(chunk)
    code, err = {"rate_limit": (429, "rate_limit"), "expired": (401, "token_expired"), "too_long": (400, "video_too_long"),
                 "server": (500, "server_error")}.get(kind, (500, "server_error"))
    h.send_json({"error": err, "message": f"Test platform: {err.replace('_', ' ')}"}, code)
    return True


def _who(h):
    auth = h.headers.get("Authorization", "")
    tok = S["tokens"].get(auth.removeprefix("Bearer ").strip())
    if not tok:
        h.send_json({"error": "invalid_token", "message": "Test platform: not signed in"}, 401); return None
    if tok["expires"] < time.time():
        h.send_json({"error": "token_expired", "message": "Test platform: the access token has expired"}, 401); return None
    return tok


def _new_tokens(platform, account):
    access, refresh = "tpa_" + secrets.token_hex(12), "tpr_" + secrets.token_hex(12)
    S["tokens"][access] = {"platform": platform, "account": account, "expires": time.time() + TOKEN_LIFE}
    S["refresh"][refresh] = {"platform": platform, "account": account}
    return {"access_token": access, "refresh_token": refresh, "expires_in": TOKEN_LIFE, "token_type": "Bearer",
            "account": {"id": account["id"], "name": account["name"]}}


def handle(h, method, path, q):
    if not path.startswith("/testplatform"):
        return False
    if not enabled():
        h.send_error(404); return True
    p = path[len("/testplatform"):] or "/"
    seg = p.split("/")
    if len(seg) > 2 and seg[1] in STANDINS:          # a platform's own stand-in (standins.py), in its shapes
        import standins
        return standins.handle(h, method, seg[1], p[len(seg[1]) + 1:], q) or (h.send_error(404) or True)
    if method == "GET" and p == "/oauth/authorize":
        plat = q.get("platform", ["instagram"])[0]
        ru, st = q.get("redirect_uri", [""])[0], q.get("state", [""])[0]
        if not ru.startswith(("http://127.0.0.1", "http://localhost", "https://")):
            _page(h, "<h1>Bad redirect address</h1>", 400); return True
        code = "tpc_" + secrets.token_hex(10)
        name = NAMES.get(plat, plat)
        S["codes"][code] = {"platform": plat, "account": {"id": "tp_" + hashlib.sha1(plat.encode()).hexdigest()[:8], "name": f"Your Brand on {name} (test)"},
                            "redirect_uri": ru, "expires": time.time() + 300}
        sep = "&" if "?" in ru else "?"
        ok, no = f"{ru}{sep}{urlencode({'code': code, 'state': st})}", f"{ru}{sep}{urlencode({'error': 'access_denied', 'state': st})}"
        _page(h, f"""<span class="tag">Test platform · {html.escape(name)}</span><h1>Connect Studio AI?</h1>
<p>This stands in for {html.escape(name)}'s own sign-in page, so the planner can be tested without a real account.</p>
<div class="acc"><div class="av"></div><div><b>Your Brand (test)</b><br><small>test account</small></div></div>
<p>Studio AI will be able to:</p><ul><li>post videos for you</li><li>read how your posts do</li></ul>
<div class="b"><a class="btn no" href="{html.escape(no)}">Deny</a><a class="btn ok" href="{html.escape(ok)}">Allow</a></div>"""); return True
    if method == "POST" and p == "/oauth/token":
        raw = h.rfile.read(int(h.headers.get("Content-Length", 0) or 0)).decode()
        b = json.loads(raw) if raw.strip().startswith("{") else {k: v[0] for k, v in parse_qs(raw).items()}
        if _fail(h):
            return True
        with S["lock"]:
            if b.get("grant_type") == "authorization_code":
                c = S["codes"].pop(b.get("code", ""), None)
                if not c or c["expires"] < time.time() or c["redirect_uri"] != b.get("redirect_uri"):
                    h.send_json({"error": "invalid_grant"}, 400); return True
                h.send_json(_new_tokens(c["platform"], c["account"])); return True
            if b.get("grant_type") == "refresh_token":
                r = S["refresh"].get(b.get("refresh_token", ""))
                if not r:
                    h.send_json({"error": "invalid_grant"}, 400); return True
                t = _new_tokens(r["platform"], r["account"]); S["refresh"].pop(t["refresh_token"]); t["refresh_token"] = b["refresh_token"]
                h.send_json(t); return True
        h.send_json({"error": "unsupported_grant_type"}, 400); return True
    if method == "POST" and p == "/control":
        b = h.body()
        with S["lock"]:
            S["fail"] = [b.get("fail_next")] * int(b.get("count", 1)) if b.get("fail_next") else []
        h.send_json({"ok": True, "fail": S["fail"]}); return True
    if p.startswith("/api/"):
        if _fail(h):
            return True
        tok = _who(h)
        if not tok:
            return True
        if method == "POST" and p == "/api/upload":
            n, left, sha = 0, int(h.headers.get("Content-Length", 0) or 0), hashlib.sha256()
            while left > 0:
                chunk = h.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                sha.update(chunk); n += len(chunk); left -= len(chunk)
            mid = "tpm_" + secrets.token_hex(8)
            S["media"][mid] = {"bytes": n, "sha256": sha.hexdigest(), "name": h.headers.get("X-Filename", "video.mp4")}
            h.send_json({"media_id": mid, "bytes": n}); return True
        if method == "POST" and p == "/api/publish":
            b = h.body()
            if b.get("media_id") not in S["media"]:
                h.send_json({"error": "media_not_found"}, 400); return True
            pid = "tpp_" + secrets.token_hex(6)
            S["posts"][pid] = {"id": pid, "platform": tok["platform"], "account": tok["account"]["name"], "fields": b.get("fields") or {},
                               "media": S["media"][b["media_id"]], "at": time.time(), "deleted": False}
            h.send_json({"id": pid, "link": f"{b.get('base', '')}/testplatform/p/{pid}"}); return True
        if method == "GET" and p.startswith("/api/results/"):
            post = S["posts"].get(p.rsplit("/", 1)[-1])
            if not post:
                h.send_json({"error": "not_found"}, 404); return True
            age = max(0.0, time.time() - post["at"]) / 60
            views = int(40 * age ** 1.1 + 12)
            h.send_json({"views": views, "likes": views // 14, "comments": views // 90, "shares": views // 120, "watch_time_s": views * 9}); return True
        if method == "POST" and p.startswith("/api/delete/"):
            post = S["posts"].get(p.rsplit("/", 1)[-1])
            if post:
                post["deleted"] = True
            h.send_json({"ok": bool(post)}); return True
        h.send_json({"error": "not_found"}, 404); return True
    if method == "GET" and (p == "/" or p.startswith("/p/")):
        posts = [x for x in S["posts"].values() if not x["deleted"]]
        if p.startswith("/p/"):
            posts = [x for x in posts if x["id"] == p[3:]]
        items = "".join(f"""<div class="post"><span class="tag">{html.escape(NAMES.get(x['platform'], x['platform']))}</span>
<p><b>{html.escape(x['account'])}</b> · <small>{time.strftime('%d %b %H:%M', time.localtime(x['at']))} · {x['media']['bytes'] / 1e6:.1f} MB video</small></p>
<p>{html.escape(x['fields'].get('title') or '')}</p><p style="white-space:pre-wrap">{html.escape(x['fields'].get('text') or '')}</p>
<p style="color:#4ce3f5">{html.escape(' '.join(x['fields'].get('hashtags') or []))}</p></div>""" for x in sorted(posts, key=lambda x: -x["at"]))
        _page(h, f"<span class='tag'>Test platform</span><h1>Posted ({len(posts)})</h1>{items or '<p>Nothing posted yet.</p>'}"); return True
    h.send_error(404); return True
