// default reel timeline editor. Edits reel.json (captions, cards, chips, text, end screen);
// every change rebuilds a shadow preview with the skill's own build script.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "style") e.style.cssText = v;
    else if (k in e && k !== "list") e[k] = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : String(k));
  return e;
};
const r2 = (x) => Math.round(x * 100) / 100;
const ic = (name) => { const e = document.createElement("span"); e.className = "icw"; e.innerHTML = icon(name); return e; };
const clone = (o) => JSON.parse(JSON.stringify(o));
const fmtT = (t) => { const m = Math.floor(t / 60), s = t - m * 60; return `${m}:${s.toFixed(2).padStart(5, "0")}`; };

const S = {
  spec: null, words: [], groups: [], icons: [], logos: [], templates: {}, name: "", path: "",
  dur: 0, total: 0, fps: 25, pps: 60, t: 0, playing: false, sel: null, selWord: null,
  undo: [], redo: [], dirty: false, zoomEdits: {}, edlInfo: {}, savedJSON: "", peaks: [], perSec: 100, muted: false,
};

// ---------------------------------------------------------------- card model
const TRACK = (c) => (c.type === "chip" ? "chips" : c.type === "text" ? "text" : "cards");
const isTimeKey = (k) => k === "t" || k.startsWith("t_") || k === "dim_at";

// every time value on a card (entry, parts, cues) except `out`
function refs(c) {
  const out = [];
  for (const k of Object.keys(c)) {
    if (isTimeKey(k) && typeof c[k] === "number") out.push({ label: k, get: () => c[k], set: (v) => (c[k] = v) });
  }
  if (Array.isArray(c.times)) c.times.forEach((_, i) => out.push({ label: `times[${i}]`, get: () => c.times[i], set: (v) => (c.times[i] = v) }));
  if (Array.isArray(c.leads)) c.leads.forEach((l, i) => typeof l.t === "number" && out.push({ label: `leads[${i}]`, get: () => l.t, set: (v) => (l.t = v) }));
  // takeovers: each item lands on its own word, and a big number has its own cues
  if (Array.isArray(c.items)) c.items.forEach((it, i) => it && typeof it.t === "number" && out.push({ label: `item ${i + 1}`, get: () => it.t, set: (v) => (it.t = v) }));
  if (c.stat && typeof c.stat === "object") ["t", "t_label"].forEach((k) => typeof c.stat[k] === "number" &&
    out.push({ label: k === "t" ? "number" : "number label", get: () => c.stat[k], set: (v) => (c.stat[k] = v) }));
  return out;
}
function firstRef(c) { const r = refs(c).map((x) => x.get()); return r.length ? Math.min(...r) : 0; }
function lastRef(c) { const r = refs(c).map((x) => x.get()); return r.length ? Math.max(...r) : 0; }
// on screen from the moment it lands (the build adds a 0.1 s pre-roll) until it has left
function span(c) {
  const s = Math.max(0, firstRef(c));
  const e = Math.min(c.out ?? S.dur, S.dur);
  return [s, Math.max(e, s + 0.1)];
}
function label(c) {
  const pick = c.text || c.word || c.title || c.question || c.kicker || c.label ||
    (c.items && (c.items[0]?.label || c.items[0])) || (c.steps && c.steps.map((s) => s.label).join(" → ")) ||
    (c.left && c.left.kicker) || "";
  return String(pick).replace(/\*/g, "").replace(/->/g, "→");
}
function shiftCard(c, d) { refs(c).forEach((r) => r.set(r2(r.get() + d))); if (typeof c.out === "number") c.out = r2(c.out + d); }

// ---------------------------------------------------------------- captions model
const cap = () => (S.spec.captions = S.spec.captions || {});
const fixOf = (i) => cap().fix?.[i];
const isDrop = (i) => (cap().drop || []).includes(i);
const isKw = (i) => {
  if ((cap().keywords || []).includes(i)) return true;
  const kw = (cap().keyword_words || []).map((w) => w.toLowerCase());
  return kw.length > 0 && kw.includes((fixOf(i) ?? S.words[i].text).toLowerCase().replace(/[^\w']/g, ""));
};
const wordText = (i) => (fixOf(i) ?? S.words[i].text).replace(/,$/, "");
// group ranges [a, b] including dropped words inside the range
function groupRanges() {
  if (cap().groups) return cap().groups.map((g) => [g[0], g[1]]);
  return S.groups.map((g) => [Math.min(...g.words), Math.max(...g.words)]);
}
function materialiseGroups() { if (!cap().groups) cap().groups = groupRanges(); }
function groupSpan(gi) {
  const g = S.groups[gi];
  if (g) return [g.start, g.end];
  const [a, b] = groupRanges()[gi];
  return [S.words[a].start, S.words[b].end];
}

// ---------------------------------------------------------------- undo / change pipeline
const stateJSON = () => JSON.stringify({ s: S.spec, c: S.cut || null });
function restoreState(j) { const o = JSON.parse(j); S.spec = o.s; S.cut = o.c; pushSkips(); }
function snapshot() { S.undo.push(stateJSON()); if (S.undo.length > 200) S.undo.shift(); S.redo = []; }
// drawing the overlay lane adds an empty "overlays" list; it isn't a change, so compare without it
const specKey = (o) => JSON.stringify(o, (k, v) => (k === "overlays" && Array.isArray(v) && !v.length ? undefined : v));
function change({ inspector = true } = {}) {
  S.dirty = specKey(S.spec) !== specKey(JSON.parse(S.savedJSON));
  try { localStorage.setItem("draft:" + S.path, JSON.stringify(S.spec)); } catch (e) {}
  computeTotals();
  drawTimeline();
  if (inspector) drawInspector();
  setStatus();
  if (window.updateBrandChip) updateBrandChip();
  schedulePreview();
}
function undo() { if (!S.undo.length) return; S.redo.push(stateJSON()); restoreState(S.undo.pop()); fixSel(); change(); }
function redo() { if (!S.redo.length) return; S.undo.push(stateJSON()); restoreState(S.redo.pop()); fixSel(); change(); }
function fixSel() {
  if (S.sel?.kind === "card" && !S.spec.cards[S.sel.i]) S.sel = null;
  if (S.sel?.kind === "end" && !S.spec.endcard) S.sel = null;
  if ((S.sel?.kind === "fx" || S.sel?.kind === "sfx") && !(S.spec[S.sel.kind] || [])[S.sel.i]) S.sel = null;
  if (S.sel?.kind === "tk" && !(S.spec.takeovers || [])[S.sel.i]) S.sel = null;
  if (S.sel?.kind === "clip" && !cutSegs()[S.sel.i]) S.sel = null;
  if (S.sel?.kind === "rd" && !(S.spec.redactions || [])[S.sel.i]) S.sel = null;
  if (S.sel?.kind === "ov" && !(S.spec.overlays || [])[S.sel.i]) S.sel = null;
}
// output formats (matches the skill's build.py): canvas, panel point for cards, caption defaults, position presets
const FMTS = {
  reel: { w: 1080, h: 1920, label: "Reel 9:16" },
  feed: { w: 1080, h: 1350, label: "Feed 4:5", cy: 1040, chipY: 92, capTop: 660, capSize: 64, range: [700, 1300],
    presets: [["Top", 92], ["Upper", 860], ["Middle", 1040], ["Lower", 1180]], hint: "Captions sit at y≈660. Cards are centred below them, scaled to fit." },
  square: { w: 1080, h: 1080, label: "Square 1:1", cy: 832, chipY: 80, capTop: 560, capSize: 58, range: [600, 1040],
    presets: [["Top", 80], ["Upper", 720], ["Middle", 832], ["Lower", 930]], hint: "Captions sit at y≈560. Cards are centred below them, scaled to fit." },
  landscape: { w: 1920, h: 1080, label: "Landscape 16:9", cy: 470, chipY: 100, capTop: 880, capSize: 60, range: [80, 960],
    presets: [["Top", 110], ["Upper", 300], ["Middle", 470], ["Lower", 640]],
    hint: "Landscape cards sit in the side panel (set left, right or centre for the whole video when nothing is selected). Captions sit at y≈880." },
};
const fmtOf = (f) => FMTS[f || S.spec?.format || "reel"] || FMTS.reel;
const isLand = () => (S.spec?.format || "reel") === "landscape";
const isPanel = () => !!fmtOf().cy;          // every format except the full-height reel
function canvasSize(fmt) { const F = fmtOf(fmt); return [F.w, F.h]; }
function computeTotals() {
  S.dur = +S.spec.duration; S.fps = S.spec.fps || 25;
  S.total = S.dur + (S.spec.endcard ? +(S.spec.endcard.duration ?? 3.5) : 0);
}

function setStatus(msg, cls) {
  const st = $("#status");
  st.className = "status " + (cls || (S.dirty ? "dirty" : ""));
  st.textContent = msg || (S.dirty ? "Unsaved changes" : "Saved");
  st.hidden = !st.textContent.trim();
  $("#undo").disabled = !S.undo.length; $("#redo").disabled = !S.redo.length;
}

// ---------------------------------------------------------------- preview (double-buffered iframes)
let previewTimer = 0, previewBusy = false, previewAgain = false, previewVer = 0, active = null;
const frames = () => [$("#pvA"), $("#pvB")];
const ed = () => active?.contentWindow?.__editor;

function schedulePreview(delay = 450) { clearTimeout(previewTimer); previewTimer = setTimeout(buildPreview, delay); }
async function buildPreview() {
  if (previewBusy) { previewAgain = true; return; }
  previewBusy = true; $("#building").hidden = false;
  try {
    const res = await fetch("/api/preview", { method: "POST", body: JSON.stringify({ spec: S.spec }) }).then((r) => r.json());
    if (!res.ok) { showBanner("The build failed. The preview shows the last version that worked.", res.log, true); }
    else {
      hideBanner();
      S.groups = res.groups || [];
      drawTimeline(); if (!S.sel || S.sel.kind === "cap") drawInspectorSafe();
      await swapPreview();
    }
  } catch (e) { showBanner("Couldn't reach the editor server. Is server.py still running?", String(e), true); }
  previewBusy = false; $("#building").hidden = true;
  if (previewAgain) { previewAgain = false; buildPreview(); }
}
function swapPreview() {
  return new Promise((resolve) => {
    const [a, b] = frames();
    const back = active === a ? b : a;
    const wasPlaying = S.playing;
    back.onload = async () => {
      const api = back.contentWindow.__editor;
      if (!api) { resolve(); return; }
      api.setMuted(S.muted);
      await api.ready(S.t);
      if (active && ed()) { ed().pause(); }
      back.classList.add("active"); if (active) active.classList.remove("active");
      active = back; $("#pvMsg").hidden = true; pushZoomPreview(); pushSkips(); drawOverlay();
      if (wasPlaying) ed().play(S.t);
      resolve();
    };
    back.src = `/preview/index.html?v=${++previewVer}`;
  });
}
window.__previewTime = (t, playing) => {
  S.t = t; S.playing = playing;
  setPlayIcon(playing);
  movePlayhead(true);
};
function setPlayIcon(playing) {
  const b = $("#play"); if (b.dataset.state === String(playing)) return;
  b.dataset.state = String(playing); b.innerHTML = icon(playing ? "pause" : "play"); b.ariaLabel = playing ? "Pause" : "Play";
}
function seek(t) { S.t = Math.max(0, Math.min(S.total, t)); ed()?.seek(S.t); movePlayhead(); }
function togglePlay() {
  if (!ed()) return;
  if (ed().isPlaying()) ed().pause(); else ed().play(S.t);
}
// the preview takes the video's shape and fills the stage (as large as fits, centred)
function fitScreen(fmt) {
  const sc = $("#screen"), box = $(".stage-in"), [W, H] = canvasSize(fmt || (S.mode === "new" ? N.format : undefined));
  const aw = Math.max(120, box.clientWidth - 8), ah = Math.max(120, box.clientHeight - 8);
  const w = Math.min(aw, ah * W / H), h = w * H / W;
  sc.style.width = w + "px"; sc.style.height = h + "px";
  frames().forEach((f) => { f.style.width = W + "px"; f.style.height = H + "px"; f.style.transform = `scale(${h / H})`; });
}

// ---------------------------------------------------------------- timeline drawing
const X = (t) => t * S.pps;
function drawTimeline() {
  const W = Math.ceil(X(S.total)) + 200;
  $("#content").style.width = W + "px";
  drawRuler(W);
  const lanes = {};
  document.querySelectorAll("#content .cutzone, #content .markband").forEach((m) => m.remove());
  document.querySelectorAll("#content .lane").forEach((l) => { lanes[l.dataset.lane] = l; if (l.dataset.lane === "video") l.querySelectorAll(".cutmark, .clipb").forEach((m) => m.remove()); else if (l.dataset.lane === "audio") l.querySelectorAll(".wd").forEach((m) => m.remove()); else l.innerHTML = ""; });
  const bad = warnings();

  // cards, chips, text
  S.spec.cards.forEach((c, i) => {
    const [s, e] = span(c);
    const kind = TRACK(c) === "chips" ? "chip" : TRACK(c) === "text" ? "text" : "card";
    const b = el("div", { class: `blk ${kind}${S.sel?.kind === "card" && S.sel.i === i ? " sel" : ""}${bad.ids.has(i) ? " bad" : ""}`,
      style: `left:${X(s)}px;width:${Math.max(6, X(e - s))}px`, title: `${c.type} · ${s.toFixed(2)}–${e.toFixed(2)}s` },
      el("span", { class: "h l" }), kind === "card" ? el("span", { class: "bt" }, c.type) : null, el("span", { class: "bl" }, label(c)), el("span", { class: "h r" }));
    refs(c).forEach((r, k) => {
      const mk = el("i", { class: "mk", style: `left:${X(r.get() - s)}px`, title: `${r.label} · ${r.get().toFixed(2)}s` });
      mk.dataset.ref = k; b.append(mk);
    });
    b.addEventListener("pointerdown", (ev) => startDrag(ev, i, b));
    lanes[TRACK(c)].append(b);
  });

  // end screen
  if (S.spec.endcard) {
    const b = el("div", { class: `blk end${S.sel?.kind === "end" ? " sel" : ""}`, style: `left:${X(S.dur)}px;width:${X(S.total - S.dur)}px` },
      el("span", { class: "bl" }, "End screen"));
    b.addEventListener("pointerdown", (ev) => { ev.stopPropagation(); select({ kind: "end" }); });
    lanes.cards.append(b);
  }
  const ez = $("#endzone"); ez.hidden = !S.spec.endcard;
  ez.style.left = X(S.dur) + "px"; ez.style.width = X(S.total - S.dur) + "px";

  // captions
  groupRanges().forEach(([a, b], gi) => {
    const [s, e] = groupSpan(gi);
    const blk = el("div", { class: `blk cap${S.sel?.kind === "cap" && S.sel.g === gi ? " sel" : ""}`, style: `left:${X(s)}px;width:${Math.max(6, X(e - s) - 2)}px` });
    for (let i = a; i <= b; i++) if (!isDrop(i)) blk.append(el("span", { class: isKw(i) ? "kw" : "" }, wordText(i)), " ");
    blk.addEventListener("pointerdown", (ev) => { ev.stopPropagation(); S.selWord = null; select({ kind: "cap", g: gi }); seek(s + 0.05); });
    lanes.caps.append(blk);
  });

  // takeovers (gradient cutaways)
  (S.spec.takeovers || []).forEach((k, i) => {
    const [s0, e0] = span(k);
    const sel = S.sel?.kind === "tk" && S.sel.i === i;
    const mode = isReelFmt() ? (k.mode || "full") : "full";
    const what = k.stat ? String(k.stat.value ?? "") : (k.title || k.kicker || "");
    const b = el("div", { class: `blk tk${sel ? " sel" : ""}${bad.tk.has(i) ? " bad" : ""}${S.filling?.has(k) ? " filling" : ""}`, style: `left:${X(s0)}px;width:${Math.max(8, X(e0 - s0))}px`,
      title: `Takeover (${mode}) · ${s0.toFixed(2)}–${e0.toFixed(2)}s` },
      el("span", { class: "h l" }), el("span", { class: "bt" }, mode === "pip" ? "PIP" : "FULL"), el("span", { class: "bl" }, String(what).replace(/\*/g, "")), el("span", { class: "h r" }));
    refs(k).forEach((r, j) => { const mk = el("i", { class: "mk", style: `left:${X(r.get() - s0)}px`, title: `${r.label} · ${r.get().toFixed(2)}s` }); mk.dataset.ref = j; b.append(mk); });
    b.addEventListener("pointerdown", (ev) => startDrag(ev, i, b, "takeovers"));
    lanes.tk.append(b);
  });

  // effects (punch / push / flash) and sounds (pop / tick)
  (S.spec.fx || []).forEach((f, i) => {
    const I = FX_INFO[f.kind] || { icon: "✦", label: f.kind };
    const [s0, e0] = fxSpan(f);
    const sel = S.sel?.kind === "fx" && S.sel.i === i;
    const w = X(e0 - s0);
    const b = el("div", { class: `blk fx ${f.kind}${sel ? " sel" : ""}`, style: `left:${X(s0)}px;width:${Math.max(f.kind === "flash" ? 14 : 8, w)}px`,
      title: `${I.label}${f.to ? ` ${f.to}×` : ""} · ${s0.toFixed(2)}–${e0.toFixed(2)}s` },
      f.kind !== "flash" ? el("span", { class: "h l" }) : null,
      el("span", { class: "fi" }, I.icon), w > 50 ? el("span", { class: "bl" }, `${I.short}${f.to ? ` ${+(+f.to).toFixed(2)}×` : ""}`) : null,
      f.kind !== "flash" ? el("span", { class: "h r" }) : null);
    b.addEventListener("pointerdown", (ev) => startTimedDrag(ev, "fx", i));
    lanes.fx.append(b);
  });
  const nT = ovTracks();
  document.querySelectorAll('[data-lane="ov"]').forEach((e) => e.style.setProperty("--ovrows", nT));
  (S.spec.overlays || []).forEach((o, i) => {
    const sel = S.sel?.kind === "ov" && S.sel.i === i, k = o.track || 1;
    const b = el("div", { class: `blk ov ${o.mode === "pip" ? "pip" : "full"}${sel ? " sel" : ""}`,
      style: `left:${X(o.t)}px;width:${Math.max(10, X(o.dur))}px;top:${(nT - k) * OV_ROW + 3}px;height:${OV_ROW - 6}px;bottom:auto`,
      title: `${o.name || "Overlay"} · V${k + 1} · ${o.t.toFixed(2)}–${(o.t + o.dur).toFixed(2)}s · ${o.muted === false ? "sound on" : "muted"}` },
      el("span", { class: "h l" }), el("span", { class: "bt" }, `V${k + 1}`), el("span", { class: "bl" }, `${o.muted === false ? "🔊 " : ""}${o.name || "Overlay"}`), el("span", { class: "h r" }));
    b.addEventListener("pointerdown", (ev) => startOvDrag(ev, i));
    lanes.ov.append(b);
  });
  (S.spec.redactions || []).forEach((r, i) => {
    const sel = S.sel?.kind === "rd" && S.sel.i === i;
    const b = el("div", { class: `blk rd${sel ? " sel" : ""}`, style: `left:${X(r.t)}px;width:${Math.max(10, X(r.dur))}px`,
      title: `${RD_TYPES[r.type] || "Blur"} · ${r.t.toFixed(2)}–${(r.t + r.dur).toFixed(2)}s${r.track ? " · follows movement" : ""}` },
      el("span", { class: "h l" }), el("span", { class: "bl" }, `${RD_TYPES[r.type] || "Blur"}${r.track ? " ↝" : ""}`), el("span", { class: "h r" }));
    b.addEventListener("pointerdown", (ev) => startRdDrag(ev, i));
    lanes.rd.append(b);
  });
  (S.spec.sfx || []).forEach((f, i) => {
    const sel = S.sel?.kind === "sfx" && S.sel.i === i;
    const b = el("div", { class: `blk sfx${sel ? " sel" : ""}`, style: `left:${X(f.t)}px;width:${Math.max(30, X(SFX_LEN[f.kind] || 0.2))}px`,
      title: `${f.kind} sound at ${f.t.toFixed(2)}s, volume ${f.volume ?? SFX_VOL[f.kind]}` }, `♪ ${f.kind}`);
    b.addEventListener("pointerdown", (ev) => startTimedDrag(ev, "sfx", i));
    lanes.sfx.append(b);
  });

  // zoom (from the cut list): select a block to change its scale; Apply re-renders the base edit
  (S.edl || []).forEach((z, i) => {
    const pend = S.zoomEdits[i] != null && Math.abs(S.zoomEdits[i] - z.zoom) > 0.0005;
    const zv = pend ? S.zoomEdits[i] : z.zoom;
    const zin = zv > 1.001;
    const w = X(z.end - z.start);
    const sel = S.sel?.kind === "zoom" && S.sel.i === i;
    const b = el("div", { class: `zm ${zin ? "in" : "flat"}${pend ? " pending" : ""}${sel ? " sel" : ""}`, style: `left:${X(z.start)}px;width:${Math.max(4, w - 2)}px`,
      title: `${zin ? `Zoom ${zv.toFixed(2)}×` : "No zoom (1.0×)"}${pend ? ` (was ${z.zoom.toFixed(2)}×, not applied yet)` : ""}${z.pan ? " with pan" : ""} · ${z.start.toFixed(2)}–${z.end.toFixed(2)}s` },
      w > 34 ? (zin ? [el("span", { class: "zi" }, "⤢"), `ZOOM ${+zv.toFixed(2)}×${pend ? " •" : ""}${z.pan ? " · PAN" : ""}`] : (w > 60 ? `1.0×${pend ? " •" : ""}` : "")) : null);
    b.addEventListener("pointerdown", (ev) => { ev.stopPropagation(); if (S.cut) { const k = clipAt(z.start + 0.02); if (k != null) select({ kind: "clip", i: k }); } else select({ kind: "zoom", i }); seek(z.start + 0.02); });
    lanes.zoom.append(b);
  });
  drawClips(lanes.video);
  drawFilm();

  // words
  const showText = S.pps >= 70;
  S.words.forEach((w, i) => {
    const d = el("div", { class: `wd${isKw(i) ? " kw" : ""}${isDrop(i) ? " drop" : ""}`, style: `left:${X(w.start)}px;width:${Math.max(2, X(w.end - w.start))}px`,
      title: `${i} · ${w.text} · ${w.start.toFixed(2)}s` }, showText ? wordText(i) : "");
    d.addEventListener("pointerdown", (ev) => { ev.stopPropagation(); seek(w.start); });
    lanes.audio.append(d);          // words sit over the waveform
  });

  drawWave();
  laneCounts();
  movePlayhead();
  const n = bad.list.length;
  $("#warn").textContent = n ? `⚠ ${n} timing ${n === 1 ? "issue" : "issues"}: ${bad.list[0]}${n > 1 ? " …" : ""}` : "";
}
// track headers show how many items each track has; empty optional tracks shrink to a slim row
function laneCounts() {
  const cards = S.spec.cards || [];
  const n = { tk: (S.spec.takeovers || []).length, text: cards.filter((c) => c.type === "text").length, chips: cards.filter((c) => c.type === "chip").length,
    cards: cards.filter((c) => TRACK(c) === "cards").length, caps: groupRanges().length, fx: (S.spec.fx || []).length, sfx: (S.spec.sfx || []).length, rd: (S.spec.redactions || []).length, ov: (S.spec.overlays || []).length,
    zoom: (S.edl || []).filter((z) => z.zoom > 1.001).length };
  const slimmable = new Set(["tk", "text", "chips", "fx", "sfx", "rd", "ov"]);
  Object.entries(n).forEach(([k, v]) => {
    const lab = document.querySelector(`.tl-labels .lab[data-lane="${k}"]`), lane = document.querySelector(`#content .lane[data-lane="${k}"]`);
    if (!lab) return;
    const c = lab.querySelector(".cnt"); if (c) c.textContent = v ? String(v) : "";
    const slim = slimmable.has(k) && !v && S.mode !== "new";
    lab.classList.toggle("slim", slim); lane?.classList.toggle("slim", slim);
  });
}
function drawRuler(W) {
  const r = $("#ruler"); r.innerHTML = "";
  const step = S.pps >= 120 ? 1 : S.pps >= 50 ? 2 : S.pps >= 25 ? 5 : 10;
  for (let t = 0; t <= S.total + step; t += step) r.append(el("div", { class: "tick", style: `left:${X(t)}px` }, fmtT(t).replace(/\.00$/, "")));
  if (S.pps >= 50) for (let t = 0.5; t <= S.total; t += step === 1 ? 0.5 : 1) if (t % step) r.append(el("div", { class: "tick minor", style: `left:${X(t)}px` }));
}
function drawWave() {
  const c = $("#wave"), lane = c.parentElement;
  const W = Math.min(Math.ceil(X(S.dur)), 32000), H = lane.clientHeight;
  const dpr = window.devicePixelRatio || 1;
  c.width = W * dpr; c.height = H * dpr; c.style.width = W + "px";
  const g = c.getContext("2d"); g.scale(dpr, dpr);
  g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--wave").trim() || "#9d86f6";
  const p = S.peaks; if (!p.length) return;
  for (let x = 0; x < W; x++) {
    const a = Math.floor((x / S.pps) * S.perSec), b = Math.max(a + 1, Math.floor(((x + 1) / S.pps) * S.perSec));
    let m = 0; for (let k = a; k < b && k < p.length; k++) m = Math.max(m, p[k]);
    const h = Math.max(1, Math.sqrt(m) * (H - 6));
    g.fillRect(x, (H - h) / 2, 1, h);
  }
}
function drawFilm() {
  const c = $("#film"), lane = c.parentElement, F = S.film;
  const W = Math.min(Math.ceil(X(S.dur)), 32000), H = lane.clientHeight;
  const dpr = window.devicePixelRatio || 1;
  c.width = W * dpr; c.height = H * dpr; c.style.width = W + "px";
  if (!F || !F.img || !F.img.complete) return;
  const g = c.getContext("2d"); g.scale(dpr, dpr);
  const tw = Math.round(H * F.w / F.h);                 // one thumbnail's width at lane height
  for (let x = 0; x < W; x += tw) {
    const k = Math.min(F.count - 1, Math.floor((x + tw / 2) / S.pps / F.step));
    g.drawImage(F.img, k * F.w, 0, F.w, F.h, x, 0, tw, H);
  }
}
function movePlayhead(follow) {
  if (S.sel?.kind === "card" || S.sel?.kind === "rd" || S.sel?.kind === "ov") drawOverlay();
  $("#playhead").style.left = X(S.t) + "px";
  $("#tc").innerHTML = `<b>${fmtT(S.t)}</b> / ${fmtT(S.total)}`;
  const ph = $("#phTime"); if (ph) ph.textContent = fmtT(S.t);
  if (follow && S.playing) {
    const sc = $("#scroller"), x = X(S.t);
    if (x > sc.scrollLeft + sc.clientWidth - 80 || x < sc.scrollLeft) sc.scrollLeft = x - 120;
  }
}

// house rules: never two card groups at once; leave ~0.2 s before the next card
function warnings() {
  const ids = new Set(), list = [], tk = new Set();
  (S.spec.takeovers || []).forEach((k, i) => {
    const [a, b] = span(k);
    S.spec.cards.forEach((c, j) => { const [s, e] = span(c); if (TRACK(c) === "cards" && s < b - 0.05 && e > a + 0.05) { tk.add(i); ids.add(j); list.push(`a ${c.type} card is on screen during a takeover at ${a.toFixed(1)}s`); } });
  });
  const cards = S.spec.cards.map((c, i) => ({ c, i, s: span(c) })).filter((x) => TRACK(x.c) === "cards").sort((a, b) => a.s[0] - b.s[0]);
  for (let k = 0; k + 1 < cards.length; k++) {
    const a = cards[k], b = cards[k + 1];
    if (b.s[0] < a.s[1] - 0.01) { ids.add(a.i); ids.add(b.i); list.push(`${a.c.type} and ${b.c.type} overlap at ${b.s[0].toFixed(1)}s`); }
  }
  S.spec.cards.forEach((c, i) => {
    const [s, e] = span(c);
    if (e > S.dur + 0.001 || s < 0) { ids.add(i); list.push(`${c.type} runs past the video`); }
    if (refs(c).some((r) => typeof c.out === "number" && r.get() > c.out - 0.05)) { ids.add(i); list.push(`${c.type} has a part after it leaves`); }
  });
  return { ids, list, tk };
}

// ---------------------------------------------------------------- dragging
function wordSnaps() { return S.words.map((w) => w.start - 0.1); }
function snapTo(v, targets) {
  if (!$("#snap").checked || window.__alt) return [v, null];
  const tol = 8 / S.pps;
  let best = null, bd = tol;
  for (const t of targets) { const d = Math.abs(t - v); if (d < bd) { bd = d; best = t; } }
  return best == null ? [v, null] : [best, best];
}
function showSnap(t) {
  let s = $("#content .snapline");
  if (t == null) { s?.remove(); return; }
  if (!s) { s = el("div", { class: "snapline" }); $("#content").append(s); }
  s.style.left = X(t) + "px";
}
function startDrag(ev, i, blk, key = "cards") {
  ev.stopPropagation(); ev.preventDefault();
  const list = S.spec[key], kind = key === "cards" ? "card" : "tk";
  const c = list[i];
  const mode = ev.target.classList.contains("mk") ? "mk" : ev.target.classList.contains("l") ? "l" : ev.target.classList.contains("r") ? "r" : "m";
  const refIdx = mode === "mk" ? +ev.target.dataset.ref : -1;
  const orig = clone(c), x0 = ev.clientX;
  const [s0, e0] = span(orig), f0 = firstRef(orig), l0 = lastRef(orig);
  const outSnaps = () => list.filter((o, j) => j !== i && (key !== "cards" || TRACK(o) === TRACK(c))).map((o) => span(o)[0] - 0.2).concat(S.words.map((w) => w.end + 0.1));
  let moved = false;
  if (!(S.sel?.kind === kind && S.sel.i === i)) { S.sel = { kind, i }; drawInspector(); }

  const mv = (e) => {
    const d = (e.clientX - x0) / S.pps;
    if (!moved && Math.abs(e.clientX - x0) < 3) return;
    if (!moved) { snapshot(); moved = true; }
    const cur = clone(orig);
    let snapAt = null;
    if (mode === "m") {
      let nf = f0 + d; [nf, snapAt] = snapTo(nf, wordSnaps());
      let dd = nf - f0;
      dd = Math.max(dd, 0.1 - f0);
      const end = (typeof orig.out === "number" ? orig.out : l0 + 0.5);
      dd = Math.min(dd, S.dur - end);
      shiftCard(cur, dd);
    } else if (mode === "l") {
      let nf = f0 + d; [nf, snapAt] = snapTo(nf, wordSnaps());
      const outV = typeof orig.out === "number" ? orig.out : S.dur;
      nf = Math.max(0.1, Math.min(nf, outV - 0.4));
      const k = (outV - nf) / Math.max(0.01, outV - f0);
      refs(cur).forEach((r) => r.set(r2(nf + (r.get() - f0) * k)));
    } else if (mode === "r") {
      let no = (typeof orig.out === "number" ? orig.out : S.dur) + d; [no, snapAt] = snapTo(no, outSnaps());
      cur.out = r2(Math.max(l0 + 0.3, Math.min(S.dur, no)));
    } else {
      const r = refs(cur)[refIdx];
      let nv = refs(orig)[refIdx].get() + d; [nv, snapAt] = snapTo(nv, wordSnaps());
      const hi = typeof orig.out === "number" ? orig.out - 0.1 : S.dur;
      r.set(r2(Math.max(0.05, Math.min(hi, nv))));
    }
    list[i] = cur;
    showSnap(snapAt);
    drawTimeline();
    if (S.sel?.kind === kind && S.sel.i === i) refreshTiming();
  };
  const up = () => {
    removeEventListener("pointermove", mv); removeEventListener("pointerup", up); showSnap(null);
    if (moved) { change(); if (mode !== "r") seek(firstRef(list[i])); }
    else { select({ kind, i }); seek(Math.max(s0, firstRef(c))); }
  };
  addEventListener("pointermove", mv); addEventListener("pointerup", up);
}

// scrubbing on the ruler and empty lane space
function scrubStart(ev) {
  if (ev.target.closest(".blk, .wd")) return;
  const rect = $("#content").getBoundingClientRect();
  const at = (e) => (e.clientX - rect.left) / S.pps;
  if (ev.target.closest(".lane, .ruler")) { if (!ev.target.closest(".ruler")) select(null); }
  const wasPlaying = S.playing; if (wasPlaying) ed()?.pause();
  seek(at(ev));
  const mv = (e) => seek(at(e));
  const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); };
  addEventListener("pointermove", mv); addEventListener("pointerup", up);
}

function select(sel) { S.sel = sel; if (sel?.kind !== "cap") S.selWord = null; drawTimeline(); drawInspector(); drawOverlay(); }

// ---------------------------------------------------------------- inspector
function drawInspector() { drawInspectorInner(); decorateButtons($("#insp")); }
function drawInspectorInner() {
  const box = $("#insp"); box.innerHTML = "";
  if (!S.sel) return box.append(reelPanel());
  if (S.sel.kind === "card") return box.append(cardPanel(S.sel.i));
  if (S.sel.kind === "cap") return box.append(capPanel(S.sel.g));
  if (S.sel.kind === "end") return box.append(endPanel());
  if (S.sel.kind === "zoom") return box.append(S.cut ? clipPanel(clipAt(S.t) ?? 0) : zoomPanel(S.sel.i));
  if (S.sel.kind === "clip") return box.append(clipPanel(S.sel.i));
  if (S.sel.kind === "tk") return S.spec.takeovers?.[S.sel.i] ? box.append(tkPanel(S.sel.i)) : null;
  if (S.sel.kind === "fx") return S.spec.fx[S.sel.i] ? box.append(fxPanel(S.sel.i)) : null;
  if (S.sel.kind === "sfx") return S.spec.sfx[S.sel.i] ? box.append(sfxPanel(S.sel.i)) : null;
  if (S.sel.kind === "ov") return (S.spec.overlays || [])[S.sel.i] ? box.append(ovPanel(S.sel.i)) : null;
  if (S.sel.kind === "rd") return (S.spec.redactions || [])[S.sel.i] ? box.append(rdPanel(S.sel.i)) : null;
}

// redraw unless the person is typing in the inspector
function drawInspectorSafe() { if (!document.activeElement?.closest?.("#insp")) drawInspector(); }

// an input bound to obj[key]; one undo step per focus
function bind(input, get, set, { num = false, live = true } = {}) {
  let snap = false;
  input.value = get() ?? "";
  input.addEventListener("focus", () => (snap = false));
  input.addEventListener(live ? "input" : "change", () => {
    if (!snap) { snapshot(); snap = true; }
    let v = input.value;
    if (num) { if (v === "") return; v = parseFloat(v); if (isNaN(v)) return; }
    set(v); change({ inspector: false });
  });
  return input;
}
const row = (lab, ...kids) => el("div", { class: "row" }, el("label", {}, lab), ...kids);
const sec = (title, ...kids) => el("div", { class: "sec" }, el("div", { class: "sh" }, ...[].concat(title)), ...kids);

function timeInput(get, set) {
  const inp = el("input", { type: "number", step: "0.01" });
  bind(inp, () => (get() == null ? "" : get()), (v) => set(r2(v)), { num: true });
  const here = el("button", { class: "small", title: "Set to the playhead", onclick: () => { snapshot(); set(r2(S.t)); change(); } }, "◆ playhead");
  const go = el("button", { class: "small", title: "Jump to this time", onclick: () => get() != null && seek(get()) }, "Go");
  return [inp, el("span", { class: "unit" }, "s"), here, go];
}

function cardPanel(i) {
  const c = S.spec.cards[i];
  const wrap = el("div");
  const [s, e] = span(c);
  wrap.append(
    el("h2", {}, c.type === "text" ? "Text" : c.type === "chip" ? "Chip" : "Card", el("span", { class: "tag" }, c.type)),
    el("div", { class: "sub" }, `${s.toFixed(2)}s – ${e.toFixed(2)}s · ${(e - s).toFixed(1)}s on screen`),
    el("div", { class: "btns" },
      el("button", { onclick: () => seek(firstRef(c)) }, "Go to start"),
      el("button", { onclick: () => { snapshot(); const d = clone(c); const len = e - s; shiftCard(d, Math.min(len + 0.3, S.dur - (d.out ?? S.dur))); S.spec.cards.push(d); S.sel = { kind: "card", i: S.spec.cards.length - 1 }; change(); } }, "Duplicate"),
      el("button", { class: "danger", onclick: () => deleteCard(i) }, "Delete")),
  );

  if (c.type === "text") wrap.append(textSection(c));
  if (c.type === "chip") wrap.append(sec("Content", row("Text", bind(el("input", { type: "text" }), () => c.text, (v) => (c.text = v))),
    el("div", { class: "hint" }, "Wrap words in *stars* for the gradient. Use -> for an arrow.")));
  if (c.type !== "text" && c.type !== "chip") {
    const content = el("div");
    form(c, content, c, []);
    wrap.append(sec("Content", content));
  }

  const timing = el("div", { id: "timing" });
  wrap.append(sec(["Timing", el("span", { class: "hint" }, "◆ markers on the block can be dragged")], timing));
  fillTiming(timing, c);

  if (c.type !== "text") {
    const def = { chip: 288, questions: 1240, hub: 1200, statement: 1222, compare: 1230, steps: 1232, feature: 1232, tiles: 1210, connect: 1192, chat: 1203, task: 1240 }[c.type] || 1230;
    wrap.append(sec("Position", posControl(c, def)));
  }

  wrap.append(placeSection(c));
  const ta = el("textarea", { class: "json", spellcheck: false });
  ta.value = JSON.stringify(c, null, 2);
  wrap.append(sec(["Raw JSON", el("button", { class: "small", onclick: () => {
    try { const v = JSON.parse(ta.value); snapshot(); S.spec.cards[i] = v; change(); } catch (err) { toast("That isn't valid JSON: " + err.message); }
  } }, "Apply")], ta));
  return wrap;
}
function fillTiming(box, c) {
  box.innerHTML = "";
  refs(c).forEach((r) => box.append(row(r.label === "t" ? "In (t)" : r.label, ...timeInput(r.get, r.set))));
  box.append(row("Out", ...timeInput(() => c.out ?? null, (v) => (c.out = v))));
  if (c.out == null) box.append(el("div", { class: "hint" }, "No out time: it stays to the end of the video."));
}
function refreshTiming() { const t = $("#timing"); if (t && S.sel?.kind === "card") fillTiming(t, S.spec.cards[S.sel.i]); if (t && S.sel?.kind === "tk") fillTiming(t, S.spec.takeovers[S.sel.i]); }

// landscape: cards sit in the side panel; "y" is the group's vertical centre
function yControl(c) {
  const F = fmtOf(), def = c.type === "chip" ? F.chipY : F.cy;
  const num = el("input", { type: "number", step: "1" }), rng = el("input", { type: "range", min: String(Math.min(F.chipY, F.range[0])), max: String(F.range[1]), step: "2", style: "flex:1;min-width:0" });
  let snap = false;
  const sync = () => { num.value = c.y ?? def; rng.value = c.y ?? def; };
  const set = (v) => { if (!snap) { snapshot(); snap = true; } c.y = Math.round(+v); sync(); change({ inspector: false }); };
  num.addEventListener("input", () => num.value !== "" && set(num.value));
  rng.addEventListener("input", () => set(rng.value));
  [num, rng].forEach((x) => x.addEventListener("focus", () => (snap = false)));
  rng.addEventListener("pointerdown", () => (snap = false));
  sync();
  const presets = el("div", { class: "btns" }, ...F.presets.map(([n, v]) =>
    el("button", { class: "small", onclick: () => { snap = false; set(v); } }, n)),
    el("button", { class: "small", onclick: () => { snapshot(); delete c.y; sync(); change({ inspector: false }); } }, "Default"));
  return el("div", {}, row("Vertical centre", num, rng), presets, el("div", { class: "hint" }, F.hint));
}
const posControl = (c, def) => (isPanel() ? yControl(c) : topControl(c, def));

function topControl(c, def) {
  const num = el("input", { type: "number", step: "1" }), rng = el("input", { type: "range", min: "120", max: "1760", step: "2", class: "grow" });
  let snap = false;
  const sync = () => { num.value = c.top ?? def; rng.value = c.top ?? def; };
  const set = (v) => { if (!snap) { snapshot(); snap = true; } c.top = Math.round(+v); sync(); change({ inspector: false }); };
  num.addEventListener("input", () => num.value !== "" && set(num.value));
  rng.addEventListener("input", () => set(rng.value));
  [num, rng].forEach((x) => x.addEventListener("focus", () => (snap = false)));
  rng.addEventListener("pointerdown", () => (snap = false));
  sync();
  const presets = el("div", { class: "btns" }, ...[["Top", 288], ["Upper", 560], ["Under captions", 1240], ["Low", 1500]].map(([n, v]) =>
    el("button", { class: "small", onclick: () => { snap = false; set(v); } }, n)),
    el("button", { class: "small", onclick: () => { snapshot(); delete c.top; sync(); change({ inspector: false }); } }, "Default"));
  return el("div", {}, row("Top (px)", num, rng), presets,
    el("div", { class: "hint" }, "Captions sit at y≈990–1090. Cards start from y≈1190; chips sit at y≈288."));
}

function textSection(c) {
  const ta = el("input", { type: "text" });
  return sec("Content",
    row("Text", bind(ta, () => c.text, (v) => (c.text = v))),
    el("div", { class: "hint", style: "margin:-2px 0 8px 118px" }, "Wrap words in *stars* for the brand gradient."),
    row("Kicker", bind(el("input", { type: "text", placeholder: "Optional small line above" }), () => c.kicker || "", (v) => { if (v) c.kicker = v; else delete c.kicker; })),
    row("Style", selectOf([["glass", "Glass card"], ["bare", "Text only"]], () => c.style || "glass", (v) => (c.style = v))),
    row("Animation", selectOf([["words", "Word by word"], ["rise", "All at once"], ["pop", "Pop"]], () => c.anim || "words", (v) => (c.anim = v))),
    row("Size", bind(el("input", { type: "number", step: "2" }), () => c.size ?? 64, (v) => (c.size = v), { num: true }), el("span", { class: "unit" }, "px")),
    posControl(c, 1240),
  );
}
function selectOf(opts, get, set) {
  const s = el("select", {}, ...opts.map(([v, n]) => el("option", { value: v }, n)));
  s.value = get();
  s.addEventListener("change", () => { snapshot(); set(s.value); change({ inspector: false }); });
  return s;
}

// generic editor for any card's content: strings, lists, nested objects; time keys live in Timing
const ICON_KEYS = new Set(["icon", "badge_icon"]);
const ICON_LISTS = new Set(["left", "right"]);
const LOGO_KEYS = new Set(["logo"]);
const LOGO_LISTS = new Set(["sources", "satellites"]);
const SKIP = new Set(["type", "out", "top", "times", "leads", "mode", "y", "x"]);
function listFor(card, key, inList) {
  if (key === "center") return card.type === "connect" ? "dl-logos" : "dl-icons";
  if (inList) return ICON_LISTS.has(key) ? "dl-icons" : LOGO_LISTS.has(key) ? "dl-logos" : null;
  return ICON_KEYS.has(key) ? "dl-icons" : LOGO_KEYS.has(key) ? "dl-logos" : null;
}
function pretty(k) { return k.replace(/_/g, " ").replace(/^./, (m) => m.toUpperCase()); }
function form(obj, box, card, path) {
  for (const k of Object.keys(obj)) {
    if (path.length === 0 && (SKIP.has(k) || isTimeKey(k))) continue;
    if (path.length > 0 && k === "t") continue;
    const v = obj[k];
    if (typeof v === "string") {
      const inp = el("input", { type: "text" });
      const dl = listFor(card, k, false); if (dl) inp.setAttribute("list", dl);
      box.append(row(pretty(k), bind(inp, () => obj[k], (x) => (obj[k] = x))));
    } else if (typeof v === "number") {
      box.append(row(pretty(k), bind(el("input", { type: "number", step: "any" }), () => obj[k], (x) => (obj[k] = x), { num: true })));
    } else if (typeof v === "boolean") {
      const cb = el("input", { type: "checkbox" }); cb.checked = v;
      cb.addEventListener("change", () => { snapshot(); obj[k] = cb.checked; change({ inspector: false }); });
      box.append(row(pretty(k), cb));
    } else if (Array.isArray(v) && v.every((x) => typeof x === "string")) {
      box.append(stringList(obj, k, card, path));
    } else if (Array.isArray(v) && v.every((x) => x && typeof x === "object")) {
      box.append(objectList(obj, k, card, path));
    } else if (v && typeof v === "object") {
      const fs = el("div", { class: "fs" }, el("div", { class: "fh" }, pretty(k)));
      form(v, fs, card, path.concat(k)); box.append(fs);
    }
  }
  if (path.length === 0 && Array.isArray(card.leads)) box.append(objectList(card, "leads", card, path, true));
}
// keep a card's `times` in step with the list it times (questions, steps, tiles)
function timedList(card, arr) { return Array.isArray(card.times) && card.times.length === arr.length; }
function stringList(obj, k, card, path) {
  const fs = el("div", { class: "fs" }, el("div", { class: "fh" }, pretty(k)));
  obj[k].forEach((_, j) => {
    const inp = el("input", { type: "text", class: "grow" });
    const dl = listFor(card, k, true); if (dl) inp.setAttribute("list", dl);
    fs.append(el("div", { class: "row" }, bind(inp, () => obj[k][j], (x) => (obj[k][j] = x)),
      el("button", { class: "small", title: "Remove", onclick: () => { snapshot(); if (path.length === 0 && timedList(card, obj[k])) card.times.splice(j, 1); obj[k].splice(j, 1); change(); } }, "✕")));
  });
  fs.append(el("button", { class: "small", onclick: () => {
    snapshot();
    if (path.length === 0 && timedList(card, obj[k])) card.times.push(r2((card.times.at(-1) ?? S.t) + 0.6));
    obj[k].push(obj[k].at(-1) ?? ""); change();
  } }, "+ Add"));
  return fs;
}
function objectList(obj, k, card, path, isLeads) {
  const fs = el("div", { class: "fs" }, el("div", { class: "fh" }, isLeads ? "Lead words (cycle before the main word)" : pretty(k)));
  obj[k].forEach((item, j) => {
    const sub = el("div", { class: "fs" }, el("div", { class: "fh" }, `${pretty(k).replace(/s$/, "")} ${j + 1}`,
      el("button", { class: "small", onclick: () => { snapshot(); if (path.length === 0 && timedList(card, obj[k])) card.times.splice(j, 1); obj[k].splice(j, 1); change(); } }, "Remove")));
    form(item, sub, card, path.concat(k, j));
    fs.append(sub);
  });
  fs.append(el("button", { class: "small", onclick: () => {
    snapshot();
    const n = clone(obj[k].at(-1) ?? (isLeads ? { text: "Word", t: S.t } : {}));
    if (typeof n.t === "number" || isLeads) n.t = r2((n.t ?? S.t) + 0.6);
    if (path.length === 0 && timedList(card, obj[k])) card.times.push(r2((card.times.at(-1) ?? S.t) + 0.6));
    obj[k].push(n); change();
  } }, "+ Add"));
  return fs;
}

function capPanel(gi) {
  const ranges = groupRanges(); const [a, b] = ranges[gi] || [0, 0];
  const [s, e] = groupSpan(gi);
  const wrap = el("div", {}, el("h2", {}, "Caption", el("span", { class: "tag" }, `${gi + 1} of ${ranges.length}`)));
  wrap.append(el("div", { class: "sub" }, `${s.toFixed(2)}s – ${e.toFixed(2)}s · timed to the speech`));
  const chips = el("div", { class: "words" });
  for (let i = a; i <= b; i++) {
    const ch = el("span", { class: `wchip${isKw(i) ? " kw" : ""}${isDrop(i) ? " drop" : ""}${S.selWord === i ? " sel" : ""}`, title: `Word ${i} · ${S.words[i].start.toFixed(2)}s` },
      wordText(i), fixOf(i) != null ? el("span", { class: "orig" }, S.words[i].text) : null);
    ch.addEventListener("click", () => { S.selWord = i; seek(S.words[i].start); drawInspector(); });
    chips.append(ch);
  }
  wrap.append(chips);
  wrap.append(el("div", { class: "btns" },
    el("button", { disabled: gi === 0, onclick: () => mergeGroups(gi - 1) }, "← Merge with previous"),
    el("button", { disabled: gi >= ranges.length - 1, onclick: () => mergeGroups(gi) }, "Merge with next →"),
    el("button", { onclick: () => seek(s) }, "Go to caption")));

  if (S.selWord != null && S.selWord >= a && S.selWord <= b) {
    const i = S.selWord;
    const inp = el("input", { type: "text" });
    bind(inp, () => wordText(i), (v) => {
      cap().fix = cap().fix || {};
      if (v === S.words[i].text || v === "") delete cap().fix[i]; else cap().fix[i] = v;
    });
    wrap.append(sec(`Word: “${S.words[i].text}”`,
      row("Shown as", inp),
      el("div", { class: "btns" },
        el("button", { class: isKw(i) ? "on" : "", onclick: () => toggleIn("keywords", i) }, isKw(i) ? "★ Keyword" : "☆ Make keyword"),
        el("button", { class: isDrop(i) ? "on" : "", onclick: () => toggleIn("drop", i) }, isDrop(i) ? "Hidden" : "Hide word"),
        el("button", { disabled: i === a, onclick: () => splitAt(gi, i) }, "Start new caption here")),
      el("div", { class: "hint" }, "Fix spelling and product names here (UK spelling). Hide words folded into a fix, e.g. “high level” → GoHighLevel.")));
  } else {
    wrap.append(el("div", { class: "hint" }, "Click a word to fix its text, make it a keyword, hide it, or split the caption."));
  }
  return wrap;
}
function toggleIn(key, i) {
  snapshot();
  const list = (cap()[key] = cap()[key] || []);
  const k = list.indexOf(i);
  if (k >= 0) list.splice(k, 1);
  else { list.push(i); list.sort((x, y) => x - y); }
  if (key === "keywords" && k >= 0 && isKw(i)) toast("This word is a keyword through keyword_words in reel.json.");
  change();
}
function splitAt(gi, i) {
  snapshot(); materialiseGroups();
  const g = cap().groups[gi];
  cap().groups.splice(gi, 1, [g[0], i - 1], [i, g[1]]);
  S.groups = []; S.sel = { kind: "cap", g: gi + 1 }; change();
}
function mergeGroups(gi) {
  snapshot(); materialiseGroups();
  const g = cap().groups;
  g.splice(gi, 2, [g[gi][0], g[gi + 1][1]]);
  S.groups = []; S.sel = { kind: "cap", g: gi }; S.selWord = null; change();
}

// the standard the default brand end screen: three regular lines, then the offer in bold
const STANDARD_END = [{"text": "Follow"}, {"text": "for more", "bold": true}];
// a client video's standard end screen is the client's (brands.js); the default brand keeps the one above
const standardEnd = () => clone((window.brandEndLines && window.brandEndLines(S.spec.brand)) || STANDARD_END);

function endPanel() {
  const E = S.spec.endcard;
  const wrap = el("div", {}, el("h2", {}, "End screen"), el("div", { class: "sub" }, "Brand gradient, white logo and call to action after the video"));
  wrap.append(row("Duration", bind(el("input", { type: "number", step: "0.1" }), () => E.duration ?? 3.5, (v) => (E.duration = v), { num: true }), el("span", { class: "unit" }, "s")));
  if (!E.lines) {
    // older single headline / sub line format
    wrap.append(sec("Text",
      row("Headline", bind(el("input", { type: "text" }), () => E.headline || "", (v) => (E.headline = v))),
      row("Sub line", bind(el("input", { type: "text" }), () => E.sub || "", (v) => (E.sub = v))),
      el("div", { class: "btns" }, el("button", { onclick: () => {
        snapshot();
        E.lines = [E.headline, E.sub].filter(Boolean).map((t) => ({ text: t.replace(/\*/g, "") }));
        delete E.headline; delete E.sub; change();
      } }, "Switch to multiple lines"))));
  } else {
    const list = el("div");
    E.lines.forEach((l, i) => {
      const inp = el("input", { type: "text", class: "grow", placeholder: l.bold ? "Bold line" : "Line" });
      bind(inp, () => l.text, (v) => (l.text = v));
      if (l.bold) inp.style.fontWeight = "700";
      const move = (d) => { const j = i + d; if (j < 0 || j >= E.lines.length) return; snapshot(); [E.lines[i], E.lines[j]] = [E.lines[j], E.lines[i]]; change(); };
      list.append(el("div", { class: "row" }, inp,
        el("button", { class: `small${l.bold ? " on" : ""}`, title: "Bold: the big offer lines", onclick: () => { snapshot(); if (l.bold) delete l.bold; else l.bold = true; change(); } }, "Bold"),
        el("button", { class: "small", title: "Move up", disabled: i === 0, onclick: () => move(-1) }, "↑"),
        el("button", { class: "small", title: "Move down", disabled: i === E.lines.length - 1, onclick: () => move(1) }, "↓"),
        el("button", { class: "small", title: "Remove line", onclick: () => { snapshot(); E.lines.splice(i, 1); change(); } }, "✕")));
    });
    wrap.append(sec(["Lines", el("span", { class: "hint" }, "Regular lines first, then the bold offer")], list,
      el("div", { class: "btns" },
        el("button", { class: "small", onclick: () => { snapshot(); E.lines.push({ text: "" }); change(); } }, "+ Line"),
        el("button", { class: "small", onclick: () => { snapshot(); E.lines.push({ text: "", bold: true }); change(); } }, "+ Bold line"),
        el("button", { class: "small", onclick: () => { snapshot(); E.lines = standardEnd(); change(); } }, "Reset to standard")),
      el("div", { class: "hint" }, "The the default brand logo sits under the lines. Lines rise in one by one, then the bold offer lands.")));
  }
  wrap.append(el("div", { class: "btns" }, el("button", { onclick: () => seek(S.dur + 2.5) }, "Go to end screen"),
    el("button", { class: "danger", onclick: () => { snapshot(); S._lastEnd = S.spec.endcard; delete S.spec.endcard; S.sel = null; change(); } }, "Remove end screen")));
  return wrap;
}

// ---------------------------------------------------------------- zoom
const pendingZooms = () => Object.entries(S.zoomEdits).filter(([i, z]) => S.edl[i] && Math.abs(z - S.edl[i].zoom) > 0.0005);
function setZoom(i, v) {
  v = Math.round(Math.max(1, Math.min(1.6, v)) * 100) / 100;
  if (Math.abs(v - S.edl[i].zoom) < 0.0005) delete S.zoomEdits[i]; else S.zoomEdits[i] = v;
  drawTimeline(); pushZoomPreview();
}
// the preview can only approximate a zoom-IN on the already-zoomed edit; zoom-outs show after Apply
function pushZoomPreview() {
  const list = (S.edl || []).map((z, i) => ({ start: z.start, end: z.end, ratio: Math.max(1, (S.zoomEdits[i] ?? z.zoom) / z.zoom) })).filter((x) => x.ratio > 1.0005);
  frames().forEach((f) => { try { f.contentWindow?.__editor?.setZoomPreview?.(list); } catch (e) {} });
}
function zoomPanel(i) {
  const z = S.edl[i], cur = S.zoomEdits[i] ?? z.zoom;
  const wrap = el("div", {}, el("h2", {}, "Zoom", el("span", { class: "tag" }, `${i + 1} of ${S.edl.length}`)),
    el("div", { class: "sub" }, `${z.start.toFixed(2)}s – ${z.end.toFixed(2)}s · ${(z.end - z.start).toFixed(1)}s between cuts`));
  if (!S.edlInfo.editable) {
    wrap.append(el("div", { class: "note" }, "This video has no cut list (work/edl.json), so its zooms can't be changed here."));
    return wrap;
  }
  const out = el("b", { style: "min-width:56px;font-size:15px" }, `${cur.toFixed(2)}×`);
  const rng = el("input", { type: "range", min: "1", max: "1.6", step: "0.01", style: "flex:1;min-width:0" }); rng.value = cur;
  rng.addEventListener("input", () => { setZoom(i, +rng.value); out.textContent = `${(+rng.value).toFixed(2)}×`; drawZoomNotes(); });
  rng.addEventListener("change", () => drawInspector());
  const notes = el("div");
  const drawZoomNotes = () => {
    notes.innerHTML = "";
    const v = S.zoomEdits[i] ?? z.zoom;
    if (v < z.zoom - 0.0005) notes.append(el("div", { class: "hint" }, "Zooming out is shown in the preview after you apply it."));
    else if (v > z.zoom + 0.0005) notes.append(el("div", { class: "hint" }, "The preview shows an approximation until you apply it."));
  };
  drawZoomNotes();
  wrap.append(sec("Scale", el("div", { class: "row" }, el("label", {}, "Zoom"), rng, out),
    el("div", { class: "btns" }, ...[["None", 1], ["1.1×", 1.1], ["1.22×", 1.22], ["1.3×", 1.3], ["1.4×", 1.4]].map(([n, v]) =>
      el("button", { class: `small${Math.abs(cur - v) < 0.005 ? " on" : ""}`, onclick: () => { setZoom(i, v); drawInspector(); } }, n)),
      el("button", { class: "small", onclick: () => { setZoom(i, z.zoom); drawInspector(); } }, `Original (${z.zoom.toFixed(2)}×)`)),
    notes,
    z.pan ? el("div", { class: "hint" }, "This shot also pans; the pan is kept.") : null,
    el("div", { class: "hint" }, "The house style alternates 1.3× → 1.0× → 1.22× → 1.0× every 5–8 s.")));
  wrap.append(applySection());
  return wrap;
}
function applySection() {
  const n = pendingZooms().length;
  const box = sec("Apply");
  if (S.zoomJob?.running) {
    box.append(el("div", { class: "note" }, `Re-rendering the base edit… ${Math.round(S.zoomJob.elapsed || 0)}s. The reel reloads when it's done.`));
    return box;
  }
  if (!S.edlInfo.raw) {
    box.append(el("div", { class: "note" }, "To change zooms, the editor re-renders the base edit from the original camera file. Show it where that file is (once per video)."),
      el("div", { class: "btns" }, el("button", { onclick: locateRaw }, "Locate raw video…")));
    return box;
  }
  box.append(el("div", { class: "hint" }, n ? `${n} zoom ${n === 1 ? "change" : "changes"} waiting. Applying re-renders the base edit with the same cuts and lighting (a minute or two); captions and cards stay where they are.`
    : "Change a zoom, then apply to re-render the base edit."),
    el("div", { class: "btns" },
      el("button", { class: "primary", onclick: applyZooms }, n ? `Apply ${n} zoom ${n === 1 ? "change" : "changes"}` : "Apply zoom changes"),
      n ? el("button", { onclick: () => { S.zoomEdits = {}; drawTimeline(); drawInspector(); pushZoomPreview(); } }, "Discard") : null),
    el("div", { class: "hint", style: "margin-top:4px;overflow-wrap:anywhere" }, `Raw video: ${S.edlInfo.raw.replace(/^\/Users\/[^/]+/, "~")}`));
  return box;
}
async function locateRaw() {
  let body = {};
  if (window.PORTAL) {                      // no Finder: upload the camera file (kept in the project's raw/ folder)
    const upload = await pickAndUpload("video/*", "the camera video");
    if (!upload) return;
    body = { upload };
  }
  const r = await fetch("/api/zoom/locate", { method: "POST", body: JSON.stringify(body) }).then((x) => x.json());
  if (r.ok) { S.edlInfo.raw = r.raw; toast("Raw video found"); drawInspector(); }
  else if (r.error) toast(r.error);
}
async function applyZooms() {
  const zooms = Object.fromEntries(pendingZooms());
  if (!Object.keys(zooms).length) { toast("No zoom changes to apply."); return; }
  if (S.dirty && !(await save())) return;
  const r = await fetch("/api/zoom/apply", { method: "POST", body: JSON.stringify({ zooms }) }).then((x) => x.json());
  if (!r.ok) { toast(r.error || "Couldn't start the re-render."); return; }
  pollZoomJob();
}
async function pollZoomJob() {
  const st = await fetch("/api/zoom/status").then((x) => x.json()).catch(() => null);
  if (!st) return setTimeout(pollZoomJob, 2000);
  S.zoomJob = st;
  setStatus(st.running ? `Re-rendering the ${st.kind === "cuts" ? "cut" : "zooms"}… ${Math.round(st.elapsed)}s` : undefined);
  if (S.sel?.kind === "zoom" || S.sel?.kind === "clip") drawInspector();
  if (st.running) return setTimeout(pollZoomJob, 1500);
  if (st.error) { toast(st.error); setStatus(); return; }
  if (st.done) {
    S.zoomEdits = {}; S.leaving = true;
    if (st.kind === "cuts") {
      try { localStorage.removeItem("draft:" + S.path); sessionStorage.setItem("cutReport", JSON.stringify(st.report || {})); } catch (e) {}
    }
    location.reload();
  }
}

// ---------------------------------------------------------------- cuts (split, trim, delete parts of the video)
// The cut list (work/edl.json) holds the camera-file times each clip plays. Edits change a working copy (S.cut);
// the preview jumps over removed parts, and Apply re-renders the base edit and moves everything with the words.
const MIN_CLIP = 0.1;
const cutSegs = () => (S.cut ? S.cut.segs : (S.edlRaw || []));
const segLen = (s) => s.out - s.in;
function oldToRaw(t) {
  let a = 0;
  for (const s of S.edlRaw || []) { if (t < a + segLen(s)) return s.in + Math.max(0, t - a); a += segLen(s); }
  const l = (S.edlRaw || []).slice(-1)[0]; return l ? l.out : t;
}
// the parts of camera time [a, b] that the current (rendered) edit shows, as edited-timeline spans
function oldPieces(a, b) {
  const out = []; let acc = 0;
  for (const s of S.edlRaw || []) {
    const lo = Math.max(a, s.in), hi = Math.min(b, s.out);
    if (hi - lo > 0.001) out.push([acc + lo - s.in, acc + hi - s.in]);
    acc += segLen(s);
  }
  return out;
}
function clipAt(t) { const r = oldToRaw(t); const k = cutSegs().findIndex((s) => s.in - 1e-6 <= r && r < s.out - 1e-6); return k < 0 ? null : k; }
function ensureCut() {
  if (!S.cut) { S.cut = { segs: (S.edlRaw || []).map((s, i) => ({ ...s, zoom: S.zoomEdits[i] ?? s.zoom })) }; S.zoomEdits = {}; }
}
function removedZones() {
  if (!S.cut) return [];
  const kept = S.cut.segs.flatMap((s) => oldPieces(s.in, s.out)).sort((x, y) => x[0] - y[0]);
  const out = []; let t = 0;
  for (const [a, b] of kept) { if (a - t > 0.02) out.push([t, a]); t = Math.max(t, b); }
  if (S.dur - t > 0.3) out.push([t, S.dur]);          // the edit can run a few frames past the camera file's end
  return out;
}
const cutStats = () => {
  const removed = removedZones().reduce((n, [a, b]) => n + b - a, 0);
  const now = cutSegs().reduce((n, s) => n + segLen(s), 0);
  return { removed, added: Math.max(0, now - (S.dur - removed)), dur: now };
};
function pushSkips() {
  const list = removedZones().map(([s, e]) => ({ s, e }));
  frames().forEach((f) => { try { f.contentWindow?.__editor?.setSkips?.(list); } catch (e) {} });
}
function cutChanged() {
  if (S.cut && JSON.stringify(S.cut.segs) === JSON.stringify(S.edlRaw)) S.cut = null;   // back to how it was
  fixSel(); pushSkips(); drawTimeline(); drawInspector(); setStatus();
}
function canCut() {
  if (!S.edlInfo?.editable) { toast("This video has no cut list (work/edl.json), so it can't be cut here."); return false; }
  if (S.zoomJob?.running) { toast("Wait for the re-render to finish."); return false; }
  return true;
}
function splitAt(t) {
  if (!canCut()) return;
  const k = clipAt(t);
  if (k == null) { toast("That part is already marked for removal."); return; }
  const r = oldToRaw(t), w = cutSegs()[k];
  if (r - w.in < MIN_CLIP || w.out - r < MIN_CLIP) { toast("Too close to an existing cut."); return; }
  snapshot(); ensureCut();
  S.cut.segs.splice(k, 1, { ...w, out: Math.round(r * 1000) / 1000 }, { ...w, in: Math.round(r * 1000) / 1000 });
  S.sel = { kind: "clip", i: k + 1 };
  cutChanged();
}
function deleteClip(k) {
  if (!canCut()) return;
  if (cutSegs().length <= 1) { toast("That's the only clip left."); return; }
  snapshot(); ensureCut();
  S.cut.segs.splice(k, 1);
  S.sel = null; cutChanged();
}
// remove an edited-timeline range: every camera-time piece under it comes out of the clips it falls in
function deleteRange(a, b) {
  if (!canCut()) return;
  const rawParts = []; let acc = 0;
  for (const s of S.edlRaw || []) {
    const lo = Math.max(a, acc), hi = Math.min(b, acc + segLen(s));
    if (hi - lo > 0.001) rawParts.push([s.in + lo - acc, s.in + hi - acc]);
    acc += segLen(s);
  }
  if (!rawParts.length) return;
  let segs = clone(cutSegs());
  for (const [ra, rb] of rawParts) {
    segs = segs.flatMap((s) => {
      if (rb <= s.in || ra >= s.out) return [s];
      const parts = [];
      if (ra - s.in >= MIN_CLIP) parts.push({ ...s, out: Math.round(ra * 1000) / 1000 });
      if (s.out - rb >= MIN_CLIP) parts.push({ ...s, in: Math.round(rb * 1000) / 1000 });
      return parts;
    });
  }
  if (!segs.length) { toast("That would remove the whole video."); return; }
  snapshot(); ensureCut(); S.cut.segs = segs;
  S.mark = null; S.sel = null; cutChanged();
  toast(`Marked ${(b - a).toFixed(1)}s for removal. Apply the cut when you're ready.`);
}
// trim one edge of a clip in camera time: it can't pass its neighbours or the ends of the camera file
function trimClip(k, edge, v) {
  const segs = S.cut.segs, w = segs[k];
  if (edge === "in") {
    const lo = Math.max(w.src ? w.vbase : 0, ...segs.filter((s) => s !== w && s.out <= w.in + 1e-6).map((s) => s.out));
    w.in = Math.round(Math.max(lo, Math.min(w.out - MIN_CLIP, v)) * 1000) / 1000;
  } else {
    const hi = Math.min(w.src ? w.vbase + w.clip : S.rawDur || w.out, ...segs.filter((s) => s !== w && s.in >= w.out - 1e-6).map((s) => s.in));
    w.out = Math.round(Math.min(hi, Math.max(w.in + MIN_CLIP, v)) * 1000) / 1000;
  }
}
function nudge(k, edge, d) { if (!canCut()) return; snapshot(); ensureCut(); trimClip(k, edge, S.cut.segs[k][edge] + d); cutChanged(); }
// drag a clip's edge on the Video track; snaps to the start or end of words unless Alt is held
function startTrim(ev, k, edge) {
  ev.stopPropagation(); ev.preventDefault();
  if (!canCut()) return;
  snapshot(); ensureCut();
  const x0 = ev.clientX, v0 = S.cut.segs[k][edge];
  S.sel = { kind: "clip", i: k };
  const mv = (e) => {
    let v = v0 + (e.clientX - x0) / S.pps;
    if (!window.__alt) {
      const tol = 8 / S.pps; let best = null;
      for (const w of S.words) {
        const r = oldToRaw(edge === "in" ? w.start : w.end);
        if (Math.abs(r - v) < tol && (best == null || Math.abs(r - v) < Math.abs(best - v))) best = r;
      }
      if (best != null) v = best;
    }
    trimClip(k, edge, v); drawTimeline();
  };
  const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); cutChanged(); };
  addEventListener("pointermove", mv); addEventListener("pointerup", up);
}
function setMark(which, t) {
  S.mark = { ...(S.mark || {}), [which]: r2(t) };
  drawTimeline();
  if (markRange()) toast("Press ⌫ (or Remove marked part) to cut it out.");
}
function markRange() { const m = S.mark; if (m?.a == null || m?.b == null) return null; const a = Math.min(m.a, m.b), b = Math.max(m.a, m.b); return b - a >= 0.05 ? [a, b] : null; }
function clearMarks() { S.mark = null; drawTimeline(); updateCutbar(); }

function drawClips(lane) {
  const segs = cutSegs(), content = $("#content");
  segs.forEach((s, k) => {
    const pcs = oldPieces(s.in, s.out); if (!pcs.length) return;
    const sel = S.sel?.kind === "clip" && S.sel.i === k;
    const shown = pcs.reduce((n, [a, b]) => n + b - a, 0), extra = segLen(s) - shown;
    pcs.forEach(([a, b], j) => {
      const blk = el("div", { class: `clipb${sel ? " sel" : ""}${s.src ? " ins" : ""}`, style: `left:${X(a)}px;width:${Math.max(4, X(b - a) - 2)}px`,
        title: s.src ? `Inserted clip · ${fmtT(a)}–${fmtT(b)} · ${s.src.split(/[\\/]/).pop()}` : `Clip ${k + 1} · ${fmtT(a)}–${fmtT(b)} · camera ${s.in.toFixed(2)}–${s.out.toFixed(2)}s` },
        s.src && X(b - a) > 60 ? el("span", { class: "insl" }, "Insert") : null,
        j === 0 ? el("span", { class: "h l", title: "Drag to trim the start" }) : null,
        j === pcs.length - 1 ? el("span", { class: "h r", title: "Drag to trim the end" }) : null,
        j === pcs.length - 1 && extra > 0.02 ? el("span", { class: "plus", title: "Material brought back from the camera file" }, `+${extra.toFixed(1)}s`) : null);
      blk.addEventListener("pointerdown", (ev) => {
        const h = ev.target.closest(".h");
        if (h) return startTrim(ev, k, h.classList.contains("l") ? "in" : "out");
        ev.stopPropagation(); select({ kind: "clip", i: k });
        if (S.t < a || S.t > b) seek(a + 0.02);
      });
      lane.append(blk);
    });
    if (k > 0) lane.append(el("i", { class: "cutmark", style: `left:${X(pcs[0][0])}px`, title: `Cut at ${pcs[0][0].toFixed(2)}s` }));
  });
  removedZones().forEach(([a, b]) => content.append(el("div", { class: "cutzone", style: `left:${X(a)}px;width:${X(b - a)}px`, title: `Removed when you apply: ${(b - a).toFixed(2)}s` },
    X(b - a) > 70 ? el("span", {}, `Cut ${(b - a).toFixed(1)}s`) : null)));
  const m = S.mark;
  if (m && (m.a != null || m.b != null)) {
    const a = m.a ?? m.b, b = m.b ?? m.a, lo = Math.min(a, b), hi = Math.max(a, b);
    content.append(el("div", { class: "markband", style: `left:${X(lo)}px;width:${Math.max(2, X(hi - lo))}px` }));
  }
  updateCutbar();
}
// the cut controls in the timeline toolbar: Split, In/Out marks, and Apply/Discard while a cut is waiting
function updateCutbar() {
  const bar = $("#cutbar"); if (!bar) return;
  bar.innerHTML = "";
  const rng = markRange();
  if (rng) bar.append(el("button", { class: "small", onclick: () => deleteRange(...rng), title: "Remove the part between the In and Out marks (⌫)" }, ic("scissors"), `Remove ${(rng[1] - rng[0]).toFixed(1)}s`),
    el("button", { class: "small ghost", onclick: clearMarks, title: "Clear the marks (Esc)" }, ic("x")));
  if (S.cut) {
    const st = cutStats();
    bar.append(el("span", { class: "cutsum" }, `Cut waiting: −${st.removed.toFixed(1)}s${st.added > 0.02 ? ` +${st.added.toFixed(1)}s` : ""} → ${fmtT(st.dur)}`),
      el("button", { class: "small primary", onclick: applyCuts }, "Apply cut"),
      el("button", { class: "small", onclick: discardCuts }, "Discard"));
  }
}
function discardCuts() { snapshot(); S.cut = null; S.mark = null; cutChanged(); }
async function applyCuts() {
  if (!S.cut || !canCut()) return;
  if (!S.edlInfo.raw) { select({ kind: "clip", i: 0 }); toast("Show the editor where the camera file is first."); return; }
  const st = cutStats();
  const ok = await confirmBox("Apply the cut?", `The video goes from ${fmtT(S.dur)} to ${fmtT(st.dur)}. The base edit is re-rendered from the camera file (a minute or two). ` +
    "Captions, cards, effects and sounds move with their words; anything that sat only inside a removed part is deleted. The previous version is kept as a backup.", "Apply cut");
  if (!ok) return;
  if (S.dirty && !(await save())) return;
  const r = await fetch("/api/cuts/apply", { method: "POST", body: JSON.stringify({ segments: S.cut.segs }) }).then((x) => x.json()).catch(() => ({ ok: false }));
  if (!r.ok) { toast(r.error || "Couldn't start the re-render."); return; }
  pollZoomJob();
}
function confirmBox(title, text, yes) {
  return new Promise((res) => {
    const done = (v) => { closeModal(); res(v); };
    openModal(el("div", { class: "box" }, el("h3", {}, title), el("p", { class: "hint", style: "font-size:13px;line-height:1.5" }, text),
      el("div", { class: "btns", style: "justify-content:flex-end;margin-top:14px" },
        el("button", { onclick: () => done(false) }, "Cancel"), el("button", { class: "primary", onclick: () => done(true) }, yes))));
  });
}
function clipPanel(k) {
  const segs = cutSegs(), s = segs[k];
  if (!s) return el("div");
  const pcs = oldPieces(s.in, s.out);
  const wrap = el("div", {}, el("h2", {}, "Clip", el("span", { class: "tag" }, `${k + 1} of ${segs.length}`)),
    el("div", { class: "sub" }, pcs.length ? `${fmtT(pcs[0][0])} – ${fmtT(pcs[pcs.length - 1][1])} on the timeline · ${segLen(s).toFixed(2)}s` : `${segLen(s).toFixed(2)}s`));
  if (!S.edlInfo.editable) {
    wrap.append(el("div", { class: "note" }, "This video has no cut list (work/edl.json), so it can't be cut here."));
    return wrap;
  }
  const f = 1 / S.fps;
  const row = (label, edge) => el("div", { class: "trimrow" }, el("label", {}, label),
    el("div", { class: "btns" }, ...[[-0.5, "−0.5s"], [-0.1, "−0.1s"], [-f, "−1f"], [f, "+1f"], [0.1, "+0.1s"], [0.5, "+0.5s"]].map(([d, n]) =>
      el("button", { class: "small", title: `${edge === "in" ? "Start" : "End"} ${d < 0 ? "earlier" : "later"} by ${n.replace(/[−+]/, "")}`, onclick: () => nudge(k, edge, d) }, n))));
  wrap.append(sec("Trim", row("Start", "in"), row("End", "out"),
    el("div", { class: "hint" }, "Or drag the clip's edges on the Video track. Moving an edge outwards brings back material the automatic edit cut out."),
    el("div", { class: "hint" }, s.src ? `Inserted clip ${s.src.split(/[\\/]/).pop()}: ${(s.in - s.vbase).toFixed(2)}s – ${(s.out - s.vbase).toFixed(2)}s of ${(+s.clip || 0).toFixed(2)}s. Delete it to take it out again.`
      : `Camera file: ${s.in.toFixed(2)}s – ${s.out.toFixed(2)}s`)));
  wrap.append(sec("Cut",
    el("div", { class: "btns" },
      el("button", { onclick: () => splitAt(S.t), title: "S" }, ic("scissors"), "Split at playhead"),
      el("button", { onclick: () => deleteClip(k), title: "⌫" }, ic("trash-2"), "Delete clip"),
      pcs.length ? el("button", { onclick: () => { seek(pcs[0][0]); ed()?.play(pcs[0][0]); } }, ic("circle-play"), "Play clip") : null),
    el("div", { class: "hint" }, "To cut out a part: put the playhead at its start and press I, at its end and press O, then ⌫. Or split on both sides and delete the clip.")));
  const box = sec("Apply");
  if (S.zoomJob?.running) box.append(el("div", { class: "note" }, `Re-rendering… ${Math.round(S.zoomJob.elapsed || 0)}s. The video reloads when it's done.`));
  else if (!S.cut) box.append(el("div", { class: "hint" }, "Split, trim or delete clips. Removed parts are skipped in the preview straight away; Apply cut re-renders the video."));
  else {
    const st = cutStats();
    box.append(el("div", { class: "hint" }, `Removes ${st.removed.toFixed(1)}s${st.added > 0.02 ? ` and brings back ${st.added.toFixed(1)}s` : ""}: ${fmtT(S.dur)} → ${fmtT(st.dur)}. ` +
      "Captions, cards, effects and sounds move with their words."));
    if (!S.edlInfo.raw) box.append(el("div", { class: "note" }, "Applying re-renders from the original camera file. Show the editor where it is (once per video)."),
      el("div", { class: "btns" }, el("button", { onclick: locateRaw }, "Locate raw video…")));
    else box.append(el("div", { class: "btns" }, el("button", { class: "primary", onclick: applyCuts }, "Apply cut"), el("button", { onclick: discardCuts }, "Discard")));
  }
  wrap.append(box);
  return wrap;
}

// ---------------------------------------------------------------- moving cards and blur regions on the preview
// An overlay over the preview shows a box around the selected card or blur. Drag it to move (Shift keeps the move
// level or upright), drag a blur's corners to resize. Cards store x (group centre) plus their usual vertical position
// (top in a reel, y elsewhere); blurs store keys [{dt, x, y}] (top-left) and w, h, all in canvas pixels.
const RD_TYPES = { blur: "Blur", box: "Black box" };
const pvScale = () => { const [, H] = canvasSize(); return $("#screen").clientHeight / H; };
const pvDoc = () => { try { return active?.contentDocument; } catch (e) { return null; } };
const pvWin = () => { try { return active?.contentWindow; } catch (e) { return null; } };
// the drawn box of a card group, in canvas pixels, or null when it isn't on screen
function cardBox(i) {
  const host = pvDoc()?.getElementById(`c${i}`); if (!host) return null;
  let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity, seen = false;
  host.querySelectorAll(":scope > .g, :scope > .swap, :scope > svg.lines").forEach((e) => {
    const cs = getComputedStyle(e); if (cs.visibility === "hidden" || cs.display === "none") return;
    const q = e.getBoundingClientRect(); if (!q.width || !q.height) return;
    if (!e.matches("svg") && +cs.opacity > 0.05) seen = true;
    l = Math.min(l, q.left); t = Math.min(t, q.top); r = Math.max(r, q.right); b = Math.max(b, q.bottom);
  });
  if (!seen || getComputedStyle(host).visibility === "hidden") return null;
  return { x: l, y: t, w: r - l, h: b - t };
}
// where a blur region is at edited time t (its keys glide when it follows movement)
function rdPos(r, t) {
  const k = r.keys || [{ dt: 0, x: 0, y: 0 }], dt = t - r.t;
  if (!r.track || k.length < 2 || dt <= k[0].dt) return { x: k[0].x, y: k[0].y };
  for (let j = 1; j < k.length; j++) if (dt <= k[j].dt) { const a = k[j - 1], b = k[j], f = (dt - a.dt) / Math.max(0.001, b.dt - a.dt); return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f }; }
  const z = k[k.length - 1]; return { x: z.x, y: z.y };
}
const rdOn = (r, t) => t >= r.t - 0.001 && t <= r.t + r.dur + 0.001;
function rdBox(i) { const r = (S.spec.redactions || [])[i]; if (!r || !rdOn(r, S.t)) return null; const p = rdPos(r, S.t); return { x: p.x, y: p.y, w: r.w, h: r.h }; }

function drawOverlay() {
  const ov = $("#ovl"); if (!ov) return;
  ov.innerHTML = "";
  if (!S.spec || S.mode === "new") return;
  const k = S.sel?.kind, box = k === "card" ? cardBox(S.sel.i) : k === "rd" ? rdBox(S.sel.i) : k === "ov" ? ovBox(S.sel.i) : null;
  if (!box) return;
  const sc = pvScale();
  const b = el("div", { class: `ovbox ${k}`, style: `left:${box.x * sc}px;top:${box.y * sc}px;width:${box.w * sc}px;height:${box.h * sc}px`,
    title: k === "rd" ? "Drag to move, drag a corner to resize" : "Drag to move (Shift keeps it level)" });
  if (k === "rd" || k === "ov") ["nw", "ne", "sw", "se"].forEach((c) => b.append(el("i", { class: `ovh ${c}` })));
  ov.append(b);
}
// click the preview: pick the card or blur under the pointer, then drag it
function ovPointerDown(ev) {
  if (!S.spec || S.mode === "new" || ev.button !== 0) return;
  const r = $("#screen").getBoundingClientRect(), sc = pvScale();
  const px = (ev.clientX - r.left) / sc, py = (ev.clientY - r.top) / sc;
  const inside = (b) => b && px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h;
  const handle = ev.target.closest(".ovh");
  let hit = null;
  if (S.sel?.kind === "card" && inside(cardBox(S.sel.i))) hit = { kind: "card", i: S.sel.i };
  else if (S.sel?.kind === "rd" && (handle || inside(rdBox(S.sel.i)))) hit = { kind: "rd", i: S.sel.i };
  else if (S.sel?.kind === "ov" && (handle || inside(ovBox(S.sel.i)))) hit = { kind: "ov", i: S.sel.i };
  else {
    const ovs = S.spec.overlays || [];
    for (let i = ovs.length - 1; i >= 0 && !hit; i--) if (inside(ovBox(i))) hit = { kind: "ov", i };
    const rds = S.spec.redactions || [];
    for (let i = rds.length - 1; i >= 0 && !hit; i--) if (inside(rdBox(i))) hit = { kind: "rd", i };   // blurs sit under the cards,
    for (let i = (S.spec.cards || []).length - 1; i >= 0; i--) if (inside(cardBox(i))) { hit = { kind: "card", i }; break; }   // so a card wins
  }
  if (!hit) return;
  ev.preventDefault();
  if (S.sel?.kind !== hit.kind || S.sel.i !== hit.i) select(hit);
  if (hit.kind === "ov") return dragOv(ev, hit.i, handle ? [...handle.classList].find((c) => c.length === 2) : null);
  if (hit.kind === "card") dragCard(ev, hit.i); else dragRd(ev, hit.i, handle ? [...handle.classList].find((c) => c.length === 2) : null);
}
function dragCard(ev, i) {
  const c = S.spec.cards[i], box0 = cardBox(i), host = pvDoc()?.getElementById(`c${i}`); if (!box0 || !host) return;
  const sc = pvScale(), [W] = canvasSize(), x0 = ev.clientX, y0 = ev.clientY;
  let dx = 0, dy = 0, moved = false;
  const mv = (e) => {
    dx = (e.clientX - x0) / sc; dy = (e.clientY - y0) / sc;
    if (!moved && Math.hypot(dx, dy) * sc < 3) return;
    moved = true;
    if (e.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
    const cx = box0.x + box0.w / 2 + dx;
    const guide = Math.abs(cx - W / 2) < 14 && !e.altKey;                // snap to the middle
    if (guide) dx = W / 2 - (box0.x + box0.w / 2);
    host.style.translate = `${dx}px ${dy}px`;
    const b = $("#ovl .ovbox"); if (b) { b.style.left = (box0.x + dx) * sc + "px"; b.style.top = (box0.y + dy) * sc + "px"; }
    $("#ovl").classList.toggle("guide", guide);
  };
  const up = () => {
    removeEventListener("pointermove", mv); removeEventListener("pointerup", up); $("#ovl").classList.remove("guide");
    if (!moved) return;
    snapshot();
    c.x = Math.round(box0.x + box0.w / 2 + dx);
    if (Math.abs(dy) >= 1) {
      if (isReelFmt()) c.top = Math.round((c.top ?? cardTopDefault(c)) + dy);
      else { const L = pvWin()?.__LAYOUT || {}; c.y = Math.round((c.y ?? (c.type === "chip" ? L.chipY : L.cy) ?? 0) + dy); }
    }
    change();
  };
  addEventListener("pointermove", mv); addEventListener("pointerup", up);
}
const cardTopDefault = (c) => ({ text: 1240, chip: 288, questions: 1240, hub: 1200, statement: 1222, compare: 1230, steps: 1232, feature: 1232, tiles: 1210, connect: 1192, chat: 1203, task: 1240 }[c.type] || 1230);
function dragRd(ev, i, corner) {
  const r = S.spec.redactions[i], p0 = rdPos(r, S.t), w0 = r.w, h0 = r.h, sc = pvScale(), [W, H] = canvasSize();
  const x0 = ev.clientX, y0 = ev.clientY, node = pvDoc()?.getElementById(`rd${i}`);
  let g = { x: p0.x, y: p0.y, w: w0, h: h0 }, moved = false;
  const mv = (e) => {
    let dx = (e.clientX - x0) / sc, dy = (e.clientY - y0) / sc;
    if (!moved && Math.hypot(dx, dy) * sc < 3) return;
    moved = true;
    if (!corner) {
      if (e.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
      g = { x: Math.round(Math.max(-w0 / 2, Math.min(W - w0 / 2, p0.x + dx))), y: Math.round(Math.max(-h0 / 2, Math.min(H - h0 / 2, p0.y + dy))), w: w0, h: h0 };
    } else {
      let l = p0.x, t = p0.y, rr = p0.x + w0, b = p0.y + h0;
      if (corner.includes("w")) l = Math.min(rr - 40, l + dx); else rr = Math.max(l + 40, rr + dx);
      if (corner.includes("n")) t = Math.min(b - 40, t + dy); else b = Math.max(t + 40, b + dy);
      g = { x: Math.round(l), y: Math.round(t), w: Math.round(rr - l), h: Math.round(b - t) };
    }
    if (node) Object.assign(node.style, { left: g.x + "px", top: g.y + "px", width: g.w + "px", height: g.h + "px", transform: "none" });
    const bx = $("#ovl .ovbox"); if (bx) Object.assign(bx.style, { left: g.x * sc + "px", top: g.y * sc + "px", width: g.w * sc + "px", height: g.h * sc + "px" });
  };
  const up = () => {
    removeEventListener("pointermove", mv); removeEventListener("pointerup", up);
    if (!moved) return;
    snapshot();
    r.w = g.w; r.h = g.h;
    if (r.track) {                           // following movement: this position becomes a point at the playhead
      const dt = r2(Math.max(0, Math.min(r.dur, S.t - r.t)));
      const keys = (r.keys || []).filter((k) => Math.abs(k.dt - dt) > 0.08);
      keys.push({ dt, x: g.x, y: g.y }); keys.sort((a, b) => a.dt - b.dt);
      if (keys[0].dt > 0) keys.unshift({ dt: 0, x: keys[0].x, y: keys[0].y });
      r.keys = keys;
    } else r.keys = [{ dt: 0, x: g.x, y: g.y }];
    change();
  };
  addEventListener("pointermove", mv); addEventListener("pointerup", up);
}

function addBlur() {
  const [W, H] = canvasSize();
  const w = Math.round(W * 0.4), h = Math.round(Math.min(H * 0.18, W * 0.3));
  const t = r2(Math.max(0, Math.min(S.t, S.dur - 1))), dur = r2(Math.min(3, S.dur - t));
  snapshot();
  S.spec.redactions = S.spec.redactions || [];
  S.spec.redactions.push({ t, dur, type: "blur", strength: 28, w, h, track: false, keys: [{ dt: 0, x: Math.round((W - w) / 2), y: Math.round((H - h) / 2) }] });
  S.sel = { kind: "rd", i: S.spec.redactions.length - 1 };
  change();
  toast("Blur added at the playhead. Drag it on the preview to cover what you need to hide.");
}
function startRdDrag(ev, i) {
  ev.stopPropagation(); ev.preventDefault();
  const r = S.spec.redactions[i], o = clone(r), x0 = ev.clientX;
  const mode = ev.target.classList.contains("l") ? "l" : ev.target.classList.contains("r") ? "r" : "m";
  let moved = false;
  if (!(S.sel?.kind === "rd" && S.sel.i === i)) select({ kind: "rd", i });
  const mv = (e) => {
    if (!moved && Math.abs(e.clientX - x0) < 3) return;
    if (!moved) { snapshot(); moved = true; }
    const d = (e.clientX - x0) / S.pps;
    if (mode === "m") r.t = r2(Math.max(0, Math.min(S.dur - o.dur, o.t + d)));
    else if (mode === "l") { const end = o.t + o.dur; r.t = r2(Math.max(0, Math.min(end - 0.3, o.t + d))); r.dur = r2(end - r.t); }
    else r.dur = r2(Math.max(0.3, Math.min(S.dur - o.t, o.dur + d)));
    drawTimeline();
  };
  const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); if (moved) change(); else drawInspector(); if (!rdOn(r, S.t)) seek(r.t + 0.05); };
  addEventListener("pointermove", mv); addEventListener("pointerup", up);
}
function rdPanel(i) {
  const r = S.spec.redactions[i];
  const wrap = el("div", {}, el("h2", {}, RD_TYPES[r.type] || "Blur", el("span", { class: "tag" }, "region")),
    el("div", { class: "sub" }, "Hides part of the picture: a face, a name, a screen. Drag the box on the preview to move it, drag its corners to resize."),
    el("div", { class: "btns" },
      el("button", { onclick: () => seek(Math.max(0, r.t - 0.6)) }, "Play from just before"),
      el("button", { onclick: () => { snapshot(); const d = clone(r); d.t = r2(Math.min(S.dur - d.dur, r.t + r.dur + 0.2)); S.spec.redactions.push(d); S.sel = { kind: "rd", i: S.spec.redactions.length - 1 }; change(); } }, "Duplicate"),
      el("button", { class: "danger", onclick: () => deleteRd(i) }, "Delete")));
  wrap.append(sec("Look",
    el("div", { class: "btns" }, ...Object.entries(RD_TYPES).map(([k, n]) => el("button", { class: `small${(r.type || "blur") === k ? " on" : ""}`, onclick: () => { snapshot(); r.type = k; change(); } }, n))),
    (r.type || "blur") === "blur" ? sliderRow("Strength", () => r.strength ?? 28, (v) => (r.strength = v), 6, 60, 1, (v) => `${Math.round(v)}px`) : null,
    row("Size", bind(el("input", { type: "number", step: "1", min: "20" }), () => r.w, (v) => (r.w = Math.max(20, Math.round(v))), { num: true }), el("span", { class: "unit" }, "×"),
      bind(el("input", { type: "number", step: "1", min: "20" }), () => r.h, (v) => (r.h = Math.max(20, Math.round(v))), { num: true }), el("span", { class: "unit" }, "px"))));
  wrap.append(sec("Timing", row("Start", ...timeInput(() => r.t, (v) => (r.t = Math.max(0, v)))),
    row("Length", bind(el("input", { type: "number", step: "0.1", min: "0.3" }), () => r.dur, (v) => (r.dur = Math.max(0.3, r2(v))), { num: true }), el("span", { class: "unit" }, "s"),
      el("button", { class: "small", title: "End at the playhead", onclick: () => { if (S.t > r.t + 0.3) { snapshot(); r.dur = r2(S.t - r.t); change(); } } }, "◆ end here"))));
  const follow = el("label", { class: "tool switch" }, el("input", { type: "checkbox", checked: !!r.track }), el("span"), "Follow movement");
  follow.querySelector("input").onchange = (e) => { snapshot(); r.track = e.target.checked; if (!r.track) r.keys = [r.keys[0]]; change(); };
  const n = (r.keys || []).length;
  wrap.append(sec("Movement", follow,
    el("div", { class: "hint" }, r.track ? `${n} point${n === 1 ? "" : "s"}. Move the playhead, then drag the box: it glides from point to point.` : "Turn on to follow something that moves: move the playhead, drag the box, repeat."),
    r.track && n > 1 ? el("div", { class: "btns" }, el("button", { class: "small", onclick: () => { snapshot(); r.keys = [r.keys[0]]; change(); } }, "Clear the points")) : null));
  wrap.append(el("div", { class: "hint", style: "margin-top:10px" }, "Blurs sit on the video, under the cards, captions and takeovers."));
  return wrap;
}
function deleteRd(i) { snapshot(); S.spec.redactions.splice(i, 1); S.sel = null; change(); }
function placeSection(c) {
  return sec("Placement", el("div", { class: "hint" }, c.x != null ? `Moved: centred at x ${c.x}px. Drag it on the preview to move it again.` : "Drag it on the preview to move it anywhere (Shift keeps the move level; it snaps to the middle)."),
    c.x != null ? el("div", { class: "btns" }, el("button", { class: "small", onclick: () => { snapshot(); delete c.x; change(); } }, "Centre it again")) : null);
}

// ---------------------------------------------------------------- overlay videos (inserts, B-roll, testimonials)
// overlays[]: {src, name, t, dur, in, clip (its full length), track, mode full|pip, x, y, w, h, opacity, fade, muted, volume, duck}
const OV_ROW = 30;                                   // one overlay track row on the timeline (px)
const ovList = () => (S.spec.overlays = S.spec.overlays || []);
const ovTracks = () => Math.max(1, ...ovList().map((o) => o.track || 1));
function ovDefaultBox() {
  const [W, H] = canvasSize(), w = Math.round(W * 0.42), h = Math.round(H > W ? w * 16 / 9 * 0.62 : w * 9 / 16);
  return { x: W - w - Math.round(W * 0.055), y: Math.round(H * 0.06), w, h };
}
async function addOverlay() {
  if (!S.spec) return;
  let body = {};
  if (window.PORTAL) {
    const upload = await pickAndUpload("video/*", "the video");
    if (!upload) return;
    body = { upload };
  } else toast("Choose a video in the Finder window…");
  const r = await fetch("/api/overlay/pick", { method: "POST", body: JSON.stringify(body) }).then((x) => x.json()).catch(() => ({ ok: false }));
  if (r.error) toast(r.error);
  if (!r.ok) return;
  const t = r2(Math.max(0, Math.min(S.t, S.dur - 0.5))), dur = r2(Math.min(r.dur || 5, S.dur - t, 6));
  const busy = (k) => ovList().some((o) => (o.track || 1) === k && o.t < t + dur && o.t + o.dur > t);
  let track = 1; while (busy(track)) track++;
  snapshot();
  ovList().push({ src: r.src, name: r.name, t, dur, in: 0, clip: r.dur, track, mode: "full", opacity: 1, fade: 0.3, muted: true, volume: 1, duck: 1, has_audio: r.audio });
  S.sel = { kind: "ov", i: ovList().length - 1 };
  change();
  toast(r.audio ? "Overlay added, muted. Unmute it in the panel to hear its sound." : "Overlay added.");
}
function setOvSound(o, on) {
  snapshot(); o.muted = !on;
  if (on && (o.duck ?? 1) >= 0.999) o.duck = 0.15;   // a testimonial with sound: the speaker drops right down underneath
  if (!on) o.duck = 1;
  change();
}
function startOvDrag(ev, i) {
  ev.stopPropagation(); ev.preventDefault();
  const o = ovList()[i], o0 = clone(o), x0 = ev.clientX, y0 = ev.clientY, clipLen = o.clip || Infinity;
  const mode = ev.target.classList.contains("l") ? "l" : ev.target.classList.contains("r") ? "r" : "m";
  let moved = false;
  if (!(S.sel?.kind === "ov" && S.sel.i === i)) select({ kind: "ov", i });
  const mv = (e) => {
    if (!moved && Math.hypot(e.clientX - x0, e.clientY - y0) < 3) return;
    if (!moved) { snapshot(); moved = true; }
    const d = (e.clientX - x0) / S.pps;
    if (mode === "m") {
      o.t = r2(Math.max(0, Math.min(S.dur - o0.dur, o0.t + d)));
      o.track = Math.max(1, Math.min(6, (o0.track || 1) - Math.round((e.clientY - y0) / OV_ROW)));   // drag up = a higher track
    } else if (mode === "l") {                        // trim the start: the clip's own start point moves with it
      const dd = Math.max(-o0.in, Math.min(o0.dur - 0.3, d, S.dur));
      o.t = r2(Math.max(0, o0.t + dd)); const real = o.t - o0.t;
      o.in = r2(o0.in + real); o.dur = r2(o0.dur - real);
    } else o.dur = r2(Math.max(0.3, Math.min(S.dur - o0.t, clipLen - o0.in, o0.dur + d)));
    drawTimeline();
  };
  const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); if (moved) change(); else drawInspector(); if (S.t < o.t || S.t > o.t + o.dur) seek(o.t + 0.05); };
  addEventListener("pointermove", mv); addEventListener("pointerup", up);
}
function ovBox(i) {
  const o = ovList()[i]; if (!o || o.mode !== "pip" || S.t < o.t || S.t > o.t + o.dur) return null;
  const d = ovDefaultBox(); return { x: o.x ?? d.x, y: o.y ?? d.y, w: o.w ?? d.w, h: o.h ?? d.h };
}
function dragOv(ev, i, corner) {
  const o = ovList()[i], b0 = ovBox(i), sc = pvScale(), [W, H] = canvasSize(), x0 = ev.clientX, y0 = ev.clientY;
  const node = pvDoc()?.getElementById(`ov${i}`); let g = { ...b0 }, moved = false;
  const mv = (e) => {
    let dx = (e.clientX - x0) / sc, dy = (e.clientY - y0) / sc;
    if (!moved && Math.hypot(dx, dy) * sc < 3) return;
    moved = true;
    if (!corner) {
      if (e.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
      g = { ...b0, x: Math.round(Math.max(-b0.w / 2, Math.min(W - b0.w / 2, b0.x + dx))), y: Math.round(Math.max(-b0.h / 2, Math.min(H - b0.h / 2, b0.y + dy))) };
    } else {                                          // corners keep the window's shape
      const sgn = corner.includes("w") ? -1 : 1, w = Math.max(120, b0.w + sgn * dx), h = Math.round(w * b0.h / b0.w);
      g = { w: Math.round(w), h, x: corner.includes("w") ? Math.round(b0.x + b0.w - w) : b0.x, y: corner.includes("n") ? Math.round(b0.y + b0.h - h) : b0.y };
    }
    if (node) { Object.assign(node.style, { left: g.x + "px", top: g.y + "px", width: g.w + "px", height: g.h + "px" }); try { ed()?.restyle?.(); } catch (er) {} }
    const bx = $("#ovl .ovbox"); if (bx) Object.assign(bx.style, { left: g.x * sc + "px", top: g.y * sc + "px", width: g.w * sc + "px", height: g.h * sc + "px" });
  };
  const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); if (!moved) return; snapshot(); Object.assign(o, g); change(); };
  addEventListener("pointermove", mv); addEventListener("pointerup", up);
}
function ovPanel(i) {
  const o = ovList()[i];
  const wrap = el("div", {}, el("h2", {}, o.name || "Overlay video", el("span", { class: "tag" }, o.mode === "pip" ? "picture-in-picture" : "full screen")),
    el("div", { class: "sub" }, `Track V${(o.track || 1) + 1} · ${o.t.toFixed(2)}s – ${(o.t + o.dur).toFixed(2)}s · plays the clip from ${(o.in || 0).toFixed(2)}s`),
    el("div", { class: "btns" },
      el("button", { onclick: () => seek(Math.max(0, o.t - 0.6)) }, "Play from just before"),
      el("button", { onclick: () => { snapshot(); const d = clone(o); d.t = r2(Math.min(S.dur - d.dur, o.t + o.dur + 0.2)); ovList().push(d); S.sel = { kind: "ov", i: ovList().length - 1 }; change(); } }, "Duplicate"),
      el("button", { class: "danger", onclick: () => deleteOv(i) }, "Delete")));
  const on = o.muted === false;
  wrap.append(sec("Sound",
    el("div", { class: "btns" },
      el("button", { class: `ovsound${on ? " on" : ""}`, onclick: () => setOvSound(o, !on), title: on ? "Mute this clip" : "Play this clip's own sound" },
        ic(on ? "volume-2" : "volume-x"), on ? "Sound on (click to mute)" : "Muted (click to unmute)")),
    o.has_audio === false ? el("div", { class: "hint" }, "This clip has no sound of its own.") : null,
    on ? sliderRow("Volume", () => o.volume ?? 1, (v) => (o.volume = v), 0, 2, 0.05, (v) => `${Math.round(v * 100)}%`) : null,
    sliderRow("Speaker", () => o.duck ?? 1, (v) => (o.duck = v), 0, 1, 0.05, (v) => `${Math.round(v * 100)}%`),
    el("div", { class: "hint" }, "Speaker = how loud the main video stays while this plays. Unmuting a testimonial drops it to 15%; 0% silences it.")));
  wrap.append(sec("Look",
    el("div", { class: "btns" }, ...[["full", "Full screen"], ["pip", "Picture-in-picture"]].map(([k, n]) =>
      el("button", { class: `small${(o.mode || "full") === k ? " on" : ""}`, onclick: () => { snapshot(); o.mode = k; if (k === "pip" && o.x == null) Object.assign(o, ovDefaultBox()); change(); } }, n))),
    o.mode === "pip" ? el("div", { class: "hint" }, "Drag the window on the preview to move it; drag a corner to resize.") : null,
    o.mode === "pip" ? el("div", { class: "btns" }, el("button", { class: "small", onclick: () => { snapshot(); Object.assign(o, ovDefaultBox()); change(); } }, "Back to the top corner")) : null,
    sliderRow("Opacity", () => o.opacity ?? 1, (v) => (o.opacity = v), 0.1, 1, 0.05, (v) => `${Math.round(v * 100)}%`),
    sliderRow("Fade", () => o.fade ?? 0.3, (v) => (o.fade = v), 0, 1.5, 0.05, (v) => `${(+v).toFixed(2)}s`)));
  wrap.append(sec("Timing", row("Start", ...timeInput(() => o.t, (v) => (o.t = Math.max(0, v)))),
    row("Length", bind(el("input", { type: "number", step: "0.1", min: "0.3" }), () => o.dur, (v) => (o.dur = Math.max(0.3, Math.min(r2(v), (o.clip || Infinity) - (o.in || 0)))), { num: true }), el("span", { class: "unit" }, "s")),
    row("Clip from", bind(el("input", { type: "number", step: "0.1", min: "0" }), () => o.in || 0, (v) => (o.in = Math.max(0, Math.min(r2(v), (o.clip || Infinity) - 0.3))), { num: true }), el("span", { class: "unit" }, "s into the clip")),
    row("Track", el("div", { class: "btns" },
      el("button", { class: "small", onclick: () => { if ((o.track || 1) > 1) { snapshot(); o.track = (o.track || 1) - 1; change(); } } }, "Down"),
      el("b", {}, `V${(o.track || 1) + 1}`),
      el("button", { class: "small", onclick: () => { snapshot(); o.track = Math.min(6, (o.track || 1) + 1); change(); } }, "Up"))),
    el("div", { class: "hint" }, "Drag the block on the Overlays track to move it (up or down for another track), or its ends to trim. A higher track sits on top.")));
  return wrap;
}
function deleteOv(i) { snapshot(); ovList().splice(i, 1); S.sel = null; change(); }

// ---------------------------------------------------------------- effects
const FX_INFO = {
  punch: { label: "Punch in", short: "PUNCH", icon: "⤢", dur: 1.5, to: 1.15, min: 1.05, max: 1.4,
    help: "Snaps in on the word at the start, then eases back out before the end. Use it on a word that needs weight." },
  push: { label: "Slow push", short: "PUSH", icon: "↗", dur: 5, to: 1.08, min: 1.02, max: 1.2,
    help: "A slow drift in from start to end. Good for an opening line or a key statement." },
  flash: { label: "Flash", short: "FLASH", icon: "✦", help: "A white flash that fades over 0.35 s. Use it on a hard cut or a turn in the argument." },
};
const SFX_LEN = { pop: 0.18, tick: 0.09 }, SFX_VOL = { pop: 0.32, tick: 0.26 };
const fxSpan = (f) => [f.t, f.kind === "flash" ? f.t + 0.35 : (f.until ?? f.t + 1)];

function addEffect(kind) {
  const t = r2(Math.max(0, Math.min(S.t, S.dur - 0.5)));
  snapshot();
  if (kind === "pop" || kind === "tick") {
    S.spec.sfx = S.spec.sfx || [];
    S.spec.sfx.push({ kind, t, volume: SFX_VOL[kind] });
    S.sel = { kind: "sfx", i: S.spec.sfx.length - 1 };
  } else {
    const I = FX_INFO[kind], f = { kind, t };
    if (I.dur) { f.until = r2(Math.min(S.dur, t + I.dur)); f.to = I.to; }
    S.spec.fx = S.spec.fx || [];
    S.spec.fx.push(f);
    S.sel = { kind: "fx", i: S.spec.fx.length - 1 };
  }
  closeAddMenu(); change();
}

// drag an effect or sound: body moves it, edges change start / end; snaps to word starts
function startTimedDrag(ev, key, i) {
  ev.stopPropagation(); ev.preventDefault();
  const list = S.spec[key], orig = clone(list[i]), x0 = ev.clientX;
  const mode = ev.target.classList.contains("l") ? "l" : ev.target.classList.contains("r") ? "r" : "m";
  const starts = S.words.map((w) => w.start), ends = S.words.map((w) => w.end);
  let moved = false;
  if (!(S.sel?.kind === key && S.sel.i === i)) { S.sel = { kind: key, i }; drawInspector(); }
  const mv = (e) => {
    if (!moved && Math.abs(e.clientX - x0) < 3) return;
    if (!moved) { snapshot(); moved = true; }
    const d = (e.clientX - x0) / S.pps, f = clone(orig);
    let at = null;
    if (mode === "m") {
      let nt = orig.t + d; [nt, at] = snapTo(nt, starts);
      const len = orig.until != null ? orig.until - orig.t : 0;
      nt = Math.max(0, Math.min(S.dur - Math.max(len, 0.1), nt));
      f.t = r2(nt); if (orig.until != null) f.until = r2(nt + len);
    } else if (mode === "l") {
      let nt = orig.t + d; [nt, at] = snapTo(nt, starts);
      f.t = r2(Math.max(0, Math.min(orig.until - 0.4, nt)));
    } else {
      let nu = orig.until + d; [nu, at] = snapTo(nu, ends);
      f.until = r2(Math.max(orig.t + 0.4, Math.min(S.dur, nu)));
    }
    list[i] = f; showSnap(at); drawTimeline();
  };
  const up = () => {
    removeEventListener("pointermove", mv); removeEventListener("pointerup", up); showSnap(null);
    if (moved) change(); else drawInspector();
    seek(list[i].t);
  };
  addEventListener("pointermove", mv); addEventListener("pointerup", up);
}

function sliderRow(lab, get, set, min, max, step, fmt) {
  const out = el("b", { style: "min-width:52px" }, fmt(get()));
  const rng = el("input", { type: "range", min, max, step, style: "flex:1;min-width:0" }); rng.value = get();
  let snap = false;
  rng.addEventListener("pointerdown", () => (snap = false));
  rng.addEventListener("input", () => { if (!snap) { snapshot(); snap = true; } set(+rng.value); out.textContent = fmt(+rng.value); change({ inspector: false }); });
  return el("div", { class: "row" }, el("label", {}, lab), rng, out);
}

function fxPanel(i) {
  const f = S.spec.fx[i], I = FX_INFO[f.kind] || { label: f.kind, help: "" };
  const wrap = el("div", {}, el("h2", {}, I.label, el("span", { class: "tag" }, "effect")),
    el("div", { class: "sub" }, I.help),
    el("div", { class: "btns" },
      el("button", { onclick: () => seek(Math.max(0, f.t - 0.6)) }, "Play from just before"),
      el("button", { onclick: () => { snapshot(); const d = clone(f); const len = fxSpan(f)[1] - f.t; d.t = r2(Math.min(S.dur - len, fxSpan(f)[1] + 0.5)); if (d.until != null) d.until = r2(d.t + len); S.spec.fx.push(d); S.sel = { kind: "fx", i: S.spec.fx.length - 1 }; change(); } }, "Duplicate"),
      el("button", { class: "danger", onclick: () => { snapshot(); S.spec.fx.splice(i, 1); S.sel = null; change(); } }, "Delete")));
  const timing = [row("Start", ...timeInput(() => f.t, (v) => (f.t = v)))];
  if (f.kind !== "flash") timing.push(row("End", ...timeInput(() => f.until, (v) => (f.until = v))));
  wrap.append(sec("Timing", ...timing));
  if (I.min) wrap.append(sec("Strength", sliderRow("Scale", () => f.to ?? I.to, (v) => (f.to = v), I.min, I.max, 0.01, (v) => `${(+v).toFixed(2)}×`),
    el("div", { class: "hint" }, "Applied on top of the zoom track's punch-ins.")));
  else wrap.append(sec("Strength", sliderRow("Brightness", () => f.strength ?? 0.85, (v) => (f.strength = v), 0.3, 1, 0.05, (v) => `${Math.round(v * 100)}%`)));
  wrap.append(el("div", { class: "hint", style: "margin-top:10px" }, "Use effects sparingly, and not while a card is landing."));
  return wrap;
}

function sfxPanel(i) {
  const f = S.spec.sfx[i];
  return el("div", {}, el("h2", {}, "Sound effect", el("span", { class: "tag" }, f.kind)),
    el("div", { class: "sub" }, "The house style has no sound effects by default. A pop suits a card landing, a tick a list item."),
    sec("Sound", row("Sound", selectOf([["pop", "Pop"], ["tick", "Tick"]], () => f.kind, (v) => (f.kind = v))),
      row("Time", ...timeInput(() => f.t, (v) => (f.t = v))),
      sliderRow("Volume", () => f.volume ?? SFX_VOL[f.kind], (v) => (f.volume = v), 0, 1, 0.01, (v) => `${Math.round(v * 100)}%`)),
    el("div", { class: "btns" },
      el("button", { onclick: () => seek(Math.max(0, f.t - 0.6)) }, "Play from just before"),
      el("button", { class: "danger", onclick: () => { snapshot(); S.spec.sfx.splice(i, 1); S.sel = null; change(); } }, "Delete")));
}

// ---------------------------------------------------------------- takeovers
const isReelFmt = () => (S.spec?.format || "reel") === "reel";
const TK_KINDS = [
  { key: "list", label: "List", help: "a list being named, items on their words", pick: (L) => L.find((k) => k.mode === "full" && k.items && !k.numbered) || L.find((k) => k.items) },
  { key: "pip", label: "Picture-in-picture list", help: "the speaker in a window above the list (reel only)", reelOnly: true, pick: (L) => L.find((k) => k.mode === "pip" && !k.numbered) },
  { key: "stat", label: "Big number", help: "a number or a 'thing one'", pick: (L) => L.find((k) => k.stat && k.stat.count) || L.find((k) => k.stat) },
  { key: "recap", label: "Recap", help: "numbered points, e.g. a closing summary", pick: (L) => L.find((k) => k.numbered && k.mode !== "pip") || L.find((k) => k.numbered) },
  { key: "headline", label: "Big text", help: "one big line that sums up the point", pick: () => ({ mode: "full", kicker: "Key point", title: "Your *point*", t: 0, t_title: 0.12, out: 3.6 }) },
];
const tkKind = (k) => (k.stat ? "stat" : k.numbered ? "recap" : k.items ? (k.mode === "pip" ? "pip" : "list") : "headline");
// Claude writes the takeover from what's said around t; the placeholder is replaced when the reply comes back
async function fillTakeover(obj, kind, t) {
  S.filling = S.filling || new Set(); S.filling.add(obj);
  drawTimeline(); drawInspectorSafe(); setStatus("Claude is writing the takeover…");
  const spec = { ...S.spec, takeovers: (S.spec.takeovers || []).filter((k) => k !== obj) };
  const r = await fetch("/api/takeover/suggest", { method: "POST", body: JSON.stringify({ kind, t, spec }) }).then((x) => x.json()).catch(() => ({ ok: false }));
  S.filling.delete(obj); setStatus();
  const i = (S.spec.takeovers || []).indexOf(obj);
  if (i < 0) { drawTimeline(); return; }                 // undone or deleted in the meantime
  if (!r.ok || !r.takeover) { toast(r.error || "Couldn't fill it in; edit the text in the panel."); drawTimeline(); drawInspectorSafe(); return; }
  snapshot(); S.spec.takeovers[i] = r.takeover;
  change();
  toast(r.how === "claude" ? "Filled in from what's said. Undo (⌘Z) goes back to the placeholder."
    : `Used the sentence at the playhead (${String(r.how).replace(/^fallback: /, "")}).`);
}
function addTakeover(kind) {
  const K = TK_KINDS.find((x) => x.key === kind), tpl = clone(K.pick(S.tkTemplates || []) || { mode: "full", kicker: "Key point", title: "Your *title*", t: 0, out: 4 });
  if (!isReelFmt()) tpl.mode = "full";
  const f = firstRef(tpl), len = (typeof tpl.out === "number" ? tpl.out : lastRef(tpl) + 1.5) - f;
  const at = Math.max(0.1, Math.min(S.t, S.dur - len));
  shiftCard(tpl, r2(at - f));
  if (typeof tpl.out !== "number") tpl.out = r2(at + len);
  snapshot(); (S.spec.takeovers = S.spec.takeovers || []).push(tpl);
  S.sel = { kind: "tk", i: S.spec.takeovers.length - 1 };
  closeAddMenu(); change();
  fillTakeover(tpl, kind, S.t);
}
function deleteTakeover(i) { snapshot(); S.spec.takeovers.splice(i, 1); S.sel = null; change(); }
function tkPanel(i) {
  const k = S.spec.takeovers[i];
  const [s, e] = span(k);
  const wrap = el("div", {}, el("h2", {}, "Takeover", el("span", { class: "tag" }, k.stat ? "big number" : k.numbered ? "numbered" : (isReelFmt() ? k.mode || "full" : "full"))),
    el("div", { class: "sub" }, `${s.toFixed(2)}s – ${e.toFixed(2)}s · gradient cutaway; captions underneath are left out, so give it the words being said`),
    el("div", { class: "btns" },
      el("button", { onclick: () => seek(Math.max(0, s - 0.5)) }, "Play from just before"),
      el("button", { onclick: () => { snapshot(); const d = clone(k); shiftCard(d, Math.min(e - s + 0.5, S.dur - (d.out ?? S.dur))); S.spec.takeovers.push(d); S.sel = { kind: "tk", i: S.spec.takeovers.length - 1 }; change(); } }, "Duplicate"),
      el("button", { class: "danger", onclick: () => deleteTakeover(i) }, "Delete")));
  const busy = S.filling?.has(k);
  wrap.append(sec("Words", busy ? el("div", { class: "note filling" }, "Claude is writing this from what's said here…")
      : el("div", { class: "hint" }, "Fill it in from what's said at its start: the text, and each part landing on its word."),
    el("div", { class: "btns" }, el("button", { class: "small", disabled: busy, onclick: () => fillTakeover(k, tkKind(k), firstRef(k)) }, ic("sparkles"), "Fill from what's said"))));
  if (isReelFmt()) wrap.append(sec("Style", row("Mode", selectOf([["full", "Full: gradient wipe"], ["pip", "Picture-in-picture: speaker above"]], () => k.mode || "full", (v) => (k.mode = v)))));
  else wrap.append(sec("Style", el("div", { class: "hint" }, "Full gradient wipe. Picture-in-picture is for 9:16 reels only.")));
  const content = el("div");
  form(k, content, k, []);          // kicker, title (*word* = underline), numbered, items, or the big number
  content.append(el("div", { class: "btns" },
    !k.stat && !k.items ? el("button", { class: "small", onclick: () => { snapshot(); k.items = [{ text: "First point", t: r2(s + 0.6) }]; change(); } }, "+ Items") : null,
    !k.stat && !k.items?.length ? el("button", { class: "small", onclick: () => { snapshot(); delete k.title; delete k.items; delete k.numbered; k.stat = { value: "01", t: r2(s + 0.25), label: "Your point", t_label: r2(s + 0.5) }; change(); } }, "Make it a big number") : null));
  content.append(el("div", { class: "hint" }, "Items: up to 5 in picture-in-picture, 4 in full; keep each under 28 characters. Logos take any logo name or icon:<lucide name>."));
  wrap.append(sec("Content", content));
  const timing = el("div", { id: "timing" });
  wrap.append(sec(["Timing", el("span", { class: "hint" }, "◆ markers on the block can be dragged")], timing));
  fillTiming(timing, k);
  if (k.out == null) wrap.append(el("div", { class: "hint" }, "No out time: it runs straight into the end screen."));
  return wrap;
}

function reelPanel() {
  const c = cap(), cards = S.spec.cards || [];
  const tpl = S.spec.template || ((S.spec.takeovers || []).length ? "takeover" : "clean");
  const stat = (v, l, sel) => el("button", { class: "stat", onclick: sel || null, disabled: !sel || null }, el("b", {}, String(v)), el("span", {}, l));
  const firstOf = (pred) => { const i = cards.findIndex(pred); return i < 0 ? null : () => { select({ kind: "card", i }); seek(firstRef(cards[i])); }; };
  const wrap = el("div", { class: "summary" },
    el("div", { class: "phead" }, el("h2", {}, S.name),
      el("div", { class: "tags" }, el("span", { class: "tag" }, fmtOf().label), el("span", { class: "tag soft" }, tpl === "takeover" ? "Takeover" : "Clean"))),
    el("div", { class: "stats" },
      stat(fmtT(S.total).replace(/\.\d+$/, ""), "length"),
      stat(cards.filter((x) => TRACK(x) === "cards").length, "cards", firstOf((x) => TRACK(x) === "cards")),
      stat((S.spec.takeovers || []).length, "takeovers", (S.spec.takeovers || []).length ? () => { select({ kind: "tk", i: 0 }); seek(S.spec.takeovers[0].t); } : null),
      stat(groupRanges().length, "captions", groupRanges().length ? () => select({ kind: "cap", g: 0 }) : null),
      stat((S.spec.fx || []).length + (S.spec.sfx || []).length, "effects"),
      stat(S.spec.endcard ? "Yes" : "No", "end screen", S.spec.endcard ? () => { select({ kind: "end" }); seek(S.dur + 2.5); } : null)),
    el("div", { class: "hint", style: "margin:-2px 0 6px" }, "Select anything on the timeline to edit it. Press ? for shortcuts."));
  const w = warnings();
  if (w.list.length) wrap.append(el("div", { class: "issues" }, el("b", {}, ic("triangle-alert"), ` ${w.list.length} timing ${w.list.length === 1 ? "issue" : "issues"}`),
    el("ul", {}, ...w.list.slice(0, 6).map((x) => el("li", {}, x)))));
  if (isLand()) {
    S.spec.layout = S.spec.layout || {};
    wrap.append(sec("Layout",
      row("Cards panel", selectOf([["right", "Right of the speaker"], ["left", "Left of the speaker"], ["centre", "Centre"]],
        () => S.spec.layout.cards || "right", (v) => (S.spec.layout.cards = v))),
      el("div", { class: "hint" }, "Cards are scaled into a side panel; chips sit along its top.")));
  }
  wrap.append(sec("Captions",
    row("Size", bind(el("input", { type: "number", step: "2" }), () => c.size ?? (fmtOf().capSize || 70), (v) => (c.size = v), { num: true }), el("span", { class: "unit" }, "px")),
    row("Top", bind(el("input", { type: "number", step: "2" }), () => c.top ?? (fmtOf().capTop || 990), (v) => (c.top = v), { num: true }), el("span", { class: "unit" }, "px")),
    row("Lead", bind(el("input", { type: "number", step: "0.01" }), () => c.lead ?? 0.05, (v) => (c.lead = v), { num: true }), el("span", { class: "unit" }, "s early")),
    row("Words per line", bind(el("input", { type: "number", step: "1", min: "1", max: "6" }), () => c.max_words ?? 3, (v) => (c.max_words = v), { num: true }),
      el("span", { class: "unit" }, c.groups ? "set by hand" : "auto")),
    c.groups ? el("button", { class: "small", onclick: () => { snapshot(); delete c.groups; S.groups = []; change(); } }, "Reset grouping to automatic") : null,
  ));
  if (!S.spec.endcard) wrap.append(sec("End screen", el("button", { onclick: () => {
    snapshot(); S.spec.endcard = S._lastEnd || { duration: 3.5, lines: standardEnd() }; change();
  } }, "Add end screen")));
  return wrap;
}

// ---------------------------------------------------------------- add / delete
const CARD_HELP = {
  questions: "people keep asking…", hub: "many sources into one", statement: "it's all about X", compare: "X vs Y",
  steps: "a process", feature: "name a key term", tiles: "a list of tools", connect: "tools plugged in",
  chat: "just ask it", task: "runs on its own",
};
const DEFAULTS = {
  text: { type: "text", text: "Your text *here*", style: "glass", anim: "words", t: 0, out: 3 },
  chip: { type: "chip", text: "So how*?*", t: 0, out: 3 },
};
function addCard(type) {
  const tpl = clone(DEFAULTS[type] || S.templates[type]);
  if (!tpl) return toast(`No template for ${type}`);
  delete tpl.top;
  const f = firstRef(tpl), at = Math.max(0.1, Math.min(S.t, S.dur - 1));
  shiftCard(tpl, r2(at - f));
  if (typeof tpl.out !== "number") tpl.out = r2(lastRef(tpl) + 1);
  if (tpl.out > S.dur) shiftCard(tpl, r2(S.dur - tpl.out));
  snapshot(); S.spec.cards.push(tpl);
  S.sel = { kind: "card", i: S.spec.cards.length - 1 };
  closeAddMenu(); change();
}
function deleteCard(i) { snapshot(); S.spec.cards.splice(i, 1); S.sel = null; change(); }

// ---------------------------------------------------------------- save / render
function sortedSpec() {
  const sp = clone(S.spec);
  const order = sp.cards.map((c, i) => [firstRef(c), i]).sort((a, b) => a[0] - b[0]).map((x) => x[1]);
  sp.cards = order.map((i) => sp.cards[i]);
  return { sp, order };
}
async function save() {
  const { sp, order } = sortedSpec();
  setStatus("Saving…");
  const res = await fetch("/api/save", { method: "POST", body: JSON.stringify({ spec: sp }) }).then((r) => r.json()).catch((e) => ({ ok: false, log: String(e) }));
  if (!res.ok) { setStatus("Save failed", "err"); showBanner("Saved reel.json, but the build failed:", res.log, true); return false; }
  if (S.sel?.kind === "card") S.sel.i = order.indexOf(S.sel.i);
  S.spec = sp; S.savedJSON = JSON.stringify(sp); S.dirty = false;
  try { localStorage.removeItem("draft:" + S.path); } catch (e) {}
  drawTimeline(); drawInspector(); setStatus();
  toast(`Saved. The previous version is in .editor/backups/${res.backup}`);
  return true;
}
const tilde = (p) => String(p || "").replace(/^\/Users\/[^/]+/, "~");
async function renderReel() {
  const target = await fetch("/api/render/target").then((r) => r.json()).catch(() => ({}));
  const box = el("div", { class: "box" });
  const title = el("input", { type: "text", class: "grow", value: S.name });
  const where = el("div", { class: "note" });
  const showWhere = () => { where.textContent = `Saves to ${tilde(target.folder)}/${(title.value.trim() || "Video").replace(/[\\/:*?"<>|]+/g, "-")}.mp4`; };
  title.addEventListener("input", showWhere); showWhere();
  const go = el("button", { class: "primary" }, "Save and render");
  box.append(el("h3", {}, "Render the final video"), row("File name", title), where,
    el("div", { class: "hint" }, `Finished videos are filed by format in ${target.renders || "06. Renders"}/${target.format || ""}. If a video with this name is already there, it moves to "Previous versions" rather than being replaced. Rendering at delivery quality can take a few minutes.`),
    el("div", { class: "btns", style: "justify-content:flex-end;margin-top:14px" }, el("button", { onclick: closeModal }, "Cancel"), go));
  openModal(box);
  go.onclick = async () => {
    go.disabled = true;
    if (S.dirty && !(await save())) { closeModal(); return; }
    const r = await fetch("/api/render", { method: "POST", body: JSON.stringify({ title: title.value.trim() || S.name }) });
    if (r.status === 409) toast("A render is already running.");
    renderProgress();
  };
}
async function renderProgress() {
  const pre = el("pre", {}, "Starting…"), head = el("h3", {}, "Rendering…"), done = el("div");
  const stop = el("button", { class: "danger", onclick: () => fetch("/api/render/stop", { method: "POST" }) }, "Stop");
  const close = el("button", { onclick: closeModal }, "Hide");
  const btns = el("div", { class: "btns", style: "justify-content:flex-end" }, stop, close);
  openModal(el("div", { class: "box" }, head, done, pre, btns));
  const poll = async () => {
    const s = await fetch("/api/render").then((r) => r.json()).catch(() => null);
    if (!s) return setTimeout(poll, 2000);
    pre.textContent = s.log.slice(-25).join("\n") || "Starting…"; pre.scrollTop = 1e9;
    if (s.running) { head.textContent = `Rendering… ${Math.round(s.elapsed)}s`; setTimeout(poll, 1500); }
    else {
      stop.remove();
      head.textContent = s.code === 0 ? "Render finished" : `Render stopped (exit code ${s.code})`;
      if (s.code === 0) {
        done.append(el("div", { class: "note ok" }, `Saved to ${tilde(s.output)}`));
        btns.prepend(window.PORTAL ? el("button", { class: "primary", onclick: () => downloadFile(s.output) }, ic("download"), "Download")
          : el("button", { class: "primary", onclick: () => fetch("/api/reveal", { method: "POST", body: JSON.stringify({ path: s.output }) }) }, "Show in Finder"));
        if (window.openPosts) btns.prepend(el("button", { onclick: () => { closeModal(); window.openPosts(); } }, ic("send"), "Prepare posts"));
      }
    }
  };
  poll();
}
function showShortcuts() {
  const keys = [["Space", "Play or pause"], ["← / →", "Back or forward one frame"], ["⇧ ← / ⇧ →", "Back or forward one second"],
    ["Home / End", "Go to the start or end"], ["⌘Z / ⇧⌘Z", "Undo / redo"], ["⌘S", "Save"], ["⌫", "Delete the selected block, clip or marked range"],
    ["S", "Split the video at the playhead"], ["I / O", "Mark the start / end of a part to remove"],
    ["Esc", "Deselect, close menus"], ["Alt while dragging", "Drag freely (no snapping to words)"], ["⌘ + scroll", "Zoom the timeline"], ["?", "This list"]];
  openModal(el("div", { class: "box shortcuts" }, el("h3", {}, "Keyboard shortcuts"),
    el("div", { class: "keys" }, ...keys.flatMap(([k, d]) => [el("span", { class: "kbd" }, k), el("span", {}, d)])),
    el("div", { class: "hint", style: "margin-top:12px" }, "On the timeline: drag a block to move it, drag its edges to change when it starts or ends, drag a ◆ marker to retime one part. Click a caption, then a word, to edit it."),
    el("div", { class: "btns", style: "justify-content:flex-end;margin-top:14px" }, el("button", { class: "primary", onclick: closeModal }, "Got it"))));
}
// common panel buttons get their icons
const BTN_ICONS = { "Delete": "trash-2", "Duplicate": "copy", "Go to start": "skip-back", "Play from just before": "circle-play",
  "Go to caption": "circle-play", "Go to end screen": "circle-play", "Remove end screen": "trash-2", "+ Add": "plus", "Apply": "check", "Discard": "x" };
function decorateButtons(root) {
  root.querySelectorAll("button").forEach((b) => {
    const k = b.textContent.trim().replace(/^Apply .*/, "Apply");
    if (BTN_ICONS[k] && !b.querySelector("svg")) b.insertAdjacentHTML("afterbegin", icon(BTN_ICONS[k]));
  });
}
function openModal(box) { const m = $("#modal"); m.innerHTML = ""; m.append(box); m.hidden = false; }
function closeModal() { $("#modal").hidden = true; }
let toastT = 0;
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), 3500); }
function showBanner(msg, log, err) {
  const b = $("#banner"); b.innerHTML = ""; b.className = "banner" + (err ? " err" : ""); b.hidden = false;
  b.append(el("span", {}, msg), log ? el("pre", {}, log) : null, el("button", { class: "small", onclick: hideBanner }, "Dismiss"));
}
function hideBanner() { $("#banner").hidden = true; }

// ---------------------------------------------------------------- boot
async function boot() {
  const p = await fetch("/api/project").then((r) => r.json());
  S.caps = p.caps || {};
  if (await resumeWizardJob()) return;
  if (shouldSplash()) showSplash(p);
  if (p.none) { document.body.classList.add("no-reel"); $("#projName").textContent = ""; setStatus(" "); showHome(true); return; }
  Object.assign(S, { spec: p.spec, words: p.transcript, icons: p.icons, logos: p.logos, templates: p.templates, tkTemplates: p.takeoverTemplates || [], name: p.name, path: p.path });
  S.spec.cards = S.spec.cards || []; S.spec.fx = S.spec.fx || []; S.spec.sfx = S.spec.sfx || [];
  S.savedJSON = JSON.stringify(S.spec);
  document.title = `${p.name} · Studio AI`;
  $("#projName").textContent = p.name;
  if (window.updateBrandChip) updateBrandChip();
  $("#dl-icons").append(...p.icons.map((n) => el("option", { value: n })));
  $("#dl-logos").append(...p.logos.map((n) => el("option", { value: n })));
  computeTotals();



  try {
    const draft = localStorage.getItem("draft:" + S.path);
    if (draft && draft !== S.savedJSON) {
      const b = $("#banner"); b.className = "banner"; b.hidden = false; b.innerHTML = "";
      b.append(el("span", {}, "You have unsaved changes from your last session."),
        el("button", { class: "small", onclick: () => { snapshot(); S.spec = JSON.parse(draft); hideBanner(); change(); } }, "Restore them"),
        el("button", { class: "small", onclick: () => { localStorage.removeItem("draft:" + S.path); hideBanner(); } }, "Discard"));
    }
  } catch (e) {}

  S.pps = Math.max(12, Math.min(120, Math.floor(($("#scroller").clientWidth - 40) / Math.max(10, Math.min(S.total, 45)))));
  $("#zoom").value = S.pps;
  fitScreen(); drawTimeline(); drawInspector(); setStatus();
  buildPreview();
  fetch("/api/peaks").then((r) => r.json()).then((d) => { S.peaks = d.peaks; S.perSec = d.perSec; drawWave(); });
  fetch("/api/edl").then((r) => r.json()).then((d) => {
    S.rawDur = d.raw_dur || null;
    // the planner can run a little past the end of the camera file; the render stops there, so do the same
    // (inserts, segments with src, sit in their own virtual range past the camera file: see cuts.py)
    S.edlRaw = (d.raw_segments || []).map((s) => ({ ...s, out: S.rawDur && !s.src ? Math.min(s.out, S.rawDur) : s.out })).filter((s) => s.out - s.in > 0.01);
    S.edl = d.segments || [];
    S.edlInfo = { raw: d.raw, editable: d.editable }; drawTimeline(); drawInspectorSafe();
    try {
      const rep = JSON.parse(sessionStorage.getItem("cutReport") || "null"); sessionStorage.removeItem("cutReport");
      if (rep) {
        const gone = Object.values(rep.removed || {}).reduce((a, b) => a + b, 0);
        toast(`Cut applied: ${fmtT(rep.old_dur || 0)} → ${fmtT(rep.new_dur || 0)}${gone ? `, ${gone} item${gone > 1 ? "s" : ""} inside removed parts deleted` : ""}.`);
      }
    } catch (e) {}
    if (d.zoomjob?.running && d.zoomjob.proj === S.path) pollZoomJob();
  });
  fetch("/api/filmstrip").then((r) => r.json()).then((d) => {
    if (d.error || !d.count) return;
    const img = new Image();
    img.onload = () => { S.film = { ...d, img }; drawFilm(); };
    img.src = "/api/filmstrip.jpg?v=" + d.key[1];
  });
}

// light / dark mode
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("theme", theme); } catch (e) {}
  const b = $("#themeBtn"), next = theme === "dark" ? "light" : "dark";
  b.title = b.ariaLabel = `Switch to ${next} mode`;
  if (S.spec) { drawWave(); }
}
$("#themeBtn").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");

// controls
$("#play").onclick = togglePlay;
$("#back").onclick = () => seek(S.t - 1 / S.fps);
$("#fwd").onclick = () => seek(S.t + 1 / S.fps);
$("#mute").onclick = () => { S.muted = !S.muted; $("#mute").innerHTML = icon(S.muted ? "volume-x" : "volume-2"); $("#mute").title = S.muted ? "Unmute" : "Mute"; frames().forEach((f) => f.contentWindow?.__editor?.setMuted(S.muted)); };
$("#toStart").onclick = () => seek(0);
$("#toEnd").onclick = () => seek(S.total);
$("#helpBtn").onclick = showShortcuts;
$("#undo").onclick = undo; $("#redo").onclick = redo;
$("#splitBtn").onclick = () => splitAt(S.t);
$("#addBlur").onclick = addBlur;
$("#addVideo").onclick = addOverlay;
$("#ovl").addEventListener("pointerdown", ovPointerDown);
addEventListener("resize", () => drawOverlay());
$("#markIn").onclick = () => setMark("a", S.t);
$("#markOut").onclick = () => setMark("b", S.t);
$("#save").onclick = save; $("#render").onclick = renderReel;
// add buttons: + Text and + Chip add straight away; Card, Takeover and Effect open a single-column list
const FX_ITEMS = [["punch", "Punch in", "a word that needs weight"], ["push", "Slow push", "an opening or key line"], ["flash", "Flash", "a hard cut or a turn"],
  ["pop", "Pop sound", "a card landing"], ["tick", "Tick sound", "a list item"]];
const pretty1 = (t) => t.charAt(0).toUpperCase() + t.slice(1);
const MENUS = {
  cardMenu: () => Object.entries(CARD_HELP).filter(([k]) => S.templates[k]).map(([k, h]) => [pretty1(k), h, () => addCard(k)]),
  tkMenu: () => TK_KINDS.filter((K) => !K.reelOnly || isReelFmt()).map((K) => [K.label, K.help, () => addTakeover(K.key)]),
  fxMenu: () => FX_ITEMS.map(([k, n, h]) => [n, h, () => addEffect(k)]),
};
function closeAddMenu() { Object.keys(MENUS).forEach((id) => ($("#" + id).hidden = true)); }
function openMenu(id, btn) {
  const m = $("#" + id), wasOpen = !m.hidden;
  closeAddMenu();
  if (wasOpen) return;
  m.innerHTML = "";
  MENUS[id]().forEach(([label, help, fn]) => m.append(el("button", { onclick: fn }, label, el("small", {}, help))));
  // opens upwards from the timeline bar: never taller than the room above the button (it scrolls instead)
  m.style.maxHeight = Math.max(160, btn.getBoundingClientRect().top - 12) + "px";
  m.hidden = false; m.scrollTop = 0;
}
$("#addText").onclick = () => { closeAddMenu(); addCard("text"); };
$("#addChip").onclick = () => { closeAddMenu(); addCard("chip"); };
[["addCard", "cardMenu"], ["addTk", "tkMenu"], ["addFx", "fxMenu"]].forEach(([b, m]) =>
  ($("#" + b).onclick = (e) => { e.stopPropagation(); openMenu(m, e.currentTarget); }));
document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) closeAddMenu(); });
$("#zoom").oninput = (e) => {
  const sc = $("#scroller"), centre = (sc.scrollLeft + sc.clientWidth / 2) / S.pps;
  S.pps = +e.target.value; drawTimeline(); sc.scrollLeft = X(centre) - sc.clientWidth / 2;
};
$("#scroller").addEventListener("wheel", (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  e.preventDefault();
  const z = $("#zoom"); z.value = Math.max(12, Math.min(320, S.pps * (e.deltaY < 0 ? 1.12 : 1 / 1.12))); z.oninput({ target: z });
}, { passive: false });
$("#content").addEventListener("pointerdown", scrubStart);
addEventListener("resize", () => { fitScreen(); drawWave(); drawFilm(); });
addEventListener("keydown", (e) => { if (e.key === "Alt") window.__alt = true; });
addEventListener("keyup", (e) => { if (e.key === "Alt") window.__alt = false; });
addEventListener("keydown", (e) => {
  const typing = e.target.closest("input, textarea, select");
  const mod = e.metaKey || e.ctrlKey;
  if ($("#splash") || wizardOpen()) {        // splash / new-video wizard: only Esc and typing
    if (e.key === "Escape" && wizardOpen() && W.step < 3) { closeWizard(); if (!S.spec || S.mode === "new") showHome(true); }
    return;
  }
  if ($("#lfview") && !$("#lfview").hidden) return;     // the long-form editor has its own keys
  if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); if (S.spec && S.mode !== "new") save(); return; }
  if (typing) return;
  if (!$("#home").hidden || S.mode === "new") { if (e.key === "Escape" && S.spec && S.mode !== "new") hideHome(); return; }
  if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
  if (e.key === " ") { e.preventDefault(); togglePlay(); }
  else if (e.key === "Home") { e.preventDefault(); seek(0); }
  else if (e.key === "End") { e.preventDefault(); seek(S.total); }
  else if (e.key === "?") { e.preventDefault(); showShortcuts(); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); seek(S.t - (e.shiftKey ? 1 : 1 / S.fps)); }
  else if (e.key === "ArrowRight") { e.preventDefault(); seek(S.t + (e.shiftKey ? 1 : 1 / S.fps)); }
  else if (e.key.toLowerCase() === "s" && !mod) { e.preventDefault(); splitAt(S.t); }
  else if (e.key.toLowerCase() === "i" && !mod) { e.preventDefault(); setMark("a", S.t); }
  else if (e.key.toLowerCase() === "o" && !mod) { e.preventDefault(); setMark("b", S.t); }
  else if ((e.key === "Backspace" || e.key === "Delete") && S.sel?.kind === "clip") { e.preventDefault(); deleteClip(S.sel.i); }
  else if ((e.key === "Backspace" || e.key === "Delete") && S.sel?.kind === "rd") { e.preventDefault(); deleteRd(S.sel.i); }
  else if ((e.key === "Backspace" || e.key === "Delete") && S.sel?.kind === "ov") { e.preventDefault(); deleteOv(S.sel.i); }
  else if ((e.key === "Backspace" || e.key === "Delete") && !S.sel && markRange()) { e.preventDefault(); deleteRange(...markRange()); }
  else if ((e.key === "Backspace" || e.key === "Delete") && S.sel?.kind === "card") { e.preventDefault(); deleteCard(S.sel.i); }
  else if ((e.key === "Backspace" || e.key === "Delete") && S.sel?.kind === "tk") { e.preventDefault(); deleteTakeover(S.sel.i); }
  else if ((e.key === "Backspace" || e.key === "Delete") && (S.sel?.kind === "fx" || S.sel?.kind === "sfx")) { e.preventDefault(); snapshot(); S.spec[S.sel.kind].splice(S.sel.i, 1); S.sel = null; change(); }
  else if (e.key === "Escape") { closeModal(); closeAddMenu(); if (!S.sel && S.mark) clearMarks(); else select(null); }
});
addEventListener("beforeunload", (e) => { if ((S.dirty || pendingZooms().length || S.cut) && !S.leaving) { e.preventDefault(); e.returnValue = ""; } });

// resizable timeline (drag its top edge) and side panel (drag its left edge); each browser remembers the sizes
const store = { get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} } };
(() => {
  const tl = $(".timeline"), h = el("div", { class: "resizer", title: "Drag to resize the timeline (double-click to reset)" }); tl.prepend(h);
  const fit = (px) => Math.max(220, Math.min(innerHeight - 260, px));
  const saved = +store.get("tlHeight"); if (saved) tl.style.height = fit(saved) + "px";
  h.addEventListener("pointerdown", (e) => {
    const y0 = e.clientY, h0 = tl.offsetHeight;
    document.body.classList.add("resizing");
    const mv = (ev) => { tl.style.height = fit(h0 - (ev.clientY - y0)) + "px"; fitScreen(); };
    const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); document.body.classList.remove("resizing"); store.set("tlHeight", tl.offsetHeight); drawWave(); };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  });
  h.addEventListener("dblclick", () => { tl.style.height = ""; store.set("tlHeight", ""); fitScreen(); drawWave(); });
})();
(() => {
  const top = $(".top"), h = el("div", { class: "vresizer", title: "Drag to resize the side panel (double-click to reset)" }); top.append(h);
  const fit = (px) => Math.round(Math.max(300, Math.min(Math.min(760, innerWidth - 480), px)));
  const set = (px) => { document.documentElement.style.setProperty("--insp-w", fit(px) + "px"); fitScreen(); };
  const saved = +store.get("inspWidth"); if (saved) set(saved);
  h.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    const x0 = e.clientX, w0 = $(".inspector").offsetWidth;
    document.body.classList.add("resizing"); h.classList.add("on");
    const mv = (ev) => set(w0 - (ev.clientX - x0));
    const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); document.body.classList.remove("resizing"); h.classList.remove("on"); store.set("inspWidth", $(".inspector").offsetWidth); };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  });
  h.addEventListener("dblclick", () => { document.documentElement.style.removeProperty("--insp-w"); store.set("inspWidth", ""); fitScreen(); });
  addEventListener("resize", () => { const w = +store.get("inspWidth"); if (w) set(w); });
})();
