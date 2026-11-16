"""Auto-filled takeovers: Claude writes a takeover's text (and lands each part on its word) from what is said
around the playhead. Used by POST /api/takeover/suggest. Claude runs as `claude -p` (Claude Code headless, the
user's own login), like the New pipeline. Without Claude, a simple fallback takes the title from the sentence.
"""
import json, re, subprocess, sys

import claude_client
from pathlib import Path

# Studio AI brand kits: a client video gets the client's name and tone of voice
try:
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "03. Brands"))
    import brandkit
except ImportError:
    brandkit = None

KINDS = {
    "list": "a list being named: kicker, a short title (one *word* underlined), and items, each landing on the word where it is named. "
            "Use logos for named tools (any logo key or icon:<lucide name>); mode full; up to 4 items, text up to 28 characters.",
    "pip": "a list with the speaker in a window above it: mode pip, kicker, a title up to 22 characters, up to 5 items, each on its word.",
    "stat": "a big number: kicker, and stat {value, count (the number to count up to, if it is a plain number), prefix, suffix, "
            "t (the number's word), label (what it measures, short), t_label, size (300; ~210 for six characters), bar (0-1, optional)}. "
            "If no number is said, use a 'thing one' style value like \"01\" with the point as the label.",
    "recap": "a numbered recap: kicker (e.g. Recap), a title like \"Two *big* things\", numbered: true, items on their words.",
    "headline": "big text: a kicker and one big headline (title) that captures the point being made, t_title on its first word. "
                "No items, no stat. Full titles up to 16 characters per line, 2-3 lines at most.",
}


def section(md, head):
    m = re.search(rf"^## {re.escape(head)}.*?(?=^## )", md, re.S | re.M)
    return m.group(0) if m else ""


def window(words, t, before=1.0, after=25.0, cap=110):
    """Indexed words from just before the playhead to about 25 s after it."""
    out = [(i, w) for i, w in enumerate(words) if t - before <= w["start"] <= t + after]
    return out[:cap]


def sentence_at(words, t):
    """The sentence being said at t (fallback title)."""
    i = next((k for k, w in enumerate(words) if w["start"] >= t - 0.05), len(words) - 1)
    a = i
    while a > 0 and not re.search(r"[.?!]$", words[a - 1]["text"]) and i - a < 12:
        a -= 1
    b = i
    while b < len(words) - 1 and not re.search(r"[.?!]$", words[b]["text"]) and b - a < 14:
        b += 1
    return words[a:b + 1]


def fallback(kind, words, t, dur):
    s = sentence_at(words, t)
    text = " ".join(w["text"] for w in s).strip(" ,.")
    title = " ".join(text.split()[:5]) or "Your point"
    t0 = round(max(0.1, (s[0]["start"] if s else t) - 0.1), 2)
    base = {"mode": "full", "t": t0, "out": round(min(dur, t0 + 4.5), 2), "kicker": "Key point"}
    if kind == "stat":
        num = next((w for w in words if w["start"] >= t - 0.5 and re.search(r"\d", w["text"])), None)
        val = re.sub(r"[^\d.%£$€x+–-]", "", num["text"]) if num else "01"
        return {**base, "stat": {"value": val or "01", "t": round((num["start"] if num else t0 + 0.3), 2), "label": title, "t_label": round(t0 + 1.2, 2)}}
    return {**base, "title": title, "t_title": round(t0 + 0.1, 2)}


def suggest(kind, t, words, spec, skill, creds, env=None, cwd=None):
    """-> (takeover dict, how) where how is 'claude' or 'fallback: <why>'."""
    dur = float(spec.get("duration", 0)) or (words[-1]["end"] if words else 0)
    kind = kind if kind in KINDS else "list"
    if not creds or not creds.available:
        return fallback(kind, words, t, dur), "fallback: Claude isn't set up (sign in to Claude Code, or add an API key in the portal)"
    fmt = spec.get("format", "reel")
    ref = Path(skill) / "references"
    md = (ref / "reel-spec.md").read_text() if (ref / "reel-spec.md").exists() else ""
    ex = []
    try:
        ex = json.loads((ref / "example-takeovers.json").read_text()).get("takeovers", [])
    except (OSError, ValueError):
        pass
    win = window(words, t)
    if not win:
        return fallback(kind, words, t, dur), "fallback: no words near the playhead"
    others = [(k.get("t"), k.get("out")) for k in spec.get("takeovers", [])]
    lines = "\n".join(f"{i}\t{w['start']:.2f}\t{w['text']}" for i, w in win)
    bid = spec.get("brand") if brandkit else None
    who = brandkit.display_name(bid) if bid else "Your brand"
    voice = brandkit.voice_note(bid) if bid else ""
    prompt = f"""You write one takeover (a gradient cutaway) for a {who} {fmt} video, from what the speaker says.
{voice}

Kind wanted: {kind}: {KINDS[kind]}
{"Picture-in-picture is reel-only: use mode full." if fmt != "reel" and kind == "pip" else ""}

Rules:
- Use the speaker's own words and meaning; short, punchy, sentence case. No made-up facts or numbers.
- Every time is seconds on the edited timeline below. A part lands on its word: word start - 0.1.
- "t" is where the takeover starts: on the word that introduces it, at or after {max(0, t - 1):.2f}s.
- "out" ends it 0.6-1.2 s after the last part lands, under 12 s in total, before {dur:.2f}s.
- Don't overlap these existing takeovers (t, out): {json.dumps(others)}.
- If nothing nearby suits this kind, still write the best one you can from what is said at the playhead.

Reply with JSON only: {{"takeover": {{...}}}}

Spec (takeovers):
{section(md, "takeovers")}

Examples from a finished reel:
{json.dumps(ex[:6], indent=1)}

Transcript (index, start s, word), playhead at {t:.2f}s:
{lines}
"""
    try:
        out = claude_client.ask_json(creds, prompt, cwd=cwd, env=env, timeout=180, effort="medium", what="takeover")
    except (claude_client.ClaudeError, OSError) as e:
        return fallback(kind, words, t, dur), f"fallback: {e}"
    tk = out.get("takeover") if isinstance(out, dict) else None
    if not isinstance(tk, dict) or not isinstance(tk.get("t"), (int, float)):
        return fallback(kind, words, t, dur), "fallback: Claude's reply wasn't a takeover"
    if fmt != "reel":
        tk["mode"] = "full"
    tk["t"] = round(max(0.05, min(float(tk["t"]), dur - 1)), 2)
    if isinstance(tk.get("out"), (int, float)):
        tk["out"] = round(min(float(tk["out"]), dur), 2)
    return tk, "claude"
