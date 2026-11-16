"""One way to call Claude, for everything in Studio AI (ROADMAP phase 7): the New pipelines (short and long), takeover
fills, brand-guide import and the AI studio all ask for one JSON object and go through ask_json().

Two back ends:
  cli  `claude -p` (Claude Code), the user's own login on this Mac. Claude reads files itself with its Read tool (and
       fetches a website with WebFetch), so prompts may simply name files in `cwd`.
  api  The Anthropic API with the user's own API key, for the hosted team portal (a Claude.ai / Claude Code login can't
       be shared through a server). Needs the official SDK on the server (`pip install anthropic`, Python 3.10+). It
       can't open files, so the caller passes them in `files` (images and PDFs are attached to the request) and a
       website in `web_url` (the server-side web fetch tool reads it).

Which one runs: a Creds object, made per request by creds_from(headers, settings) and kept by the job that uses it.
  - The portal sets the request headers  X-Claude-Api-Key  (and optionally X-Claude-Model)  for the signed-in user.
  - Without them: settings.json  {"claude_backend": "api"}  uses the server's ANTHROPIC_API_KEY (one shared key);
    anything else uses `claude -p` (the default on a Mac).
A key is never written to disk or to a log.
"""
import base64, json, mimetypes, os, re, shutil, subprocess, time
from pathlib import Path

import osutil   # macOS / Windows differences (where claude is installed)

DEFAULT_MODEL = "claude-opus-5-5"
SIGNED_OUT = re.compile(r"not logged in|please run /login|invalid api key|failed to authenticate|session expired", re.I)
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_ATTACH = 30 * 1024 * 1024      # the API takes 32 MB per request; leave room for the prompt


class ClaudeError(RuntimeError):
    pass


class NotSignedIn(ClaudeError):
    """Claude Code isn't signed in on this Mac, or the API key was rejected."""


class Creds:
    """How to reach Claude for one request (and the jobs it starts)."""

    def __init__(self, backend="cli", api_key=None, model=None, claude_cmd=None):
        self.backend, self.api_key, self.model, self.claude_cmd = backend, api_key, model, claude_cmd

    def __repr__(self):                       # never print the key
        return f"Creds({self.backend}, model={self.model or DEFAULT_MODEL})"

    @property
    def available(self):
        return bool(self.api_key) if self.backend == "api" else bool(self.claude_cmd)

    @property
    def label(self):
        return "the Claude API" if self.backend == "api" else "Claude Code"


def find_claude(settings):
    cands = [settings.get("claude_cmd"), shutil.which("claude")] + osutil.claude_candidates()
    return next((c for c in cands if c and Path(c).is_file() and os.access(c, os.X_OK)), None)


def creds_from(headers, settings):
    """The credentials for this request: the portal's per-user key, the server's shared key, or Claude Code."""
    key = (headers.get("X-Claude-Api-Key") if headers else None) or None
    model = (headers.get("X-Claude-Model") if headers else None) or settings.get("claude_model") or None
    if key:
        return Creds("api", api_key=key.strip(), model=model)
    if settings.get("claude_backend") == "api":
        return Creds("api", api_key=os.environ.get("ANTHROPIC_API_KEY"), model=model)
    return Creds("cli", model=settings.get("claude_model"), claude_cmd=find_claude(settings))


def parse_json(text, what="reply"):
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if not m:
        raise ClaudeError(f"Claude's {what} had no JSON in it: {text[-300:]}")
    try:
        return json.loads(m.group(1))
    except ValueError as e:
        raise ClaudeError(f"Claude's {what} wasn't valid JSON ({e})")


def ask_json(creds, prompt, *, cwd=None, tools="Read,Glob,Grep", files=(), web_url=None, on_event=None,
             timeout=1800, effort="high", what="reply", env=None, should_stop=None):
    """Ask Claude for one JSON object. on_event(text) gets short progress lines ("Reading page 3", "Thinking…").
    files: paths the API back end attaches (the cli back end reads what the prompt names in cwd, so it ignores them).
    should_stop(): checked while Claude Code runs; True stops it (ClaudeError "Stopped")."""
    if creds is None or not creds.available:
        raise NotSignedIn("Claude isn't set up: sign in to Claude Code on this Mac, or add your Claude API key in the portal")
    if creds.backend == "api":
        return parse_json(_ask_api(creds, prompt, files, web_url, on_event, timeout, effort), what)
    return parse_json(_ask_cli(creds, prompt, cwd, tools + (",WebFetch" if web_url else ""), on_event, timeout, env, should_stop), what)


# ---------------------------------------------------------------- claude -p
def _ask_cli(creds, prompt, cwd, tools, on_event, timeout, env, should_stop=None):
    cmd = [creds.claude_cmd, "-p", "Do the task described in the input. Reply with the JSON object only.",
           "--output-format", "stream-json", "--verbose", "--allowedTools", tools]
    if creds.model:
        cmd += ["--model", creds.model]
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    p.stdin.write(prompt); p.stdin.close()
    final, tail, deadline = None, [], time.time() + timeout
    for line in p.stdout:
        tail.append(line); del tail[:-40]
        if time.time() > deadline:
            p.kill(); raise ClaudeError(f"Claude took too long ({timeout // 60} minutes)")
        if should_stop and should_stop():
            p.kill(); raise ClaudeError("Stopped")
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant" and on_event:
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    what = inp.get("file_path") or inp.get("url") or inp.get("pattern") or ""
                    m = re.search(r"page-(\d+)", what)
                    on_event(f"Looking at page {int(m.group(1))}" if m else f"{c.get('name')}: {Path(what).name or what}"[:120])
        elif ev.get("type") == "result":
            final = ev.get("result") or ""
    p.wait()
    out = final if final is not None else "".join(tail)
    if SIGNED_OUT.search(out) or (final is None and SIGNED_OUT.search("".join(tail))):
        raise NotSignedIn("Claude Code isn't signed in: run claude in Terminal once and sign in, then try again")
    if final is None:
        raise ClaudeError("Claude Code stopped without an answer: " + "".join(tail)[-300:])
    return out


# ---------------------------------------------------------------- the Anthropic API (the hosted portal)
def _attachments(files):
    """Images and PDFs as content blocks; text files inline. Stops before the request size limit."""
    blocks, total, skipped = [], 0, []
    for f in files or ():
        f = Path(f)
        if not f.is_file():
            continue
        mt = mimetypes.guess_type(f.name)[0] or ""
        size = f.stat().st_size
        if total + size * 4 // 3 > MAX_ATTACH:
            skipped.append(f.name); continue
        if mt in IMAGE_TYPES or mt == "application/pdf":
            data = base64.standard_b64encode(f.read_bytes()).decode("ascii")
            total += len(data)
            kind = "image" if mt in IMAGE_TYPES else "document"
            blocks.append({"type": "text", "text": f"File: {f.name}"})
            blocks.append({"type": kind, "source": {"type": "base64", "media_type": mt, "data": data}})
        elif mt.startswith("text/") or f.suffix.lower() in (".json", ".md", ".txt", ".srt", ".vtt", ".css", ".svg"):
            text = f.read_text(errors="replace"); total += len(text)
            blocks.append({"type": "text", "text": f"File: {f.name}\n{text}"})
    if skipped:
        blocks.append({"type": "text", "text": f"(Left out to stay under the size limit: {', '.join(skipped[:20])})"})
    return blocks


def _ask_api(creds, prompt, files, web_url, on_event, timeout, effort):
    try:
        import anthropic
    except ImportError:
        raise ClaudeError("The Claude API back end needs the anthropic package on this server: pip install anthropic (Python 3.10+)")
    client = anthropic.Anthropic(api_key=creds.api_key, timeout=float(timeout))
    content = _attachments(files) + [{"type": "text", "text": prompt}]
    if web_url:
        content.append({"type": "text", "text": f"The website to read: {web_url}"})
    messages = [{"role": "user", "content": content}]
    tools = [{"type": "web_fetch_20260209", "name": "web_fetch"}] if web_url else []
    kw = dict(model=creds.model or DEFAULT_MODEL, max_tokens=64000, messages=messages,
              output_config={"effort": effort},
              # a declined request is re-run on Anthropic's recommended fallback model instead of failing
              betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    if tools:
        kw["tools"] = tools
    if on_event:
        on_event("Claude is working…")
    try:
        for _ in range(6):                      # pause_turn: the server-side tool loop paused; send it back to resume
            with client.beta.messages.stream(**kw) as stream:
                msg = stream.get_final_message()
            if msg.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": msg.content})
    except anthropic.AuthenticationError:
        raise NotSignedIn("The Claude API key was rejected: check it in the portal")
    except anthropic.PermissionDeniedError:
        raise NotSignedIn("This Claude API key can't use that model")
    except anthropic.RateLimitError:
        raise ClaudeError("Claude is busy for this API key (rate limit). Try again in a minute")
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"The Claude API said no ({e.status_code}): {getattr(e, 'message', e)}")
    except anthropic.APIConnectionError:
        raise ClaudeError("Couldn't reach the Claude API (network)")
    if msg.stop_reason == "refusal":
        raise ClaudeError("Claude declined this request")
    if msg.stop_reason == "max_tokens":
        raise ClaudeError("Claude's reply was cut off (too long)")
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
