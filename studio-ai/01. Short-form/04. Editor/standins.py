"""Per-platform stand-ins for the test platform (ROADMAP phase 9.5): YouTube, Facebook, Instagram, TikTok and LinkedIn,
each answering in its platform's own shapes (addresses, fields, headers, status codes and errors, as researched on
2026-10-18), so the real connectors in connectors.py run end to end with no accounts.

Served under /testplatform/<platform>/<host>/…, where <host> stands for the platform's own server
(e.g. youtube/api = www.googleapis.com, facebook/graph = graph.facebook.com, linkedin/api = api.linkedin.com).
They share the test platform's sign-in page, feed (/testplatform/) and failure switch (/testplatform/control).
Tokens: YouTube and TikTok expire after 2 minutes (to exercise refreshing); Meta Page tokens never expire; LinkedIn
lasts 60 days and has no refresh token, as for most real LinkedIn apps.
Python 3.9 standard library only.
"""
import base64, hashlib, html, json, re, secrets, time
from urllib.parse import parse_qs, quote, unquote, urlencode

import testplatform as tp

NAMES = {"youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram", "tiktok": "TikTok", "linkedin": "LinkedIn"}
ACCOUNT = {"youtube": ("UCtestStudioAI00000000", "Your Brand (test)"), "facebook": ("pg_1001", "Your Brand (test)"),
           "instagram": ("igu_2001", "studio.test"), "tiktok": ("tt_open_3001", "Your Brand (test)"),
           "linkedin": ("urn:li:organization:9001", "Your Brand (test)")}
LIFE = {"youtube": tp.TOKEN_LIFE, "tiktok": tp.TOKEN_LIFE, "linkedin": 5184000, "facebook": None, "instagram": None}
X = {"uploads": {}, "objects": {}}          # upload sessions; Facebook/Instagram/LinkedIn objects by id


# ---------------------------------------------------------------- small helpers
def reply(h, code, obj=None, headers=None):
    data = b"" if obj is None else json.dumps(obj).encode()
    h.send_response(code)
    for k, v in (headers or {}).items():
        h.send_header(k, v)
    if obj is not None:
        h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    if data:
        h.wfile.write(data)
    return True


def read_body(h, keep=False):
    """-> (bytes received, sha256, the data if keep)."""
    left, n, sha, buf = int(h.headers.get("Content-Length", 0) or 0), 0, hashlib.sha256(), []
    while left > 0:
        chunk = h.rfile.read(min(1 << 20, left))
        if not chunk:
            break
        sha.update(chunk); n += len(chunk); left -= len(chunk)
        if keep:
            buf.append(chunk)
    return n, sha.hexdigest(), b"".join(buf)


def form_or_json(raw):
    t = raw.decode(errors="replace").strip()
    if t.startswith("{"):
        return json.loads(t)
    return {k: v[0] for k, v in parse_qs(t, keep_blank_values=True).items()}


def base(h):
    return f"http://{h.headers.get('Host', '127.0.0.1')}/testplatform"


def views(at):
    age = max(0.0, time.time() - at) / 60
    return int(40 * age ** 1.1 + 12)


# ---------------------------------------------------------------- errors in each platform's shape
def error(h, plat, kind, msg=None):
    msg = msg or f"Test platform: {kind.replace('_', ' ')}"
    if plat == "youtube":
        code, reason = {"expired": (401, "authError"), "invalid": (401, "authError"), "rate_limit": (403, "rateLimitExceeded"),
                        "too_long": (400, "invalidVideoMetadata"), "server": (503, "backendError")}.get(kind, (400, kind))
        return reply(h, code, {"error": {"code": code, "message": msg, "errors": [{"message": msg, "domain": "youtube.test", "reason": reason}]}})
    if plat in ("facebook", "instagram"):
        code, sub = {"expired": (190, 463), "invalid": (190, 467), "rate_limit": (4, None), "too_long": (100, 1363128), "server": (2, None)}.get(kind, (100, None))
        e = {"message": msg, "type": "OAuthException", "code": code, "fbtrace_id": secrets.token_hex(6)}
        if sub:
            e["error_subcode"] = sub
        return reply(h, 500 if kind == "server" else 400, {"error": e})
    if plat == "tiktok":
        code, err = {"expired": (401, "access_token_invalid"), "invalid": (401, "access_token_invalid"), "rate_limit": (429, "rate_limit_exceeded"),
                     "too_long": (400, "invalid_param"), "server": (500, "internal_error")}.get(kind, (400, kind))
        return reply(h, code, {"error": {"code": err, "message": msg, "log_id": secrets.token_hex(8)}})
    code, c = {"expired": (401, "EXPIRED_ACCESS_TOKEN"), "invalid": (401, "INVALID_ACCESS_TOKEN"), "rate_limit": (429, "TOO_MANY_REQUESTS"),
               "too_long": (400, "INVALID_VALUE_FOR_FIELD"), "server": (500, "INTERNAL_SERVER_ERROR")}.get(kind, (400, kind.upper()))
    return reply(h, code, {"status": code, "serviceErrorCode": 65600, "code": c, "message": msg})


def failed(h, plat):
    """The test platform's failure switch, answered in this platform's shape."""
    with tp.S["lock"]:
        if not tp.S["fail"]:
            return False
        kind = tp.S["fail"].pop(0)
    read_body(h)
    error(h, plat, kind)
    return True


def who(h, plat):
    auth = h.headers.get("Authorization", "")
    token = re.sub(r"^(Bearer|OAuth)\s+", "", auth).strip() or (h.q.get("access_token", [""])[0] if hasattr(h, "q") else "")
    t = tp.S["tokens"].get(token)
    if not t or t["platform"] != plat:
        error(h, plat, "invalid", "Test platform: no valid access token"); return None
    if t["expires"] and t["expires"] < time.time():
        error(h, plat, "expired", "Test platform: the access token has expired"); return None
    return t


def tokens(plat, account, with_refresh=True):
    access = "tpa_" + secrets.token_hex(12)
    life = LIFE[plat]
    tp.S["tokens"][access] = {"platform": plat, "account": account, "expires": time.time() + life if life else None}
    out = {"access_token": access, "token_type": "Bearer"}
    if life:
        out["expires_in"] = life
    if with_refresh:
        refresh = "tpr_" + secrets.token_hex(12)
        tp.S["refresh"][refresh] = {"platform": plat, "account": account}
        out["refresh_token"] = refresh
    return out


def consent(h, plat, q, id_key="client_id"):
    ru, st = q.get("redirect_uri", [""])[0], q.get("state", [""])[0]
    if not q.get(id_key, [""])[0]:
        tp._page(h, f"<h1>Missing {id_key}</h1>", 400); return True
    if not ru.startswith(("http://127.0.0.1", "http://localhost", "https://")):
        tp._page(h, "<h1>Bad redirect address</h1>", 400); return True
    code = "tpc_" + secrets.token_hex(10)
    aid, name = ACCOUNT[plat]
    tp.S["codes"][code] = {"platform": plat, "account": {"id": aid, "name": name}, "redirect_uri": ru, "expires": time.time() + 300,
                           "challenge": q.get("code_challenge", [None])[0], "scope": q.get("scope", [""])[0]}
    sep = "&" if "?" in ru else "?"
    ok, no = f"{ru}{sep}{urlencode({'code': code, 'state': st})}", f"{ru}{sep}{urlencode({'error': 'access_denied', 'state': st})}"
    scopes = [s for s in re.split(r"[ ,]+", q.get("scope", [""])[0]) if s]
    tp._page(h, f"""<span class="tag">Test platform · {html.escape(NAMES[plat])}</span><h1>Connect Studio AI?</h1>
<p>This stands in for {html.escape(NAMES[plat])}'s own sign-in page, in its shapes, so the real connection can be tested without an account.</p>
<div class="acc"><div class="av"></div><div><b>{html.escape(name)}</b><br><small>test account</small></div></div>
<p>Permissions asked for:</p><ul>{''.join(f'<li><code>{html.escape(s)}</code></li>' for s in scopes) or '<li>(none)</li>'}</ul>
<div class="b"><a class="btn no" href="{html.escape(no)}">Deny</a><a class="btn ok" href="{html.escape(ok)}">Allow</a></div>""")
    return True


def take_code(form, challenge_fn=None):
    c = tp.S["codes"].pop(form.get("code", ""), None)
    if not c or c["expires"] < time.time() or c["redirect_uri"] != form.get("redirect_uri"):
        return None, "invalid_grant"
    if c.get("challenge") and challenge_fn and challenge_fn(form.get("code_verifier", "")) != c["challenge"]:
        return None, "invalid_grant"
    return c, None


def new_post(plat, account, title, text, media, pid=None, extra=None):
    pid = pid or "tpp_" + secrets.token_hex(6)
    tp.S["posts"][pid] = {"id": pid, "platform": plat, "account": account, "fields": {"title": title or "", "text": text or ""},
                          "media": media, "at": time.time(), "deleted": False, **(extra or {})}
    return pid


def post_page(h, pid):
    tp.handle(h, "GET", f"/testplatform/p/{pid}", {})
    return True


# ---------------------------------------------------------------- YouTube
def youtube(h, method, host, path, q):
    P = "youtube"
    if method == "GET" and host == "accounts" and path == "/o/oauth2/v2/auth":
        return consent(h, P, q)
    if host == "watch":
        return post_page(h, q.get("v", [""])[0])
    if method == "POST" and host == "oauth" and path == "/token":
        f = form_or_json(read_body(h, True)[2])
        if f.get("grant_type") == "authorization_code":
            c, err = take_code(f, lambda v: base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode())
            if err:
                return reply(h, 400, {"error": err, "error_description": "Bad Request"})
            t = tokens(P, c["account"]); t["scope"] = c["scope"]
            return reply(h, 200, t)
        if f.get("grant_type") == "refresh_token":
            r = tp.S["refresh"].get(f.get("refresh_token", ""))
            if not r or r["platform"] != P:
                return reply(h, 400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
            t = tokens(P, r["account"], with_refresh=False)
            return reply(h, 200, t)
        return reply(h, 400, {"error": "unsupported_grant_type"})
    if failed(h, P):            # the failure switch hits API calls, not signing in
        return True
    if host != "api":
        return reply(h, 404, {"error": {"code": 404, "message": "Not Found"}})
    if method == "PUT" and path == "/upload/youtube/v3/videos":
        sid = q.get("upload_id", [""])[0]
        sess = X["uploads"].get(sid)
        if not sess:
            read_body(h); return reply(h, 404, {"error": {"code": 404, "message": "Upload session not found"}})
        n, sha, _ = read_body(h)
        if n != sess["size"]:
            return reply(h, 400, {"error": {"code": 400, "message": f"Expected {sess['size']} bytes, got {n}", "errors": [{"reason": "badContent"}]}})
        vid = secrets.token_urlsafe(8)[:11]
        s = sess["meta"]
        new_post(P, ACCOUNT[P][1], s["snippet"].get("title"), s["snippet"].get("description"), {"bytes": n, "sha256": sha}, pid=vid,
                 extra={"tags": s["snippet"].get("tags") or [], "privacy": s["status"].get("privacyStatus")})
        X["uploads"].pop(sid, None)
        return reply(h, 201, {"kind": "youtube#video", "id": vid, "snippet": dict(s["snippet"], channelId=ACCOUNT[P][0]),
                              "status": dict(s["status"], uploadStatus="uploaded")})
    t = who(h, P)
    if not t:
        return True
    if method == "GET" and path == "/youtube/v3/channels":
        return reply(h, 200, {"kind": "youtube#channelListResponse", "items": [{"id": ACCOUNT[P][0], "snippet": {"title": ACCOUNT[P][1], "customUrl": "@studio-test"}}]})
    if method == "POST" and path == "/upload/youtube/v3/videos":
        if q.get("uploadType", [""])[0] != "resumable":
            return reply(h, 400, {"error": {"code": 400, "message": "Use uploadType=resumable", "errors": [{"reason": "badRequest"}]}})
        meta = json.loads(read_body(h, True)[2] or b"{}")
        title = (meta.get("snippet") or {}).get("title") or ""
        if not title or len(title) > 100 or re.search(r"[<>]", title):
            return reply(h, 400, {"error": {"code": 400, "message": "The video's title is missing or too long", "errors": [{"reason": "invalidTitle"}]}})
        if len(((meta.get("snippet") or {}).get("description") or "").encode()) > 5000:
            return reply(h, 400, {"error": {"code": 400, "message": "Description too long", "errors": [{"reason": "invalidDescription"}]}})
        sid = secrets.token_hex(8)
        X["uploads"][sid] = {"size": int(h.headers.get("X-Upload-Content-Length", 0) or 0), "meta": meta}
        return reply(h, 200, headers={"Location": f"https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id={sid}&part=snippet,status"})
    if method == "POST" and path == "/upload/youtube/v3/thumbnails/set":
        n, _, _ = read_body(h)
        post = tp.S["posts"].get(q.get("videoId", [""])[0])
        if not post:
            return reply(h, 404, {"error": {"code": 404, "message": "Video not found", "errors": [{"reason": "videoNotFound"}]}})
        post["thumb_bytes"] = n
        return reply(h, 200, {"kind": "youtube#thumbnailSetResponse", "items": [{"default": {"url": "https://i.ytimg.test/x.jpg"}}]})
    if method == "GET" and path == "/youtube/v3/videos":
        items = []
        for vid in q.get("id", [""])[0].split(","):
            p = tp.S["posts"].get(vid)
            if p and not p["deleted"]:
                v = views(p["at"])
                items.append({"id": vid, "statistics": {"viewCount": str(v), "likeCount": str(v // 14), "commentCount": str(v // 90), "favoriteCount": "0"}})
        return reply(h, 200, {"kind": "youtube#videoListResponse", "items": items})
    if method == "DELETE" and path == "/youtube/v3/videos":
        p = tp.S["posts"].get(q.get("id", [""])[0])
        if not p:
            return reply(h, 404, {"error": {"code": 404, "message": "Video not found", "errors": [{"reason": "videoNotFound"}]}})
        p["deleted"] = True
        return reply(h, 204)
    return reply(h, 404, {"error": {"code": 404, "message": "Not Found"}})


# ---------------------------------------------------------------- Facebook and Instagram (Graph API)
def multipart(raw, ctype):
    m = re.search(r"boundary=([^;]+)", ctype or "")
    if not m:
        return {}, {}
    fields, files = {}, {}
    for part in raw.split(b"--" + m.group(1).encode()):
        if b"\r\n\r\n" not in part:
            continue
        head, body = part.split(b"\r\n\r\n", 1)
        body = body[:-2] if body.endswith(b"\r\n") else body
        name = re.search(rb'name="([^"]+)"', head)
        if not name:
            continue
        if b"filename=" in head:
            files[name.group(1).decode()] = body
        else:
            fields[name.group(1).decode()] = body.decode(errors="replace")
    return fields, files


def meta(h, P, method, host, path, q):
    G = "/v26.0"
    if method == "GET" and host == "www" and path == f"{G}/dialog/oauth":
        return consent(h, P, q)
    if host in ("reel", "videos", "p"):
        return post_page(h, path.strip("/"))
    if host not in ("graph", "video", "rupload"):
        return reply(h, 404, {"error": {"message": "Unknown path", "code": 100}})
    if host == "graph" and path == f"{G}/oauth/access_token":
        if q.get("grant_type", [""])[0] == "fb_exchange_token":
            t = tp.S["tokens"].get(q.get("fb_exchange_token", [""])[0])
            if not t:
                return error(h, P, "invalid")
            out = tokens(P, t["account"], with_refresh=False); out["expires_in"] = 5183944
            return reply(h, 200, out)
        c, err = take_code({"code": q.get("code", [""])[0], "redirect_uri": q.get("redirect_uri", [""])[0]})
        if err:
            return reply(h, 400, {"error": {"message": "Invalid verification code format.", "type": "OAuthException", "code": 100}})
        out = tokens(P, c["account"], with_refresh=False); out["expires_in"] = 5000
        return reply(h, 200, out)
    if failed(h, P):
        return True
    if host == "rupload":
        hd = {"Authorization": h.headers.get("Authorization", "")}
        if not hd["Authorization"].startswith("OAuth "):
            read_body(h); return reply(h, 400, {"debug_info": {"type": "AuthError", "message": "Use Authorization: OAuth <token>"}})
        if not who(h, P):
            return True
        oid = path.rsplit("/", 1)[-1]
        o = X["objects"].get(oid)
        n, sha, _ = read_body(h)
        if not o:
            return reply(h, 400, {"debug_info": {"type": "ProcessingFailedError", "message": "No such upload"}})
        if str(n) != h.headers.get("file_size") or h.headers.get("offset") != "0":
            return reply(h, 400, {"debug_info": {"type": "ProcessingFailedError", "message": "file_size / offset don't match the body"}})
        o.update(bytes=n, sha256=sha, uploaded=time.time())
        return reply(h, 200, {"success": True, **({"message": "Upload successful."} if P == "instagram" else {})})
    t = who(h, P)
    if not t:
        return True
    parts = [x for x in path[len(G):].split("/") if x]
    if method == "GET" and parts == ["me", "accounts"]:
        page = {"id": "pg_1001", "name": "Your Brand (test)", "category": "Brand", "tasks": ["ANALYZE", "ADVERTISE", "MODERATE", "CREATE_CONTENT", "MANAGE"],
                "access_token": tokens(P, {"id": "pg_1001", "name": "Your Brand (test)"}, with_refresh=False)["access_token"],
                "instagram_business_account": {"id": "igu_2001", "username": "studio.test"}}
        return reply(h, 200, {"data": [page], "paging": {"cursors": {"before": "a", "after": "b"}}})
    raw = b""
    if method == "POST":
        n, _, raw = read_body(h, True)
    form = {}
    if method == "POST" and raw and not (h.headers.get("Content-Type") or "").startswith("multipart/"):
        form = form_or_json(raw)
    # ---- Facebook Reels
    if P == "facebook" and len(parts) == 2 and parts[1] == "video_reels" and method == "POST":
        if form.get("upload_phase") == "start":
            vid = "fbv_" + secrets.token_hex(5)
            X["objects"][vid] = {"kind": "reel", "page": parts[0], "state": "uploading"}
            return reply(h, 200, {"video_id": vid, "upload_url": f"https://rupload.facebook.com/video-upload/v26.0/{vid}"})
        if form.get("upload_phase") == "finish":
            o = X["objects"].get(form.get("video_id", ""))
            if not o or not o.get("bytes"):
                return error(h, P, "server", "The video wasn't uploaded")
            if form.get("video_state") != "PUBLISHED":
                return reply(h, 400, {"error": {"message": "Test platform: use video_state=PUBLISHED", "code": 100}})
            o.update(state="finished", finished=time.time(), description=form.get("description", ""))
            new_post(P, ACCOUNT[P][1], "Reel", o["description"], {"bytes": o["bytes"], "sha256": o["sha256"]}, pid=form["video_id"])
            return reply(h, 200, {"success": True})
        return reply(h, 400, {"error": {"message": "upload_phase must be start or finish", "code": 100}})
    if P == "facebook" and host == "video" and len(parts) == 2 and parts[1] == "videos" and method == "POST":
        fields, files = multipart(raw, h.headers.get("Content-Type"))
        if "source" not in files:
            return reply(h, 400, {"error": {"message": "No video file", "code": 100}})
        src = files["source"]
        vid = new_post(P, ACCOUNT[P][1], fields.get("title"), fields.get("description"), {"bytes": len(src), "sha256": hashlib.sha256(src).hexdigest()},
                       pid="fbv_" + secrets.token_hex(5), extra={"thumb_bytes": len(files.get("thumb", b""))})
        return reply(h, 200, {"id": vid})
    # ---- Instagram
    if P == "instagram" and len(parts) == 2 and parts[1] == "content_publishing_limit":
        used = sum(1 for x in tp.S["posts"].values() if x["platform"] == P and x["at"] > time.time() - 86400)
        return reply(h, 200, {"data": [{"quota_usage": used, "config": {"quota_total": 50, "quota_duration": 86400}}]})
    if P == "instagram" and len(parts) == 2 and parts[1] == "media" and method == "POST":
        if form.get("media_type") != "REELS" or form.get("upload_type") != "resumable":
            return reply(h, 400, {"error": {"message": "Test platform: expected media_type=REELS and upload_type=resumable", "code": 100}})
        cap = form.get("caption", "")
        if len(cap) > 2200 or len(re.findall(r"#\w", cap)) > 30:
            return reply(h, 400, {"error": {"message": "The caption is too long or has more than 30 hashtags", "code": 100, "error_subcode": 2207028}})
        cid = "igc_" + secrets.token_hex(5)
        X["objects"][cid] = {"kind": "container", "caption": cap, "state": "new"}
        return reply(h, 200, {"id": cid, "uri": f"https://rupload.facebook.com/ig-api-upload/v26.0/{cid}"})
    if P == "instagram" and len(parts) == 2 and parts[1] == "media_publish" and method == "POST":
        o = X["objects"].get(form.get("creation_id", ""))
        if not o or not o.get("uploaded") or time.time() - o["uploaded"] < 1.5:
            return reply(h, 400, {"error": {"message": "Media ID is not available", "code": 9007, "error_subcode": 2207027}})
        if o.get("published"):
            return reply(h, 400, {"error": {"message": "Already published", "code": 100}})
        mid = new_post(P, ACCOUNT[P][1], "", o["caption"], {"bytes": o["bytes"], "sha256": o["sha256"]}, pid="igm_" + secrets.token_hex(5))
        o["published"] = mid
        X["objects"][mid] = {"kind": "media", "comments": []}
        return reply(h, 200, {"id": mid})
    if P == "instagram" and len(parts) == 2 and parts[1] == "comments" and method == "POST":
        o = X["objects"].get(parts[0])
        if not o:
            return reply(h, 400, {"error": {"message": "Unknown media", "code": 100}})
        o["comments"].append(form.get("message", ""))
        tp.S["posts"][parts[0]]["first_comment"] = form.get("message", "")
        return reply(h, 200, {"id": "igcm_" + secrets.token_hex(5)})
    # ---- reading, results and deleting (both)
    if len(parts) == 2 and parts[1] in ("video_insights", "insights") and method == "GET":
        p = tp.S["posts"].get(parts[0])
        if not p:
            return reply(h, 400, {"error": {"message": "Unsupported get request", "code": 100}})
        v = views(p["at"])
        known = {"blue_reels_play_count": v, "total_video_views": v, "post_video_avg_time_watched": 8400,
                 "post_video_likes_by_reaction_type": {"REACTION_LIKE": v // 16, "REACTION_LOVE": v // 60},
                 "post_video_social_actions": {"COMMENT": v // 90, "SHARE": v // 120},
                 "views": v, "reach": int(v * 0.8), "likes": v // 14, "comments": v // 90, "shares": v // 120, "saved": v // 70,
                 "ig_reels_video_view_total_time": v * 9000}
        want = q.get("metric", [""])[0].split(",")
        bad = [m for m in want if m not in known]
        if bad:
            return reply(h, 400, {"error": {"message": f"(#100) The value must be a valid insights metric: {bad[0]}", "code": 100}})
        return reply(h, 200, {"data": [{"name": m, "period": "lifetime", "values": [{"value": known[m]}], "id": f"{parts[0]}/insights/{m}/lifetime"} for m in want]})
    if len(parts) == 1 and method == "GET":
        oid = parts[0]
        o, p = X["objects"].get(oid), tp.S["posts"].get(oid)
        fields = q.get("fields", [""])[0]
        if o and o.get("kind") == "reel" and "status" in fields:
            pub = "published" if o.get("finished") and time.time() - o["finished"] > 1.5 else "not_started"
            return reply(h, 200, {"id": oid, "status": {"video_status": "ready" if pub == "published" else "processing",
                                                         "uploading_phase": {"status": "complete", "bytes_transfered": o.get("bytes", 0)},
                                                         "processing_phase": {"status": "complete" if pub == "published" else "in_progress"},
                                                         "publishing_phase": {"status": "complete" if pub == "published" else "not_started", "publish_status": pub}}})
        if o and o.get("kind") == "container":
            code = "PUBLISHED" if o.get("published") else "FINISHED" if o.get("uploaded") and time.time() - o["uploaded"] > 1.5 else "IN_PROGRESS"
            return reply(h, 200, {"id": oid, "status_code": code, "status": code.title()})
        if p and "permalink" in fields:
            return reply(h, 200, {"id": oid, "permalink": f"{base(h)}/instagram/p/{oid}"})
        return reply(h, 400, {"error": {"message": f"Unsupported get request. Object with ID '{oid}' does not exist", "code": 100, "error_subcode": 33}})
    if len(parts) == 1 and method == "DELETE":
        p = tp.S["posts"].get(parts[0])
        if not p:
            return reply(h, 400, {"error": {"message": "Unsupported delete request", "code": 100}})
        p["deleted"] = True
        return reply(h, 200, {"success": True})
    return reply(h, 400, {"error": {"message": f"Unknown path components: {path}", "code": 2500}})


# ---------------------------------------------------------------- TikTok
def tiktok(h, method, host, path, q):
    P = "tiktok"
    ok = {"code": "ok", "message": "", "log_id": secrets.token_hex(8)}
    if method == "GET" and host == "www" and path == "/v2/auth/authorize/":
        return consent(h, P, q, id_key="client_key")
    if host == "video":
        return post_page(h, path.strip("/"))
    if method == "PUT" and host == "upload":
        if failed(h, P):
            return True
        up = X["uploads"].get(path.strip("/"))
        n, sha, data = read_body(h, True)
        if not up:
            return reply(h, 404, {"error": {"code": "invalid_publish_id", "message": "No such upload"}})
        m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", h.headers.get("Content-Range", ""))
        if not m or int(m.group(1)) != up["got"] or int(m.group(3)) != up["size"] or int(m.group(2)) - int(m.group(1)) + 1 != n:
            return reply(h, 416, headers={"Content-Range": f"bytes 0-{up['got'] - 1}/{up['size']}"})
        up["sha"].update(data); up["got"] += n
        if up["got"] < up["size"]:
            return reply(h, 206)
        up["done"] = time.time()
        return reply(h, 201)
    if host != "api":
        return reply(h, 404, {"error": {"code": "not_found", "message": "Not found"}})
    if method == "POST" and path == "/v2/oauth/token/":
        f = form_or_json(read_body(h, True)[2])
        if f.get("grant_type") == "authorization_code":
            c, err = take_code(f, lambda v: hashlib.sha256(v.encode()).hexdigest())
            if err:
                return reply(h, 400, {"error": "invalid_grant", "error_description": "Authorization code is expired or invalid.", "log_id": "x"})
            t = tokens(P, c["account"])
        elif f.get("grant_type") == "refresh_token":
            r = tp.S["refresh"].get(f.get("refresh_token", ""))
            if not r:
                return reply(h, 400, {"error": "invalid_grant", "error_description": "Refresh token is invalid or expired.", "log_id": "x"})
            t = tokens(P, r["account"])
        else:
            return reply(h, 400, {"error": "invalid_request", "error_description": "Bad grant_type", "log_id": "x"})
        t.update(open_id=ACCOUNT[P][0], refresh_expires_in=31536000, scope="user.info.basic,video.publish,video.upload,video.list")
        return reply(h, 200, t)
    if failed(h, P):
        return True
    t = who(h, P)
    if not t:
        return True
    if method == "GET" and path == "/v2/user/info/":
        return reply(h, 200, {"data": {"user": {"open_id": ACCOUNT[P][0], "display_name": ACCOUNT[P][1], "avatar_url": ""}}, "error": ok})
    body = json.loads(read_body(h, True)[2] or b"{}") if method == "POST" else {}
    if path == "/v2/post/publish/creator_info/query/":
        return reply(h, 200, {"data": {"creator_username": "studio.test", "creator_nickname": ACCOUNT[P][1],
                                       "privacy_level_options": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
                                       "comment_disabled": False, "duet_disabled": False, "stitch_disabled": True, "max_video_post_duration_sec": 600},
                              "error": ok})
    if path in ("/v2/post/publish/video/init/", "/v2/post/publish/inbox/video/init/"):
        src = body.get("source_info") or {}
        size, chunk, count = int(src.get("video_size", 0)), int(src.get("chunk_size", 0)), int(src.get("total_chunk_count", 0))
        good = src.get("source") == "FILE_UPLOAD" and size > 0 and (
            (size <= 64_000_000 and chunk == size and count == 1) or (5_000_000 <= chunk <= 64_000_000 and count == size // chunk))
        if not good:
            return reply(h, 400, {"error": {"code": "invalid_param", "message": "source_info: chunk rules not met", "log_id": "x"}})
        direct = "inbox" not in path
        info = body.get("post_info") or {}
        if direct and info.get("privacy_level") not in ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"):
            return reply(h, 403, {"error": {"code": "privacy_level_option_mismatch", "message": "privacy_level", "log_id": "x"}})
        if direct and len((info.get("title") or "").encode("utf-16-le")) // 2 > 2200:
            return reply(h, 400, {"error": {"code": "invalid_param", "message": "title too long", "log_id": "x"}})
        pub = "v_pub_file~v2-1." + str(secrets.randbelow(10 ** 12))
        X["uploads"][pub] = {"size": size, "got": 0, "sha": hashlib.sha256(), "direct": direct, "title": info.get("title", ""), "done": None}
        return reply(h, 200, {"data": {"publish_id": pub, "upload_url": f"https://open-upload.tiktokapis.com/video/?upload_id={quote(pub)}"}, "error": ok})
    if path == "/v2/post/publish/status/fetch/":
        up = X["uploads"].get(body.get("publish_id", ""))
        if not up:
            return reply(h, 400, {"error": {"code": "invalid_publish_id", "message": "unknown publish_id", "log_id": "x"}})
        if not up["done"] or time.time() - up["done"] < 1.5:
            return reply(h, 200, {"data": {"status": "PROCESSING_UPLOAD", "uploaded_bytes": up["got"]}, "error": ok})
        if not up["direct"]:
            if not up.get("post"):
                up["post"] = new_post(P, ACCOUNT[P][1], "", "(waiting in the TikTok inbox: someone taps Post in the app)",
                                      {"bytes": up["got"], "sha256": up["sha"].hexdigest()})
            return reply(h, 200, {"data": {"status": "SEND_TO_USER_INBOX", "uploaded_bytes": up["got"]}, "error": ok})
        if not up.get("post"):
            up["post"] = new_post(P, ACCOUNT[P][1], "", up["title"], {"bytes": up["got"], "sha256": up["sha"].hexdigest()},
                                  pid=str(7300000000000000000 + secrets.randbelow(10 ** 15)))
        return reply(h, 200, {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [int(up["post"])], "uploaded_bytes": up["got"]}, "error": ok})
    if path == "/v2/video/query/":
        vids = []
        for vid in (body.get("filters") or {}).get("video_ids") or []:
            p = tp.S["posts"].get(str(vid))
            if p and not p["deleted"]:
                v = views(p["at"])
                vids.append({"id": vid, "view_count": v, "like_count": v // 14, "comment_count": v // 90, "share_count": v // 120})
        return reply(h, 200, {"data": {"videos": vids}, "error": ok})
    return reply(h, 404, {"error": {"code": "not_found", "message": path, "log_id": "x"}})


# ---------------------------------------------------------------- LinkedIn
def linkedin(h, method, host, path, q):
    P = "linkedin"
    if method == "GET" and host == "www" and path == "/oauth/v2/authorization":
        return consent(h, P, q)
    if host == "feed":
        return post_page(h, unquote(path.rsplit("/", 1)[-1]))
    if method == "POST" and host == "www" and path == "/oauth/v2/accessToken":
        f = form_or_json(read_body(h, True)[2])
        c, err = take_code(f)
        if err:
            return reply(h, 400, {"error": "invalid_request", "error_description": "Unable to retrieve access token: appid/redirect uri/code verifier does not match authorization code"})
        t = tokens(P, c["account"], with_refresh=False); t["scope"] = c["scope"].replace(" ", ",")
        tp.S["tokens"][t["access_token"]]["scope"] = c["scope"]
        return reply(h, 200, t)
    if failed(h, P):
        return True
    if method == "PUT" and host == "dms":
        oid, part = path.strip("/").split("/")
        o = X["objects"].get(oid)
        n, sha, _ = read_body(h)
        if not o:
            return reply(h, 404, {"message": "Upload not found", "status": 404})
        if part == "thumb":
            o["thumb_bytes"] = n
            return reply(h, 201)
        ins = o["parts"][int(part)]
        if n != ins["lastByte"] - ins["firstByte"] + 1:
            return reply(h, 400, {"message": "Wrong number of bytes for this part", "status": 400})
        o["etags"][int(part)] = f"/ambry-video/signedId/{secrets.token_hex(6)}.bin"
        o["bytes"] = o.get("bytes", 0) + n
        return reply(h, 200, headers={"ETag": o["etags"][int(part)]})
    if host != "api":
        return reply(h, 404, {"message": "Not found", "status": 404})
    t = who(h, P)
    if not t:
        return True
    if path == "/v2/me":
        return reply(h, 200, {"id": "tpPerson01", "localizedFirstName": "Test", "localizedLastName": "Admin", "vanityName": "testadmin"})
    if path == "/v2/userinfo":
        return reply(h, 200, {"sub": "tpPerson01", "name": "Test Admin", "given_name": "Test", "family_name": "Admin"})
    if path.startswith("/rest/"):
        if not h.headers.get("LinkedIn-Version"):
            read_body(h); return reply(h, 400, {"status": 400, "code": "VERSION_MISSING", "message": "A version must be present"})
        if h.headers.get("X-Restli-Protocol-Version") != "2.0.0":
            read_body(h); return reply(h, 400, {"status": 400, "message": "Restli protocol 2.0.0 required"})
    body = {}
    if method == "POST":
        body = json.loads(read_body(h, True)[2] or b"{}")
    if path == "/rest/organizationAcls":
        if "rw_organization_admin" not in tp.S["tokens"][h.headers["Authorization"].split()[-1]].get("scope", ""):
            return reply(h, 403, {"status": 403, "serviceErrorCode": 100, "code": "ACCESS_DENIED", "message": "Not enough permissions to access: organizationAcls"})
        return reply(h, 200, {"elements": [{"role": "ADMINISTRATOR", "organization": ACCOUNT[P][0], "roleAssignee": "urn:li:person:tpPerson01", "state": "APPROVED"}],
                              "paging": {"count": 10, "start": 0, "links": []}})
    if path.startswith("/rest/organizations/"):
        return reply(h, 200, {"id": int(path.rsplit("/", 1)[-1]), "localizedName": ACCOUNT[P][1], "vanityName": "studio-test"})
    if path == "/rest/videos" and q.get("action", [""])[0] == "initializeUpload":
        r = body.get("initializeUploadRequest") or {}
        size = int(r.get("fileSizeBytes", 0))
        if not r.get("owner", "").startswith(("urn:li:organization:", "urn:li:person:")) or size < 75_000:
            return reply(h, 400, {"status": 400, "code": "INVALID_VALUE_FOR_FIELD", "message": "owner or fileSizeBytes"})
        oid = "C5505AQ" + secrets.token_hex(6)
        step, parts = 4_194_304, []
        for i, first in enumerate(range(0, size, step)):
            parts.append({"uploadUrl": f"https://www.linkedin.com/dms-uploads/{oid}/{i}", "firstByte": first, "lastByte": min(size, first + step) - 1})
        X["objects"][oid] = {"kind": "livideo", "owner": r["owner"], "size": size, "parts": parts, "etags": [None] * len(parts), "state": "WAITING_UPLOAD"}
        return reply(h, 200, {"value": {"uploadUrlsExpireAt": int((time.time() + 86400) * 1000), "video": f"urn:li:video:{oid}", "uploadInstructions": parts,
                                        "uploadToken": "", "thumbnailUploadUrl": f"https://www.linkedin.com/dms-uploads/{oid}/thumb" if r.get("uploadThumbnail") else None,
                                        "captionsUploadUrl": None}})
    if path == "/rest/videos" and q.get("action", [""])[0] == "finalizeUpload":
        r = body.get("finalizeUploadRequest") or {}
        o = X["objects"].get(r.get("video", "").rsplit(":", 1)[-1])
        if not o or r.get("uploadedPartIds") != o["etags"] or None in o["etags"]:
            return reply(h, 400, {"status": 400, "code": "INVALID_VALUE_FOR_FIELD", "message": "uploadedPartIds don't match the uploaded parts"})
        o.update(state="PROCESSING", finalized=time.time())
        return reply(h, 200, {})
    if method == "GET" and path.startswith("/rest/videos/"):
        urn = unquote(path[len("/rest/videos/"):])
        o = X["objects"].get(urn.rsplit(":", 1)[-1])
        if not o:
            return reply(h, 404, {"status": 404, "message": "Video not found"})
        if o["state"] == "PROCESSING" and time.time() - o["finalized"] > 1.5:
            o["state"] = "AVAILABLE"
        return reply(h, 200, {"id": urn, "owner": o["owner"], "status": o["state"]})
    if method == "POST" and path == "/rest/posts":
        media = ((body.get("content") or {}).get("media") or {}).get("id", "")
        o = X["objects"].get(media.rsplit(":", 1)[-1])
        if not o or o["state"] != "AVAILABLE":
            return reply(h, 400, {"status": 400, "code": "MEDIA_ASSET_WAITING_UPLOAD", "message": "The video isn't ready"})
        if body.get("author") != o["owner"] or body.get("lifecycleState") != "PUBLISHED":
            return reply(h, 400, {"status": 400, "code": "INVALID_VALUE_FOR_FIELD", "message": "author must own the video; lifecycleState must be PUBLISHED"})
        com = body.get("commentary", "")
        if len(com) > 3000 or re.search(r"(?<!\\)[()@\[\]{}<>*_~|]", com):
            return reply(h, 400, {"status": 400, "code": "INVALID_VALUE_FOR_FIELD", "message": "commentary: too long or reserved characters not escaped"})
        urn = f"urn:li:ugcPost:{7300000000000000000 + secrets.randbelow(10 ** 15)}"
        new_post(P, ACCOUNT[P][1], (body["content"]["media"].get("title") or ""), re.sub(r"\\(.)", r"\1", com),
                 {"bytes": o.get("bytes", 0), "sha256": ""}, pid=urn)
        return reply(h, 201, headers={"x-restli-id": urn})
    if method == "GET" and path.startswith("/rest/socialActions/"):
        p = tp.S["posts"].get(unquote(path[len("/rest/socialActions/"):]))
        if not p:
            return reply(h, 404, {"status": 404, "message": "Not found"})
        v = views(p["at"])
        return reply(h, 200, {"likesSummary": {"totalLikes": v // 14}, "commentsSummary": {"aggregatedTotalComments": v // 90}, "target": p["id"]})
    if method == "GET" and path == "/rest/videoAnalytics":
        p = tp.S["posts"].get(q.get("entity", [""])[0])
        v = views(p["at"]) if p else 0
        val = v if q.get("type", [""])[0] == "VIDEO_VIEW" else v * 9000
        return reply(h, 200, {"elements": [{"entity": q.get("entity", [""])[0], "statisticsType": q.get("type", [""])[0], "value": val}] if p else [],
                              "paging": {"count": 10, "start": 0, "links": [], "total": 1 if p else 0}})
    if method == "DELETE" and path.startswith("/rest/posts/"):
        p = tp.S["posts"].get(unquote(path[len("/rest/posts/"):]))
        if p:
            p["deleted"] = True
        return reply(h, 204)
    return reply(h, 404, {"status": 404, "message": f"Not found: {path}"})


# ---------------------------------------------------------------- dispatch
def handle(h, method, plat, rest, q):
    """rest: "/<host>/<path…>" under /testplatform/<plat>."""
    host, _, path = rest.lstrip("/").partition("/")
    path = "/" + path
    if plat == "tiktok" and host == "upload":
        path = "/" + q.get("upload_id", [""])[0]
    h.q = q
    if plat == "youtube":
        return youtube(h, method, host, path, q)
    if plat in ("facebook", "instagram"):
        return meta(h, plat, method, host, path, q)
    if plat == "tiktok":
        return tiktok(h, method, host, path, q)
    if plat == "linkedin":
        return linkedin(h, method, host, path, q)
    return False
