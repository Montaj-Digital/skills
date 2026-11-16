"""The real platform connections (ROADMAP phase 9.5, batch a): YouTube, Facebook, Instagram, TikTok and LinkedIn.

Each class talks to the platform's own API with Python's standard library (connect.request). With **Use the test
platform** on, the same class talks to that platform's stand-in inside Studio AI (testplatform.py), which answers in the
platform's shapes, so every step here runs without real accounts. The developer adds the app keys (Social settings →
App keys) and signs in once per platform; SOCIAL.md says what each platform needs.

Every connector posts at the scheduled time (Studio AI's scheduler decides when), never with the platform's own
scheduling, so all ten behave the same way and a moved or cancelled post never needs undoing on the platform.

tokens (kept in the token store): {"access", "refresh", "expires_at", "account": {"id", "name"}, …platform extras}
results(): {"views", "likes", "comments", "shares", "watch_time_s"}; a number the platform doesn't give is None.
Python 3.9 standard library only.
"""
import base64, hashlib, json, secrets, time
from pathlib import Path
from urllib.parse import quote, urlencode

import connect
from connect import ConnectError, Expired, request, wait_for


def _probe(video):
    """{dur, w, h} of a video (ffprobe); zeros when it can't be read."""
    import subprocess, osutil
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json",
                              str(video)], capture_output=True, text=True, env=osutil.tool_env(), timeout=60).stdout
        d = json.loads(out or "{}"); st = (d.get("streams") or [{}])[0]
        return {"dur": float(d["format"]["duration"]), "w": st.get("width"), "h": st.get("height")}
    except (OSError, KeyError, ValueError, subprocess.SubprocessError):
        return {"dur": 0, "w": None, "h": None}


def _account_wanted(platform):
    """The account name typed in Social settings (to pick the right Page / organisation when there are several)."""
    try:
        import social
        return (social.load()["channels"].get(platform) or {}).get("account", "").strip().lstrip("@").lower()
    except Exception:
        return ""


def _pick(items, platform, name_of):
    want = _account_wanted(platform)
    for it in items:
        if want and want in (name_of(it) or "").lower():
            return it
    return items[0] if items else None


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class _Multipart:
    """A multipart/form-data body streamed from fields and files (a file is (name, path, content type))."""
    def __init__(self, fields, files):
        self.boundary = "studio" + secrets.token_hex(12)
        self.parts = []
        for k, v in fields.items():
            self.parts.append(f'--{self.boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for k, path, ctype in files:
            self.parts.append(f'--{self.boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{Path(path).name}"\r\n'
                              f'Content-Type: {ctype}\r\n\r\n'.encode())
            self.parts.append(Path(path)); self.parts.append(b"\r\n")
        self.parts.append(f"--{self.boundary}--\r\n".encode())
        self.length = sum(len(p) if isinstance(p, bytes) else p.stat().st_size for p in self.parts)
        self._i, self._fh = 0, None

    @property
    def content_type(self):
        return f"multipart/form-data; boundary={self.boundary}"

    def read(self, size=1 << 20):
        while self._i < len(self.parts):
            p = self.parts[self._i]
            if isinstance(p, bytes):
                self._i += 1
                return p
            if self._fh is None:
                self._fh = open(p, "rb")
            b = self._fh.read(size if size and size > 0 else 1 << 20)
            if b:
                return b
            self._fh.close(); self._fh = None; self._i += 1
        return b""


# ================================================================ YouTube (YouTube Data API v3)
class YouTube(connect.Connector):
    """Google sign-in (offline access + PKCE), resumable upload, the cover as the custom thumbnail."""
    HOSTS = {"accounts": "https://accounts.google.com", "oauth": "https://oauth2.googleapis.com",
             "api": "https://www.googleapis.com", "analytics": "https://youtubeanalytics.googleapis.com"}
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl",
              "https://www.googleapis.com/auth/yt-analytics.readonly"]

    def check(self, status, body, what):
        if status < 400:
            return body
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            reason = ((err.get("errors") or [{}])[0]).get("reason") or err.get("status") or ""
            msg = err.get("message") or reason
            if status == 401 and reason != "youtubeSignupRequired":
                raise Expired(msg)
            hint = {"quotaExceeded": " (YouTube's daily limit for the app; it resets at midnight Pacific time)",
                    "uploadLimitExceeded": " (the channel's daily upload limit)",
                    "youtubeSignupRequired": " (this Google account has no YouTube channel)",
                    "accessNotConfigured": " (turn on the YouTube Data API in the Google Cloud project)"}.get(reason, "")
            raise ConnectError(f"{what}: {msg}{hint} ({status})")
        if isinstance(err, str):           # the sign-in server's shape
            if err == "invalid_grant":
                raise ConnectError("YouTube's sign-in has expired or was removed: connect YouTube again in Social settings")
            raise ConnectError(f"{what}: {body.get('error_description') or err} ({status})")
        raise ConnectError(f"{what}: {str(body)[:200]} ({status})")

    def authorize_url(self, app, state, redirect, verifier=None):
        q = {"client_id": app["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": " ".join(self.SCOPES),
             "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state}
        if verifier:
            q.update(code_challenge=_challenge(verifier), code_challenge_method="S256")
        return self.page_url("accounts", "/o/oauth2/v2/auth?" + urlencode(q))

    def _tokens(self, b, old=None):
        return {"access": b["access_token"], "refresh": b.get("refresh_token") or (old or {}).get("refresh"),
                "expires_at": time.time() + int(b.get("expires_in", 3599)), "account": (old or {}).get("account")}

    def exchange(self, app, code, redirect, verifier=None):
        form = {"code": code, "client_id": app["client_id"], "client_secret": app.get("client_secret", ""), "redirect_uri": redirect,
                "grant_type": "authorization_code"}
        if verifier:
            form["code_verifier"] = verifier
        t = self._tokens(self.check(*request("POST", self.url("oauth", "/token"), form=form), "Signing in to YouTube"))
        if not t["refresh"]:
            raise ConnectError("Google didn't give a lasting sign-in: remove Studio AI's access in the Google account, then connect again")
        s, b = request("GET", self.url("api", "/youtube/v3/channels?part=snippet&mine=true"), headers=self._auth(t))
        items = self.check(s, b, "Finding the YouTube channel").get("items") or []
        if not items:
            raise ConnectError("This Google account has no YouTube channel: sign in with the account (or Brand Account) that owns your brand's channel")
        ch = items[0]
        t["account"] = {"id": ch["id"], "name": ch["snippet"]["title"]}
        return t

    def refresh(self, app, tokens):
        form = {"client_id": app["client_id"], "client_secret": app.get("client_secret", ""), "refresh_token": tokens.get("refresh", ""),
                "grant_type": "refresh_token"}
        return self._tokens(self.check(*request("POST", self.url("oauth", "/token"), form=form), "Refreshing the YouTube sign-in"), tokens)

    @staticmethod
    def _auth(tokens):
        return {"Authorization": f"Bearer {tokens['access']}"}

    @staticmethod
    def _tags(tags):
        out, total = [], 0
        for t in tags or []:
            t = str(t).lstrip("#").replace("<", "").replace(">", "").strip()
            cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)
            if t and total + cost <= 500:
                out.append(t); total += cost
        return out

    @staticmethod
    def _bytes(text, n):
        b = text.encode()[:n]
        return b.decode(errors="ignore")

    def publish(self, app, tokens, post, video, cover):
        f = post.get("fields") or {}
        title = (f.get("title") or post["video"].get("name") or "Video").replace("<", "").replace(">", "")[:100]
        meta = {"snippet": {"title": title, "description": self._bytes((f.get("text") or "").replace("<", "").replace(">", ""), 5000),
                            "tags": self._tags(f.get("tags")), "categoryId": "22"},
                "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "embeddable": True, "license": "youtube"}}
        size = Path(video).stat().st_size
        s, b, h = request("POST", self.url("api", "/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"), json_body=meta,
                          headers={**self._auth(tokens), "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"}, full=True)
        self.check(s, b, "Starting the YouTube upload")
        session = h.get("location")
        if not session:
            raise ConnectError("Starting the YouTube upload: YouTube gave no upload address")
        session = self.follow(session)
        s, b = request("PUT", session, file=video, headers={**self._auth(tokens), "Content-Type": "video/mp4"}, timeout=3600)
        vid = self.check(s, b, "Uploading the video to YouTube")["id"]
        if cover:
            try:              # needs a phone-verified channel; the video is posted either way
                s, b = request("POST", self.url("api", f"/upload/youtube/v3/thumbnails/set?videoId={vid}"), file=cover,
                               headers={**self._auth(tokens), "Content-Type": "image/jpeg"})
                self.check(s, b, "Setting the thumbnail")
            except ConnectError as e:
                post.setdefault("notes", []).append(f"YouTube: the cover wasn't set ({e})")
        short = post["video"].get("format") == "reel"
        link = (f"{connect.public_url()}/testplatform/youtube/watch?v={vid}" if self.test else
                f"https://www.youtube.com/shorts/{vid}" if short else f"https://www.youtube.com/watch?v={vid}")
        return {"id": vid, "link": link}

    def results(self, app, tokens, remote_id):
        s, b = request("GET", self.url("api", f"/youtube/v3/videos?part=statistics&id={quote(remote_id)}"), headers=self._auth(tokens))
        items = self.check(s, b, "Reading YouTube's numbers").get("items") or []
        st = (items[0] if items else {}).get("statistics") or {}
        num = lambda k: int(st[k]) if st.get(k) is not None else None
        return {"views": num("viewCount"), "likes": num("likeCount"), "comments": num("commentCount"), "shares": None, "watch_time_s": None}

    def delete(self, app, tokens, remote_id):
        s, b = request("DELETE", self.url("api", f"/youtube/v3/videos?id={quote(remote_id)}"), headers=self._auth(tokens))
        self.check(s, b, "Deleting the YouTube video")
        return {"ok": True}


# ================================================================ Facebook and Instagram (Meta Graph API)
GRAPH = "v26.0"


class Meta(connect.Connector):
    """Facebook Login for a Page; Instagram uses the professional account linked to that Page. The Page's token
    doesn't expire (it ends only if someone's password or Page role changes), so there is nothing to refresh."""
    HOSTS = {"www": "https://www.facebook.com", "graph": "https://graph.facebook.com", "video": "https://graph-video.facebook.com",
             "rupload": "https://rupload.facebook.com"}
    SCOPES = []

    def check(self, status, body, what):
        err = body.get("error") if isinstance(body, dict) else None
        if status < 400 and not err:
            return body
        if isinstance(err, dict):
            code, msg = err.get("code"), err.get("error_user_msg") or err.get("message") or "error"
            if code in (190, 102):
                raise ConnectError(f"{what}: the {self.NAME} sign-in is no longer valid ({msg}): connect {self.NAME} again in Social settings")
            if code in (10, 200, 492) or (isinstance(code, int) and 200 <= code < 300):
                raise ConnectError(f"{what}: permission missing ({msg}): connect again and allow every permission, and check the person has a role on the Page")
            if code in (4, 17, 32, 613, 80001, 80002, 341):
                raise ConnectError(f"{what}: {self.NAME} asked us to slow down ({msg})")
            raise ConnectError(f"{what}: {msg} (code {code})")
        raise ConnectError(f"{what}: {str(body)[:200]} ({status})")

    def g(self, path, host="graph"):
        return self.url(host, f"/{GRAPH}{path}")

    def authorize_url(self, app, state, redirect, verifier=None):
        q = {"client_id": app["client_id"], "redirect_uri": redirect, "state": state, "response_type": "code", "scope": ",".join(self.SCOPES)}
        return self.page_url("www", f"/{GRAPH}/dialog/oauth?" + urlencode(q))

    def _user_token(self, app, code, redirect):
        s, b = request("GET", self.g("/oauth/access_token?" + urlencode({"client_id": app["client_id"], "redirect_uri": redirect,
                                                                          "client_secret": app.get("client_secret", ""), "code": code})))
        short = self.check(s, b, f"Signing in to {self.NAME}")["access_token"]
        s, b = request("GET", self.g("/oauth/access_token?" + urlencode({"grant_type": "fb_exchange_token", "client_id": app["client_id"],
                                                                          "client_secret": app.get("client_secret", ""), "fb_exchange_token": short})))
        return self.check(s, b, f"Signing in to {self.NAME}")["access_token"]

    def _pages(self, user_token):
        s, b = request("GET", self.g("/me/accounts?fields=id,name,access_token,tasks,instagram_business_account{id,username}"),
                       headers={"Authorization": f"Bearer {user_token}"})
        return self.check(s, b, "Finding the Facebook Pages").get("data") or []

    def refresh(self, app, tokens):
        return tokens

    @staticmethod
    def _auth(tokens):
        return {"Authorization": f"Bearer {tokens['access']}"}


class Facebook(Meta):
    NAME = "Facebook"
    SCOPES = ["pages_show_list", "pages_read_engagement", "pages_manage_posts", "pages_manage_engagement", "read_insights", "business_management"]

    def exchange(self, app, code, redirect, verifier=None):
        pages = self._pages(self._user_token(app, code, redirect))
        if not pages:
            raise ConnectError("No Facebook Page found: sign in as someone who manages your brand's Page, and tick it when Facebook asks which Pages")
        p = _pick(pages, "facebook", lambda x: x.get("name"))
        if "CREATE_CONTENT" not in (p.get("tasks") or ["CREATE_CONTENT"]):
            raise ConnectError(f"You can't post on the Page {p['name']}: ask its admin for full or content access")
        return {"access": p["access_token"], "refresh": None, "expires_at": None, "account": {"id": p["id"], "name": p["name"]},
                "page_id": p["id"], "kind": {}}

    def publish(self, app, tokens, post, video, cover):
        info = _probe(video)
        tall = bool(info.get("w") and info.get("h") and info["h"] > info["w"] * 1.5)
        if tall and 3 <= info["dur"] <= 90:
            return self._reel(tokens, post, video)
        return self._video(tokens, post, video, cover)

    def _reel(self, tokens, post, video):
        page = tokens["page_id"]
        s, b = request("POST", self.g(f"/{page}/video_reels"), json_body={"upload_phase": "start"}, headers=self._auth(tokens))
        vid = self.check(s, b, "Starting the Facebook Reel")["video_id"]
        size = Path(video).stat().st_size
        s, b = request("POST", self.follow(b.get("upload_url") or f"{self.HOSTS['rupload']}/video-upload/{GRAPH}/{vid}"), file=video, timeout=3600,
                       headers={"Authorization": f"OAuth {tokens['access']}", "offset": "0", "file_size": str(size), "Content-Type": "application/octet-stream"})
        self.check(s, b, "Uploading the Reel to Facebook")
        s, b = request("POST", self.g(f"/{page}/video_reels"), headers=self._auth(tokens),
                       form={"video_id": vid, "upload_phase": "finish", "video_state": "PUBLISHED", "description": self.caption(post)})
        self.check(s, b, "Publishing the Facebook Reel")

        def done():
            s, b = request("GET", self.g(f"/{vid}?fields=status"), headers=self._auth(tokens))
            st = self.check(s, b, "Checking the Facebook Reel").get("status") or {}
            if st.get("video_status") in ("upload_failed", "error", "expired") or (st.get("publishing_phase") or {}).get("publish_status") == "error":
                raise ConnectError(f"Facebook couldn't process the Reel ({st.get('video_status')})")
            return True if (st.get("publishing_phase") or {}).get("publish_status") == "published" else None
        wait_for(done, "Publishing the Facebook Reel", every=self.POLL)
        link = f"{connect.public_url()}/testplatform/facebook/reel/{vid}" if self.test else f"https://www.facebook.com/reel/{vid}"
        return {"id": vid, "link": link, "kind": "reel"}

    def _video(self, tokens, post, video, cover):
        f = post.get("fields") or {}
        fields = {"description": self.caption(post), "published": "true"}
        if f.get("title"):
            fields["title"] = f["title"]
        files = [("source", video, "video/mp4")] + ([("thumb", cover, "image/jpeg")] if cover else [])
        body = _Multipart(fields, files)
        s, b = request("POST", self.g(f"/{tokens['page_id']}/videos", "video"), data=body, timeout=3600,
                       headers={**self._auth(tokens), "Content-Type": body.content_type, "Content-Length": str(body.length)})
        vid = self.check(s, b, "Posting the video on Facebook")["id"]
        link = (f"{connect.public_url()}/testplatform/facebook/videos/{vid}" if self.test else
                f"https://www.facebook.com/{tokens['page_id']}/videos/{vid}")
        return {"id": vid, "link": link, "kind": "video"}

    def results(self, app, tokens, remote_id):
        out = {"views": None, "likes": None, "comments": None, "shares": None, "watch_time_s": None}
        want = {"blue_reels_play_count": "views", "total_video_views": "views", "post_video_avg_time_watched": "avg_ms",
                "post_video_likes_by_reaction_type": "likes", "post_video_social_actions": "social"}
        for metric, key in want.items():          # one at a time: a metric that doesn't apply fails alone
            try:
                s, b = request("GET", self.g(f"/{remote_id}/video_insights?metric={metric}"), headers=self._auth(tokens))
                data = self.check(s, b, "Reading Facebook's numbers").get("data") or []
            except ConnectError:
                continue
            if not data:
                continue
            v = (data[0].get("values") or [{}])[0].get("value")
            if key == "views" and out["views"] is None and isinstance(v, (int, float)):
                out["views"] = int(v)
            elif key == "likes" and isinstance(v, dict):
                out["likes"] = int(sum(v.values()))
            elif key == "social" and isinstance(v, dict):
                out["comments"], out["shares"] = v.get("COMMENT", v.get("comment")), v.get("SHARE", v.get("share"))
            elif key == "avg_ms" and isinstance(v, (int, float)) and out["views"]:
                out["watch_time_s"] = int(v / 1000 * out["views"])
        return out

    def delete(self, app, tokens, remote_id):
        s, b = request("DELETE", self.g(f"/{remote_id}"), headers=self._auth(tokens))
        self.check(s, b, "Deleting the Facebook video")
        return {"ok": True}


class Instagram(Meta):
    NAME = "Instagram"
    SCOPES = ["instagram_basic", "instagram_content_publish", "instagram_manage_insights", "instagram_manage_comments",
              "instagram_manage_contents", "pages_show_list", "pages_read_engagement", "business_management"]

    def exchange(self, app, code, redirect, verifier=None):
        pages = [p for p in self._pages(self._user_token(app, code, redirect)) if p.get("instagram_business_account")]
        if not pages:
            raise ConnectError("No Instagram professional account found: link your brand's Instagram to its Facebook Page "
                               "(Instagram → Settings → Account type and tools), then connect again")
        p = _pick(pages, "instagram", lambda x: (x["instagram_business_account"].get("username") or "") + " " + x.get("name", ""))
        ig = p["instagram_business_account"]
        return {"access": p["access_token"], "refresh": None, "expires_at": None,
                "account": {"id": ig["id"], "name": "@" + ig["username"] if ig.get("username") else p["name"]}, "page_id": p["id"], "ig_id": ig["id"]}

    def publish(self, app, tokens, post, video, cover):
        ig, auth = tokens["ig_id"], self._auth(tokens)
        s, b = request("GET", self.g(f"/{ig}/content_publishing_limit?fields=quota_usage,config"), headers=auth)
        lim = (self.check(s, b, "Checking Instagram's posting limit").get("data") or [{}])[0]
        total = (lim.get("config") or {}).get("quota_total")
        if total and lim.get("quota_usage", 0) >= total:
            raise ConnectError(f"Instagram's limit of {total} posts a day is used up; it frees up over the next hours")
        f = post.get("fields") or {}
        tags = (f.get("hashtags") or [])[:30]
        caption = self.caption({"fields": dict(f, hashtags=tags)}, limit=2200)
        s, b = request("POST", self.g(f"/{ig}/media"), headers=auth,
                       form={"media_type": "REELS", "upload_type": "resumable", "caption": caption, "share_to_feed": "true"})
        c = self.check(s, b, "Starting the Instagram post")
        cid = c["id"]
        upload = self.follow(c.get("uri") or f"{self.HOSTS['rupload']}/ig-api-upload/{GRAPH}/{cid}")
        size = Path(video).stat().st_size
        s, b = request("POST", upload, file=video, timeout=3600,
                       headers={"Authorization": f"OAuth {tokens['access']}", "offset": "0", "file_size": str(size), "Content-Type": "application/octet-stream"})
        self.check(s, b, "Uploading the video to Instagram")

        def ready():
            s, b = request("GET", self.g(f"/{cid}?fields=status_code,status"), headers=auth)
            st = self.check(s, b, "Checking the Instagram upload")
            if st.get("status_code") in ("ERROR", "EXPIRED"):
                raise ConnectError(f"Instagram couldn't process the video: {st.get('status') or st['status_code']}")
            return st["status_code"] if st.get("status_code") in ("FINISHED", "PUBLISHED") else None
        if wait_for(ready, "Processing on Instagram", every=self.POLL * 2) == "PUBLISHED":
            raise ConnectError("Instagram says this upload was already posted: check the account before posting again")
        try:
            s, b = request("POST", self.g(f"/{ig}/media_publish"), headers=auth, form={"creation_id": cid})
            mid = self.check(s, b, "Publishing on Instagram")["id"]
        except ConnectError:
            # never publish twice: if it went out anyway, say so instead of trying again
            s, b = request("GET", self.g(f"/{cid}?fields=status_code"), headers=auth)
            if isinstance(b, dict) and b.get("status_code") == "PUBLISHED":
                raise ConnectError("Instagram posted it but didn't confirm: check the account, then press Mark posted")
            raise
        s, b = request("GET", self.g(f"/{mid}?fields=permalink"), headers=auth)
        link = (b.get("permalink") if isinstance(b, dict) else None) or "https://www.instagram.com/"
        if f.get("first_comment"):
            try:
                s, b = request("POST", self.g(f"/{mid}/comments"), headers=auth, form={"message": f["first_comment"][:2200]})
                self.check(s, b, "Adding the first comment")
            except ConnectError as e:
                post.setdefault("notes", []).append(f"Instagram: the first comment wasn't added ({e})")
        return {"id": mid, "link": link}

    def results(self, app, tokens, remote_id):
        out = {"views": None, "likes": None, "comments": None, "shares": None, "watch_time_s": None}
        names = {"views": "views", "likes": "likes", "comments": "comments", "shares": "shares", "ig_reels_video_view_total_time": "watch_ms"}
        s, b = request("GET", self.g(f"/{remote_id}/insights?metric={','.join(names)}"), headers=self._auth(tokens))
        for d in self.check(s, b, "Reading Instagram's numbers").get("data") or []:
            v = (d.get("values") or [{}])[0].get("value")
            k = names.get(d.get("name"))
            if k == "watch_ms" and isinstance(v, (int, float)):
                out["watch_time_s"] = int(v / 1000)
            elif k and isinstance(v, (int, float)):
                out[k] = int(v)
        return out

    def delete(self, app, tokens, remote_id):
        s, b = request("DELETE", self.g(f"/{remote_id}"), headers=self._auth(tokens))
        self.check(s, b, "Deleting the Instagram post")
        return {"ok": True}


# ================================================================ TikTok (Content Posting API v2)
class TikTok(connect.Connector):
    """Two ways to post (Social settings → TikTok):
      inbox   (default) the video goes to the TikTok app's inbox and someone taps Post on the phone. Works for any app.
      direct  posts by itself. TikTok only allows public posts after its Direct Post audit; before that every post is
              private, and TikTok says it doesn't approve tools that only post to the team's own accounts.
    Sign-in uses PKCE with TikTok's own twist (the challenge is hex, not base64url)."""
    HOSTS = {"www": "https://www.tiktok.com", "api": "https://open.tiktokapis.com"}
    UPLOADS = {"upload": "https://open-upload.tiktokapis.com/video"}
    SCOPES = ["user.info.basic", "video.publish", "video.upload", "video.list"]
    OPTIONS = [{"key": "mode", "label": "How it posts", "default": "inbox",
                "choices": [["inbox", "To the TikTok inbox: tap Post in the app"], ["direct", "Directly (needs TikTok's audit)"]]}]
    CHUNK = 10_000_000

    def check(self, status, body, what):
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict) and err.get("code", "ok") != "ok" or (status >= 400 and isinstance(err, dict)):
            code, msg = err.get("code"), err.get("message") or err.get("code")
            if code == "access_token_invalid":
                raise Expired(msg)
            hint = {"scope_not_authorized": "connect TikTok again and allow every permission",
                    "rate_limit_exceeded": "TikTok asked us to slow down",
                    "spam_risk_too_many_posts": "the account has posted as much as TikTok allows today",
                    "spam_risk_too_many_pending_share": "five videos are already waiting in the TikTok inbox: post or delete them in the app",
                    "unaudited_client_can_only_post_to_private_accounts": "until TikTok audits the app, it can only post privately: use 'Send to TikTok's inbox'",
                    "privacy_level_option_mismatch": "TikTok won't allow public posts from this app yet: use 'Send to TikTok's inbox'",
                    "reached_active_user_cap": "the app has reached TikTok's daily user limit"}.get(code)
            raise ConnectError(f"{what}: {hint or msg} ({code})")
        if isinstance(err, str):                   # the sign-in server's shape
            raise ConnectError(f"{what}: {body.get('error_description') or err}" + (": connect TikTok again" if err == "invalid_grant" else ""))
        if status >= 400:
            raise ConnectError(f"{what}: {str(body)[:200]} ({status})")
        return body

    def authorize_url(self, app, state, redirect, verifier=None):
        q = {"client_key": app["client_id"], "response_type": "code", "scope": ",".join(self.SCOPES), "redirect_uri": redirect, "state": state}
        if verifier:
            q.update(code_challenge=hashlib.sha256(verifier.encode()).hexdigest(), code_challenge_method="S256")
        return self.page_url("www", "/v2/auth/authorize/?" + urlencode(q))

    def _tokens(self, b, old=None):
        return {"access": b["access_token"], "refresh": b.get("refresh_token") or (old or {}).get("refresh"),
                "expires_at": time.time() + int(b.get("expires_in", 86400)),
                "refresh_expires_at": time.time() + int(b["refresh_expires_in"]) if b.get("refresh_expires_in") else (old or {}).get("refresh_expires_at"),
                "open_id": b.get("open_id") or (old or {}).get("open_id"), "account": (old or {}).get("account")}

    def exchange(self, app, code, redirect, verifier=None):
        form = {"client_key": app["client_id"], "client_secret": app.get("client_secret", ""), "code": code,
                "grant_type": "authorization_code", "redirect_uri": redirect}
        if verifier:
            form["code_verifier"] = verifier
        t = self._tokens(self.check(*request("POST", self.url("api", "/v2/oauth/token/"), form=form), "Signing in to TikTok"))
        s, b = request("GET", self.url("api", "/v2/user/info/?fields=open_id,display_name,avatar_url"), headers=self._auth(t))
        u = (self.check(s, b, "Reading the TikTok account").get("data") or {}).get("user") or {}
        t["account"] = {"id": u.get("open_id") or t["open_id"], "name": u.get("display_name") or "TikTok account"}
        return t

    def refresh(self, app, tokens):
        form = {"client_key": app["client_id"], "client_secret": app.get("client_secret", ""), "grant_type": "refresh_token",
                "refresh_token": tokens.get("refresh", "")}
        return self._tokens(self.check(*request("POST", self.url("api", "/v2/oauth/token/"), form=form), "Refreshing the TikTok sign-in"), tokens)

    @staticmethod
    def _auth(tokens):
        return {"Authorization": f"Bearer {tokens['access']}"}

    def _source(self, size):
        if size <= 64_000_000:
            return {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}
        n = size // self.CHUNK
        return {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": self.CHUNK, "total_chunk_count": n}

    def _title(self, post):
        text = self.caption(post)
        while len(text.encode("utf-16-le")) // 2 > 2200:
            text = text[:-1]
        return text

    def publish(self, app, tokens, post, video, cover):
        mode = self.options.get("mode") or "inbox"
        size = Path(video).stat().st_size
        src = self._source(size)
        auth = {**self._auth(tokens), "Content-Type": "application/json; charset=UTF-8"}
        if mode == "direct":
            s, b = request("POST", self.url("api", "/v2/post/publish/creator_info/query/"), json_body={}, headers=auth)
            ci = self.check(s, b, "Checking the TikTok account").get("data") or {}
            dur = _probe(video).get("dur") or 0
            if ci.get("max_video_post_duration_sec") and dur > ci["max_video_post_duration_sec"]:
                raise ConnectError(f"TikTok allows this account videos up to {ci['max_video_post_duration_sec']} seconds; this one is {dur:.0f}")
            opts = ci.get("privacy_level_options") or []
            if "PUBLIC_TO_EVERYONE" not in opts:
                raise ConnectError("TikTok won't let this app post publicly yet (it needs TikTok's Direct Post audit): "
                                   "switch TikTok to 'Send to TikTok's inbox' in Social settings")
            info = {"title": self._title(post), "privacy_level": "PUBLIC_TO_EVERYONE", "disable_comment": bool(ci.get("comment_disabled")),
                    "disable_duet": bool(ci.get("duet_disabled")), "disable_stitch": bool(ci.get("stitch_disabled")),
                    "brand_content_toggle": False, "brand_organic_toggle": True}
            s, b = request("POST", self.url("api", "/v2/post/publish/video/init/"), json_body={"post_info": info, "source_info": src}, headers=auth)
            if ci.get("creator_username"):
                tokens.setdefault("account", {})["username"] = ci["creator_username"]
        else:
            s, b = request("POST", self.url("api", "/v2/post/publish/inbox/video/init/"), json_body={"source_info": src}, headers=auth)
        d = self.check(s, b, "Starting the TikTok upload")["data"]
        pub, upload = d["publish_id"], self.follow(d["upload_url"])
        n, chunk = src["total_chunk_count"], src["chunk_size"]
        for i in range(n):
            off = i * chunk
            length = size - off if i == n - 1 else chunk
            s, b = request("PUT", upload, file=video, part=(off, length), timeout=1800,
                           headers={"Content-Type": "video/mp4", "Content-Range": f"bytes {off}-{off + length - 1}/{size}"})
            if s not in (200, 201, 206):
                self.check(s, b if isinstance(b, dict) else {"error": {"code": str(s), "message": str(b)[:200]}}, "Uploading the video to TikTok")

        def status():
            s, b = request("POST", self.url("api", "/v2/post/publish/status/fetch/"), json_body={"publish_id": pub}, headers=auth)
            st = self.check(s, b, "Checking the TikTok post").get("data") or {}
            if st.get("status") == "FAILED":
                raise ConnectError(f"TikTok couldn't post it ({st.get('fail_reason') or 'failed'})")
            if mode == "inbox" and st.get("status") in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
                return st
            if st.get("status") == "PUBLISH_COMPLETE":
                return st
            return None
        st = wait_for(status, "Posting on TikTok", every=self.POLL)
        if mode == "inbox":
            return {"id": pub, "link": None,
                    "handoff": "It's in the TikTok app's inbox: open TikTok on the phone, tap the notification, check it and tap Post. Then press Mark posted."}
        ids = st.get("publicaly_available_post_id") or []
        vid = str(ids[0]) if ids else None
        user = (tokens.get("account") or {}).get("username")
        link = (f"{connect.public_url()}/testplatform/tiktok/video/{vid}" if self.test and vid else
                f"https://www.tiktok.com/@{user}/video/{vid}" if vid and user else None)
        return {"id": vid or pub, "link": link}

    def results(self, app, tokens, remote_id):
        if not str(remote_id).isdigit():
            return None                     # an inbox post: TikTok gives its numbers once someone has posted it
        s, b = request("POST", self.url("api", "/v2/video/query/?fields=id,view_count,like_count,comment_count,share_count"),
                       json_body={"filters": {"video_ids": [str(remote_id)]}}, headers={**self._auth(tokens), "Content-Type": "application/json"})
        v = ((self.check(s, b, "Reading TikTok's numbers").get("data") or {}).get("videos") or [{}])[0]
        return {"views": v.get("view_count"), "likes": v.get("like_count"), "comments": v.get("comment_count"), "shares": v.get("share_count"),
                "watch_time_s": None}


# ================================================================ LinkedIn (versioned REST API: Videos + Posts)
LINKEDIN_VERSION = "202610"           # LinkedIn retires each version after about a year: bump it yearly


class LinkedIn(connect.Connector):
    """Posts as the company page (needs LinkedIn's Community Management API product) or as a person's profile (the
    self-serve "Share on LinkedIn" + "Sign In with LinkedIn" products). LinkedIn sign-ins last 60 days; a refresh token
    comes only for LinkedIn's approved partners, so usually someone presses Connect again every 60 days."""
    HOSTS = {"www": "https://www.linkedin.com", "api": "https://api.linkedin.com"}
    UPLOADS = {"dms": "https://www.linkedin.com/dms-uploads"}
    OPTIONS = [{"key": "as", "label": "Post as", "default": "page",
                "choices": [["page", "The company page"], ["profile", "A person's profile"]]}]
    SCOPES = {"page": ["r_basicprofile", "w_member_social", "w_organization_social", "r_organization_social", "rw_organization_admin"],
              "profile": ["openid", "profile", "w_member_social"]}

    def check(self, status, body, what):
        if status < 400:
            return body
        b = body if isinstance(body, dict) else {}
        msg = b.get("message") or b.get("error_description") or b.get("error") or str(body)[:200]
        if status == 401:
            raise Expired(f"LinkedIn's sign-in has run out (it lasts 60 days) or was removed: connect LinkedIn again in Social settings ({msg})")
        if status == 426:
            raise ConnectError(f"{what}: LinkedIn retired API version {LINKEDIN_VERSION}: the developer should update LINKEDIN_VERSION in connectors.py")
        if status == 429:
            raise ConnectError(f"{what}: LinkedIn's daily limit for the app is used up (it resets at midnight UTC)")
        if status == 403:
            raise ConnectError(f"{what}: LinkedIn refused it ({msg}): the person who connected must be an admin of the page, and the app needs the right product")
        if b.get("error") == "invalid_request" and "refresh" in str(msg):
            raise ConnectError("LinkedIn's sign-in can't be renewed: connect LinkedIn again in Social settings")
        raise ConnectError(f"{what}: {msg} ({b.get('code') or status})")

    def _as(self):
        return self.options.get("as") or "page"

    def authorize_url(self, app, state, redirect, verifier=None):
        q = {"response_type": "code", "client_id": app["client_id"], "redirect_uri": redirect, "state": state, "scope": " ".join(self.SCOPES[self._as()])}
        return self.page_url("www", "/oauth/v2/authorization?" + urlencode(q))

    def _tokens(self, b, old=None):
        return {"access": b["access_token"], "refresh": b.get("refresh_token") or (old or {}).get("refresh"),
                "expires_at": time.time() + int(b.get("expires_in", 5184000)),
                "author": (old or {}).get("author"), "account": (old or {}).get("account")}

    def h(self, tokens, extra=None):
        return {"Authorization": f"Bearer {tokens['access']}", "LinkedIn-Version": LINKEDIN_VERSION, "X-Restli-Protocol-Version": "2.0.0", **(extra or {})}

    def exchange(self, app, code, redirect, verifier=None):
        form = {"grant_type": "authorization_code", "code": code, "client_id": app["client_id"], "client_secret": app.get("client_secret", ""),
                "redirect_uri": redirect}
        t = self._tokens(self.check(*request("POST", self.url("www", "/oauth/v2/accessToken"), form=form), "Signing in to LinkedIn"))
        auth = {"Authorization": f"Bearer {t['access']}"}
        if self._as() == "profile":
            s, b = request("GET", self.url("api", "/v2/userinfo"), headers=auth)
            u = self.check(s, b, "Reading the LinkedIn profile")
            t["author"], t["account"] = f"urn:li:person:{u['sub']}", {"id": u["sub"], "name": u.get("name") or "LinkedIn profile"}
            return t
        s, b = request("GET", self.url("api", "/v2/me"), headers=auth)
        me = self.check(s, b, "Reading the LinkedIn profile")
        s, b = request("GET", self.url("api", "/rest/organizationAcls?q=roleAssignee&state=APPROVED&count=100"), headers=self.h(t))
        posters = ("ADMINISTRATOR", "CONTENT_ADMINISTRATOR", "CONTENT_ADMIN", "DIRECT_SPONSORED_CONTENT_POSTER")
        orgs = [e.get("organization") or e.get("organizationTarget") for e in self.check(s, b, "Finding the LinkedIn pages").get("elements") or []
                if e.get("role") in posters]
        orgs = [o for o in dict.fromkeys(orgs) if o]
        if not orgs:
            raise ConnectError(f"{me.get('localizedFirstName', 'This person')} isn't an admin of a LinkedIn page: ask a page super admin to add them, "
                               "or choose 'A person's profile' for LinkedIn in Social settings")
        named = []
        for o in orgs[:20]:
            s, b = request("GET", self.url("api", f"/rest/organizations/{o.rsplit(':', 1)[-1]}"), headers=self.h(t))
            named.append((o, (b.get("localizedName") if s < 400 and isinstance(b, dict) else None) or o))
        org, name = _pick(named, "linkedin", lambda x: x[1])
        t["author"], t["account"] = org, {"id": org, "name": name}
        return t

    def refresh(self, app, tokens):
        if not tokens.get("refresh"):
            return tokens
        form = {"grant_type": "refresh_token", "refresh_token": tokens["refresh"], "client_id": app["client_id"], "client_secret": app.get("client_secret", "")}
        return self._tokens(self.check(*request("POST", self.url("www", "/oauth/v2/accessToken"), form=form), "Refreshing the LinkedIn sign-in"), tokens)

    @staticmethod
    def little(text):
        """LinkedIn's 'little' text format: escape the reserved characters, keep #hashtags as hashtags."""
        import re
        return re.sub(r"([\\|{}@\[\]()<>*_~])", r"\\\1", text)

    def publish(self, app, tokens, post, video, cover):
        size = Path(video).stat().st_size
        req = {"initializeUploadRequest": {"owner": tokens["author"], "fileSizeBytes": size, "uploadCaptions": False, "uploadThumbnail": bool(cover)}}
        s, b = request("POST", self.url("api", "/rest/videos?action=initializeUpload"), json_body=req, headers=self.h(tokens))
        v = self.check(s, b, "Starting the LinkedIn upload")["value"]
        urn, etags = v["video"], []
        for ins in v["uploadInstructions"]:
            first, last = int(ins["firstByte"]), int(ins["lastByte"])
            u = self.follow(ins["uploadUrl"])
            s, b, hd = request("PUT", u, file=video, part=(first, last - first + 1), headers={"Content-Type": "application/octet-stream"}, timeout=1800, full=True)
            self.check(s, b, "Uploading the video to LinkedIn")
            etags.append(hd.get("etag", ""))
        if cover and v.get("thumbnailUploadUrl"):
            u = self.follow(v["thumbnailUploadUrl"])
            s, b = request("PUT", u, file=cover, headers={"Content-Type": "application/octet-stream", "media-type-family": "STILLIMAGE"})
            if s >= 400:
                post.setdefault("notes", []).append("LinkedIn: the cover wasn't set")
        s, b = request("POST", self.url("api", "/rest/videos?action=finalizeUpload"), headers=self.h(tokens),
                       json_body={"finalizeUploadRequest": {"video": urn, "uploadToken": v.get("uploadToken", ""), "uploadedPartIds": etags}})
        self.check(s, b, "Finishing the LinkedIn upload")

        def ready():
            s, b = request("GET", self.url("api", f"/rest/videos/{quote(urn, safe='')}"), headers=self.h(tokens))
            st = self.check(s, b, "Checking the LinkedIn video").get("status")
            if st == "PROCESSING_FAILED":
                raise ConnectError(f"LinkedIn couldn't process the video ({b.get('processingFailureReason') or 'failed'})")
            return True if st == "AVAILABLE" else None
        wait_for(ready, "Processing on LinkedIn", every=self.POLL * 3)        # every check counts against LinkedIn's daily limit
        f = post.get("fields") or {}
        body = {"author": tokens["author"], "commentary": self.little(self.caption(post, limit=3000)), "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                "content": {"media": {"id": urn, "title": (post["video"].get("name") or "")[:200]}}, "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False}
        s, b, hd = request("POST", self.url("api", "/rest/posts"), json_body=body, headers=self.h(tokens), full=True)
        self.check(s, b, "Posting on LinkedIn")
        pid = hd.get("x-restli-id") or hd.get("x-linkedin-id")
        if not pid:
            raise ConnectError("LinkedIn accepted the post but didn't say its address: check the page")
        link = (f"{connect.public_url()}/testplatform/linkedin/feed/update/{pid}" if self.test else f"https://www.linkedin.com/feed/update/{pid}/")
        return {"id": pid, "link": link}

    def results(self, app, tokens, remote_id):
        out = {"views": None, "likes": None, "comments": None, "shares": None, "watch_time_s": None}
        s, b = request("GET", self.url("api", f"/rest/socialActions/{quote(remote_id, safe='')}"), headers=self.h(tokens))
        if s < 400 and isinstance(b, dict):
            out["likes"] = (b.get("likesSummary") or {}).get("totalLikes", 0)
            out["comments"] = (b.get("commentsSummary") or {}).get("aggregatedTotalComments", 0)
        if str(tokens.get("author", "")).startswith("urn:li:organization:") and ":ugcPost:" in remote_id:
            for kind, key in (("VIDEO_VIEW", "views"), ("TIME_WATCHED", "watch_ms")):
                s, b = request("GET", self.url("api", f"/rest/videoAnalytics?q=entity&entity={quote(remote_id, safe='')}&type={kind}&aggregation=ALL"),
                               headers=self.h(tokens))
                el = ((b.get("elements") if s < 400 and isinstance(b, dict) else None) or [{}])[0]
                if el.get("value") is not None:
                    if key == "views":
                        out["views"] = int(el["value"])
                    else:
                        out["watch_time_s"] = int(el["value"] / 1000)
        return out

    def delete(self, app, tokens, remote_id):
        s, b = request("DELETE", self.url("api", f"/rest/posts/{quote(remote_id, safe='')}"), headers=self.h(tokens, {"X-RestLi-Method": "DELETE"}))
        self.check(s, b, "Deleting the LinkedIn post")
        return {"ok": True}


connect.REAL.update({"youtube": YouTube, "facebook": Facebook, "instagram": Instagram, "tiktok": TikTok, "linkedin": LinkedIn})
