// Long-form editor: preview that plays the cuts, a zoomable timeline for the whole hour (chapters, lower-thirds, cards,
// waveform), an inspector, undo/redo and save. Edits longform.json. Loaded by long.js; uses its helpers (el, ic, $, toast, S).
"use strict";

const LFE = (() => {
  const get = (p) => fetch(p).then((r) => r.json());
  const post = (p, b) => fetch(p, { method: "POST", body: JSON.stringify(b || {}) }).then((r) => r.json());
  const mmss = (t) => { t = Math.max(0, Math.round(t)); const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60; return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`; };
  const clock = (t) => { const m = Math.floor(t / 60), s = t - m * 60; return `${m}:${s.toFixed(1).padStart(4, "0")}`; };
  const parseT = (v) => { const p = String(v).trim().split(":").map(Number); if (!p.length || p.some((x) => isNaN(x))) return null; return p.reduce((a, x) => a * 60 + x, 0); };
  const r2 = (x) => Math.round(x * 100) / 100;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const LANES = { ch: "Chapters", lt: "Lower-thirds", cd: "Cards", ov: "Overlays", rd: "Blur" };
  const LANE_KEYS = ["ch", "lt", "cd", "ov", "rd"];
  const RD_NAMES = { blur: "Blur", pixel: "Pixelate", box: "Box" };
  const MIN_CH = 10;

  let E = null, raf = 0;
  const stopAll = () => { cancelAnimationFrame(raf); raf = 0; const v = $("#lfVideo"); if (v) v.pause(); E = null; };

  // ---------------------------------------------------------------- state helpers
  const list = (k) => (k === "ch" ? E.spec.chapters : k === "lt" ? E.spec.lowerThirds : k === "rd" ? E.spec.redactions : k === "ov" ? E.spec.overlays : E.spec.cards);
  const dur = (o) => (o.dur != null ? o.dur : 0);
  function toRaw(t) {
    const { segs, offs } = E; if (!segs.length) return t;
    let lo = 0, hi = offs.length - 1; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (offs[m] <= t) lo = m; else hi = m - 1; }
    return segs[lo].in + Math.min(Math.max(0, t - offs[lo]), segs[lo].out - segs[lo].in);
  }
  // Inserts (Studio AI) are segments with "src": another file, kept in its own virtual range of camera time (100000 s
  // and up, see cuts.py), so range comparisons never mix it with the camera. Playback follows the segment list in order
  // (E.k = the segment playing); an insert plays in its own <video> (E.insV) while the camera video waits.
  const SPACE = (x) => Math.floor(x / 100000);
  const isIns = (s) => !!(s && s.src);
  function editedNow() {
    const v = $("#lfVideo"); if (!E.segs.length) return v.currentTime;
    if (E.insK != null && E.insV) {
      const s = E.segs[E.insK]; if (!s) return E.t;
      return Math.min(E.total, E.offs[E.insK] + clamp(E.insV.currentTime - (s.in - s.vbase), 0, s.out - s.in));
    }
    const k = Math.min(E.k || 0, E.segs.length - 1), s = E.segs[k];
    if (isIns(s)) return E.t;
    return Math.min(E.total, E.offs[k] + Math.max(0, Math.min(v.currentTime, s.out) - s.in));
  }
  function nearestWord(t, within) {
    const W = E.words; if (!W.length) return null;
    let lo = 0, hi = W.length - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (W[m].start < t) lo = m + 1; else hi = m; }
    let best = null;
    for (const j of [lo - 1, lo]) if (W[j] && Math.abs(W[j].start - t) <= within && (best === null || Math.abs(W[j].start - t) < Math.abs(best - t))) best = W[j].start;
    return best;
  }
  const snapT = (t, ev) => (E.snap && !(ev && ev.altKey) ? nearestWord(t, 10 / E.pps) ?? t : t);

  // history
  let lastKey = "", lastAt = 0;
  function snapshot(key) {
    const now = Date.now();
    if (key && key === lastKey && now - lastAt < 1500) { lastAt = now; return; }
    lastKey = key || ""; lastAt = now;
    E.undo.push(stateJ()); if (E.undo.length > 100) E.undo.shift(); E.redo = [];
  }
  function touch() { E.dirty = true; S.dirty = true; setStatus(); if (E.undoB) { E.undoB.disabled = !E.undo.length; E.redoB.disabled = !E.redo.length; } }
  const ids = new WeakMap(); let nextId = 1;
  const idOf = (o) => { if (!ids.has(o)) ids.set(o, nextId++); return ids.get(o); };
  function setStatus() { const s = $("#lfeStatus"); if (s) { s.textContent = E.dirty ? "Unsaved changes" : "Saved"; s.className = "lfe-status" + (E.dirty ? " dirty" : ""); } }
  const stateJ = () => JSON.stringify({ spec: E.spec, segs: E.segs });
  function restore(json) {
    const o = JSON.parse(json);
    E.spec = o.spec;
    if (JSON.stringify(o.segs) !== JSON.stringify(E.segs)) {
      setSegs(o.segs); E.segsDirty = true; wordsForCut(null);
    }
    E.sel = null; E.clipSel = null; touch(); renderAll();
  }
  // camera-time words through the cut list (the same mapping the pipeline uses), so brought-back material has its words
  function mapToEdit(words, segs) {
    // camera clips only (inserts have no words), in camera order, each with its place on the edited timeline
    const offs = []; let o = 0; segs.forEach((s) => { offs.push(o); o += s.out - s.in; });
    const cam = segs.map((s, i) => [s, offs[i]]).filter(([s]) => !isIns(s)).sort((a, b) => a[0].in - b[0].in);
    const out = []; let k = 0;
    for (const w of words) {
      const mid = (w.start + w.end) / 2;
      while (k < cam.length && cam[k][0].out < mid - 1e-6) k++;
      if (k >= cam.length) break;
      const [s, off] = cam[k]; if (mid < s.in - 1e-6) continue;
      const d = off - s.in;
      out.push({ text: w.text, start: rnd(Math.max(w.start, s.in) + d), end: rnd(Math.min(w.end, s.out) + d) });
    }
    return out;
  }
  function wordsForCut(f) {
    if (E.rawWords) E.words = mapToEdit(E.rawWords, E.segs);
    else if (f) E.words = E.words.flatMap((w) => { const a = f(w.start), m = f((w.start + w.end) / 2); return m.kept ? [{ ...w, start: a.t, end: rnd(a.t + w.end - w.start) }] : []; });
    else refreshWords();
  }
  function refreshWords() { get(`/api/long/words?root=${encodeURIComponent(E.root)}`).then((w) => { if (E && Array.isArray(w)) { E.words = w; paint(); } }).catch(() => {}); }
  const undo = () => { if (!E.undo.length) return; E.redo.push(stateJ()); restore(E.undo.pop()); };
  const redo = () => { if (!E.redo.length) return; E.undo.push(stateJ()); restore(E.redo.pop()); };
  function fixChapters() {
    const c = E.spec.chapters; c.sort((a, b) => a.start - b.start);
    if (c.length) c[0].start = 0;
    c.forEach((x, i) => { x.start = r2(x.start); x.end = r2(i + 1 < c.length ? c[i + 1].start : E.total); });
  }
  function sortAll() { E.spec.lowerThirds.sort((a, b) => a.t - b.t); E.spec.cards.sort((a, b) => a.t - b.t); E.spec.redactions.sort((a, b) => a.t - b.t); E.spec.overlays.sort((a, b) => a.t - b.t); fixChapters(); }

  // ---------------------------------------------------------------- screen
  async function show(root, d, view) {
    stopAll();
    const segs = d.edl || [], offs = []; let o = 0;
    segs.forEach((s) => { offs.push(o); o += s.out - s.in; });
    E = { root, meta: d.meta, spec: d.spec, d, segs, offs, words: [], peaks: null, total: d.spec.duration, t: 0, pps: 1, sel: null, undo: [], redo: [], dirty: false, snap: true, playing: false, clipSel: null, mark: null, segsDirty: false };
    // the AI studio panel (short-form app/studio.js) works for this video while the editor is open
    window.LF_STUDIO = {
      kind: "long", root, pickMedia: !window.PORTAL,   // the portal uploads instead of linking from Finder
      api: (p) => `/api/long/studio/${p}${p.includes("?") ? "&" : "?"}root=${encodeURIComponent(root)}`,
      file: (p) => `/long/studio/${p}?root=${encodeURIComponent(root)}`,
      overlay: (c) => addAiOverlay(c),
      insert: (c) => insertClip(c),
    };
    S.dirty = false;
    E.spec.redactions = E.spec.redactions || [];
    E.spec.overlays = E.spec.overlays || []; E.ovEls = new Map();
    E.rdEls = new Map(); mounted = {};
    E.spec.captions = Object.assign({ on: true, style: "words", size: 54, bottom: 120 }, E.spec.captions || {});
    E.spec.chapters.forEach((c, i, a) => { c.end = i + 1 < a.length ? a[i + 1].start : E.total; });
    get(`/api/long/words?root=${encodeURIComponent(root)}`).then((w) => { if (E && E.root === root && Array.isArray(w)) { E.words = w; paint(); } }).catch(() => {});
    get(`/api/long/words?raw=1&root=${encodeURIComponent(root)}`).then((w) => { if (E && E.root === root && Array.isArray(w)) E.rawWords = w; }).catch(() => {});
    get(`/api/long/peaks?root=${encodeURIComponent(root)}`).then((p) => { if (E && E.root === root && p.peaks) { E.peaks = p; drawCanvas(); } }).catch(() => {});

    view.innerHTML = ""; view.classList.add("lfe-host");
    const vid = el("video", { id: "lfVideo", class: "lf-vid", preload: "metadata", playsInline: true, src: `/api/long/video?root=${encodeURIComponent(root)}` });
    E.ov = el("div", { class: "ov-root" });
    E.rdLayer = el("div", { class: "lfe-rdlayer" });
    E.vLayer = el("div", { class: "lfe-vlayer" });
    E.stage = el("div", { class: "lfe-stage" }, vid, E.vLayer, E.rdLayer, E.ov);
    E.stage.addEventListener("pointerdown", ovDrag);
    E.stageBox = el("div", { class: "lfe-stagebox" }, E.stage);
    E.play = el("button", { class: "playbtn", title: "Play / pause (Space)", "aria-label": "Play" }, ic("play"));
    E.tc = el("span", { class: "tc" }, "");
    E.ins = el("div", { class: "lfe-ins" });

    const btn = (icon, label, fn, title, cls) => el("button", { class: cls || "", onclick: fn, title: title || label, "aria-label": label }, ic(icon), label && !cls?.includes("icon") ? label : null);
    E.undoB = btn("undo-2", "Undo", undo, "Undo (⌘Z)", "icon"); E.redoB = btn("redo-2", "Redo", redo, "Redo (⇧⌘Z)", "icon");
    const top = el("div", { class: "lfe-top" },
      el("button", { class: "ghost", onclick: leaveEditor }, ic("arrow-left"), "Videos"),
      el("h2", { class: "lfe-name" }, d.meta.name), brandSwitch(), el("span", { id: "lfeStatus", class: "lfe-status" }, "Saved"),
      el("span", { class: "lfe-sp" }), E.undoB, E.redoB,
      window.PORTAL ? null : el("button", { onclick: () => post("/api/long/reveal", { root, what: "folder" }), title: "Show the project folder" }, ic("folder")),
      el("button", { onclick: save, title: "Save longform.json (⌘S)" }, ic("save"), "Save"),
      el("button", { class: "primary", onclick: openRender, title: "Save and render the final MP4" }, ic("clapperboard"), "Render"));

    // timeline
    E.canvas = el("canvas", { class: "lfe-cv" });
    E.lanes = {}; LANE_KEYS.forEach((k) => (E.lanes[k] = el("div", { class: `lfe-lane ${k}` })));
    E.ph = el("div", { class: "lfe-ph" });
    E.clLane = el("div", { class: "lfe-lane cl" });
    E.clLane.onpointerdown = (e) => { if (e.target === E.clLane) { E.clipSel = null; renderClips(); renderInspector(); const r = E.clLane.getBoundingClientRect(); seekTo((e.clientX - r.left) / E.pps); } };
    E.inner = el("div", { class: "lfe-inner" }, E.canvas, E.clLane, E.lanes.ch, E.lanes.lt, E.lanes.cd, E.lanes.ov, E.lanes.rd, E.ph);
    E.scroll = el("div", { class: "lfe-scroll" }, E.inner);
    const heads = el("div", { class: "lfe-heads" }, el("div", { class: "lfe-head ruler" }), el("div", { class: "lfe-head audio" }, ic("audio-lines"), "Audio"),
      el("div", { class: "lfe-head cl" }, ic("film"), "Video", el("b", {}, "")),
      ...LANE_KEYS.map((k) => el("div", { class: `lfe-head ${k}` }, LANES[k], el("b", {}, ""))));
    E.heads = heads;
    const zoom = el("input", { type: "range", min: 0, max: 100, value: 0, title: "Zoom (⌘ + scroll)" });
    zoom.oninput = () => setZoom(Number(zoom.value) / 100); E.zoom = zoom;
    const snap = el("label", { class: "switch lfe-snap", title: "Snap moves to the start of a word (hold Alt to switch off)" }, el("input", { type: "checkbox", checked: true }), el("span"), "Snap to words");
    snap.querySelector("input").onchange = (e) => { E.snap = e.target.checked; };
    const cardMenu = el("div", { class: "lfe-menu", hidden: true },
      el("button", { onclick: () => addCard("keypoint") }, "Key point"), el("button", { onclick: () => addCard("stat") }, "Stat"), el("button", { onclick: () => addCard("list") }, "List"));
    const cardBtn = el("button", { onclick: (e) => { e.stopPropagation(); cardMenu.hidden = !cardMenu.hidden; } }, ic("layout-template"), "Card", ic("chevron-right"));
    document.addEventListener("click", () => { cardMenu.hidden = true; });
    const tools = el("div", { class: "lfe-tools" },
      el("button", { onclick: addLT }, ic("type"), "Lower-third"), el("div", { class: "lfe-menuwrap" }, cardBtn, cardMenu),
      el("button", { onclick: addChapter }, ic("flag"), "Chapter"),
      el("button", { onclick: addOverlayVideo, title: "Lay another video over this one: an insert, B-roll or a testimonial" }, ic("video"), "Video"),
      el("button", { onclick: addRedaction, title: "Blur, pixelate or hide part of the picture" }, ic("layers"), "Blur"),
      el("button", { onclick: deleteSel, title: "Delete the selected item (Delete)" }, ic("trash-2"), "Delete"),
      el("span", { class: "lfe-div" }),
      el("button", { onclick: () => splitAt(E.t), title: "Split the video at the playhead (S)" }, ic("scissors"), "Split"),
      el("button", { class: "icon", onclick: () => setMark("a", E.t), title: "Mark the start of a part to remove (I)", "aria-label": "Mark in" }, ic("bracket-in")),
      el("button", { class: "icon", onclick: () => setMark("b", E.t), title: "Mark the end of a part to remove (O)", "aria-label": "Mark out" }, ic("bracket-out")),
      (E.cutbar = el("span", { class: "lfe-cutbar" })),
      el("span", { class: "lfe-sp" }), snap, el("button", { onclick: () => setZoom(0), title: "Fit the whole video" }, "Fit"), ic("zoom-in"), zoom);
    const tl = el("div", { class: "lfe-tl" }, tools, el("div", { class: "lfe-tlbody" }, heads, E.scroll));

    view.append(el("div", { class: "lfe" }, top,
      el("div", { class: "lfe-main" },
        el("div", { class: "lfe-left" }, E.stageBox, el("div", { class: "lfe-transport" }, E.play, E.tc, el("span", { class: "hint" }, "Space plays · ← → move 1 s · S split · I / O mark a part to cut · ⌘Z undo · ⌘S save"))),
        el("aside", { class: "lfe-right" }, E.ins)), tl));

    // video + transport
    E.play.onclick = toggle; vid.onclick = toggle;
    vid.onplay = () => { E.play.innerHTML = ""; E.play.append(ic("pause")); };
    vid.onpause = () => { E.play.innerHTML = ""; E.play.append(ic("play")); paint(); };
    vid.onseeked = paint;
    vid.onloadedmetadata = () => { const c = E.segs.find((x) => !isIns(x)); if (c && vid.currentTime < c.in) vid.currentTime = c.in; E.k = 0; if (isIns(E.segs[0])) enterIns(0, 0, false); paint(); };
    // timeline interaction
    E.scroll.onscroll = () => { drawCanvas(); };
    E.scroll.addEventListener("wheel", (e) => {
      if (e.ctrlKey || e.metaKey) { e.preventDefault(); const r = E.scroll.getBoundingClientRect(), tAt = (E.scroll.scrollLeft + e.clientX - r.left) / E.pps; setZoom(zoomFrac() - e.deltaY * 0.004, tAt, e.clientX - r.left); }
      else if (Math.abs(e.deltaX) < Math.abs(e.deltaY)) { e.preventDefault(); E.scroll.scrollLeft += e.deltaY; }
    }, { passive: false });
    E.canvas.onpointerdown = (e) => { const r = E.canvas.getBoundingClientRect(); E.dragPh = true; E.canvas.setPointerCapture(e.pointerId); seekTo((E.scroll.scrollLeft + e.clientX - r.left) / E.pps); };
    E.canvas.onpointermove = (e) => { if (E.dragPh) { const r = E.canvas.getBoundingClientRect(); seekTo((E.scroll.scrollLeft + e.clientX - r.left) / E.pps); } };
    E.canvas.onpointerup = () => { E.dragPh = false; };
    Object.values(E.lanes).forEach((ln) => ln.onpointerdown = (e) => { if (e.target === ln) { E.sel = null; E.clipSel = null; renderBlocks(); renderInspector(); const r = ln.getBoundingClientRect(); seekTo((e.clientX - r.left) / E.pps); } });
    new ResizeObserver(() => { if (!E) return; fitStage(); const fit = zoomFrac() < 0.005; fitZoomMin(); if (fit) setZoom(0); else drawCanvas(); }).observe(view);
    fitStage(); fitZoomMin(); setZoom(0); renderAll();
    cancelAnimationFrame(raf); raf = requestAnimationFrame(loop);
    if (!E._keys) { E._keys = true; addEventListener("keydown", onKey); }
  }

  async function openRender() {
    try { await LF.loadAsset("js", "/long/app/render.js"); } catch (err) { toast("The render window didn't load."); return; }
    LFR.open({ root: E.root, name: E.meta.name, t: E.t, total: E.total, dirty: () => E.dirty, save });
  }
  function leaveEditor() {
    if (E && E.dirty && !confirm("You have unsaved changes. Leave without saving?")) return;
    S.dirty = false; stopAll(); LF.leaveToLibrary();
  }
  async function save() {
    if (!E) return;
    sortAll();
    const cut = E.segsDirty;
    const r = await post("/api/long/save", { root: E.root, spec: E.spec, segments: cut ? E.segs : undefined });
    if (r.ok) { E.dirty = false; S.dirty = false; E.segsDirty = false; setStatus(); toast("Saved"); if (cut) refreshWords(); } else toast(r.error || "Couldn't save");
    return r.ok;
  }

  // ---------------------------------------------------------------- zoom and layout
  function fitStage() {
    if (!E) return;
    const b = E.stageBox.getBoundingClientRect(); if (!b.width) return;
    const w = Math.min(b.width, b.height * 16 / 9);
    E.stage.style.width = `${Math.floor(w)}px`; E.stage.style.height = `${Math.floor(w * 9 / 16)}px`;
  }
  const viewW = () => Math.max(300, E.scroll.clientWidth || 800);
  function fitZoomMin() { E.ppsMin = viewW() / E.total; E.ppsMax = 60; if (E.pps < E.ppsMin) E.pps = E.ppsMin; }
  const zoomFrac = () => (Math.log(E.pps / E.ppsMin) / Math.log(E.ppsMax / E.ppsMin)) || 0;
  function setZoom(f, anchorT, anchorX) {
    f = clamp(f, 0, 1); fitZoomMin();
    E.pps = E.ppsMin * Math.pow(E.ppsMax / E.ppsMin, f); E.zoom.value = String(Math.round(f * 100));
    E.inner.style.width = `${Math.ceil(E.total * E.pps)}px`;
    if (anchorT != null) E.scroll.scrollLeft = anchorT * E.pps - anchorX;
    else if (f === 0) E.scroll.scrollLeft = 0;
    renderBlocks(); drawCanvas(); placePlayhead();
  }

  // ---------------------------------------------------------------- timeline drawing
  const RULER = 26, AUDIO = 40;
  function drawCanvas() {
    if (!E) return;
    const cv = E.canvas, dpr = window.devicePixelRatio || 1, w = viewW(), h = RULER + AUDIO;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); cv.style.width = `${w}px`; cv.style.height = `${h}px`; }
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    const css = getComputedStyle(document.documentElement), col = (n, d) => css.getPropertyValue(n).trim() || d;
    const L = E.scroll.scrollLeft, t0 = L / E.pps, t1 = (L + w) / E.pps;
    // ruler
    g.fillStyle = col("--panel-2", "#f3f1f6"); g.fillRect(0, 0, w, RULER);
    const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]; const step = steps.find((s) => s * E.pps >= 80) || 3600;
    g.fillStyle = col("--muted", "#777"); g.strokeStyle = col("--line-2", "#ccc"); g.font = "11px Inter, sans-serif"; g.textBaseline = "middle";
    for (let t = Math.floor(t0 / step) * step; t <= t1 + step; t += step) {
      const x = Math.round(t * E.pps - L) + 0.5; g.beginPath(); g.moveTo(x, RULER - 7); g.lineTo(x, RULER); g.stroke(); g.fillText(mmss(t), x + 4, 12);
    }
    // waveform (edited time -> raw peaks)
    g.fillStyle = col("--wave", "#9d86f6");
    const mid = RULER + AUDIO / 2;
    if (E.peaks) {
      const P = E.peaks.peaks, ps = E.peaks.perSec;
      for (let x = 0; x < w; x++) {
        const ta = (L + x) / E.pps, tb = (L + x + 1) / E.pps; if (ta > E.total) break;
        const ra = toRaw(ta), rb = Math.max(ra, toRaw(Math.min(tb, E.total)));
        let m = 0; for (let i = Math.floor(ra * ps), n = Math.min(P.length - 1, Math.floor(rb * ps)); i <= n; i++) if (P[i] > m) m = P[i];
        const a = (Math.min(255, m * 1.4) / 255) * (AUDIO / 2 - 2); g.fillRect(x, mid - a, 1, Math.max(1, a * 2));
      }
    } else { g.fillStyle = col("--line", "#ddd"); g.fillRect(0, mid, w, 1); }
    // playhead is a DOM line; cut points are invisible in edited time
  }
  function placePlayhead() { if (E) E.ph.style.transform = `translateX(${E.t * E.pps}px)`; }

  function renderBlocks() {
    if (!E) return;
    E.inner.style.width = `${Math.ceil(E.total * E.pps)}px`;
    for (const k of LANE_KEYS) {
      const ln = E.lanes[k]; ln.innerHTML = "";
      list(k).forEach((o, i) => {
        const start = k === "ch" ? o.start : o.t, len = k === "ch" ? o.end - o.start : o.dur;
        const label = k === "ov" ? `${o.muted === false ? "🔊 " : ""}${o.name || "Video"}${o.mode === "pip" ? " (window)" : ""}` : k === "rd" ? RD_NAMES[o.type] || "Blur" : k === "ch" ? o.title : k === "lt" ? o.title : (o.title || (o.value ? `${o.value} ${o.label || ""}` : ""));
        const b = el("div", { class: `lfe-b ${k}${E.sel && E.sel.o === o ? " sel" : ""}${k === "ch" ? ` c${i % 4}` : ""}`, style: `left:${start * E.pps}px;width:${Math.max(4, len * E.pps)}px`, title: `${mmss(start)} ${label}` },
          el("span", {}, label));
        if (k !== "ch" || i > 0) b.append(el("i", { class: "h l" }));
        if (k !== "ch") b.append(el("i", { class: "h r" }));
        if (k === "rd" && o.keys.length > 1) o.keys.forEach((kk) => b.append(el("i", { class: "kf", style: `left:${kk.dt * E.pps}px` })));
        b._o = o; b.onpointerdown = (e) => beginDrag(e, k, o, b);
        ln.append(b);
      });
      const hb = E.heads.querySelector(`.lfe-head.${k} b`); if (hb) hb.textContent = String(list(k).length);
    }
    renderClips();
  }

  function layoutChapters() {
    E.lanes.ch.querySelectorAll(".lfe-b").forEach((b) => { const o = b._o; b.style.left = `${o.start * E.pps}px`; b.style.width = `${Math.max(4, (o.end - o.start) * E.pps)}px`; });
  }

  function beginDrag(e, k, o, b) {
    if (e.button !== 0) return;
    e.stopPropagation();
    const mode = e.target.classList.contains("l") ? "l" : e.target.classList.contains("r") ? "r" : "move";
    if (k === "ch" && mode === "move") { select(k, o); seekTo(o.start); return; }
    select(k, o);
    const x0 = e.clientX, orig = { start: k === "ch" ? o.start : o.t, dur: o.dur, in: o.in }; let moved = false;
    try { b.setPointerCapture(e.pointerId); } catch (err) { /* carry on */ }
    const move = (ev) => {
      const dx = (ev.clientX - x0) / E.pps; if (!moved && Math.abs(ev.clientX - x0) < 3) return;
      if (!moved) { snapshot(); moved = true; }
      if (k === "ch") {
        const c = E.spec.chapters, i = c.indexOf(o), lo = c[i - 1].start + MIN_CH, hi = (c[i + 1] ? c[i + 1].start : E.total) - MIN_CH;
        o.start = r2(clamp(snapT(orig.start + dx, ev), lo, hi)); fixChapters(); layoutChapters(); }
      else if (mode === "move") { o.t = r2(clamp(snapT(orig.start + dx, ev), 0, E.total - o.dur)); }
      else if (mode === "l") {
        const end = orig.start + orig.dur, lo = k === "ov" ? Math.max(0, orig.start - (orig.in || 0)) : 0;
        const t = clamp(snapT(orig.start + dx, ev), lo, end - (k === "ov" ? 0.3 : 1.5)); o.t = r2(t); o.dur = r2(end - t);
        if (k === "ov") o.in = r2(Math.max(0, (orig.in || 0) + (t - orig.start)));
      }
      else { o.dur = r2(clamp(snapT(orig.start + orig.dur + dx, ev) - orig.start, k === "ov" ? 0.3 : 1.5, Math.min(E.total - orig.start, k === "ov" ? (o.clip || Infinity) - (o.in || 0) : Infinity))); }
      if (k !== "ch") { b.style.left = `${o.t * E.pps}px`; b.style.width = `${Math.max(4, o.dur * E.pps)}px`; }
      touch(); syncInspectorTimes(); paint();
    };
    const up = () => { b.removeEventListener("pointermove", move); b.removeEventListener("pointerup", up); if (moved) { sortAll(); renderBlocks(); renderInspector(); seekTo(k === "ch" ? o.start + 1 : o.t + 0.6); } };
    b.addEventListener("pointermove", move); b.addEventListener("pointerup", up);
  }

  function select(k, o, keepTime) {
    E.sel = { k, o }; if (E.clipSel != null) { E.clipSel = null; renderClips(); } E.inner.querySelectorAll(".lfe-b").forEach((b) => b.classList.toggle("sel", b._o === o)); renderInspector(); drawRd();
    if (!keepTime) { const t = k === "ch" ? o.start : o.t; seekTo(Math.min(E.total - 0.1, t + (k === "ch" ? 1 : 0.6))); }
  }
  // a client brand: its colours and fonts for the overlays (served by the Studio server); the default brand needs nothing
  function applyBrand() {
    const id = E.spec && E.spec.brand && E.spec.brand !== "default" ? E.spec.brand : "";
    let l = document.getElementById("lf-brand");
    if (!id) { if (l) l.remove(); return; }
    const href = `/brands/${encodeURIComponent(id)}/long.css`;
    if (!l) { l = document.createElement("link"); l.id = "lf-brand"; l.rel = "stylesheet"; document.head.append(l); }
    if (l.getAttribute("href") !== href) l.setAttribute("href", href);
  }
  // the brand of this video (Studio AI brand kits, shared with the short-form header): a select in the top bar
  function brandSwitch() {
    const kits = window.BRAND_KITS || [];
    if (!kits.length) return null;
    const cur = E.spec.brand || "default";
    const s = el("select", { class: "lfe-brand", title: "Who this video is for" }, ...kits.map((k) => el("option", { value: k.id, selected: k.id === cur }, k.name)));
    s.onchange = () => {
      const old = E.spec.brand || "default", id = s.value;
      snapshot();
      if (id === "default") delete E.spec.brand; else E.spec.brand = id;
      // the end screen follows the brand when it still shows the old brand's standard lines; otherwise ask
      const std = (b) => (window.brandEndLines && brandEndLines(b)) || (typeof STANDARD_END !== "undefined" ? STANDARD_END : null);
      const key = (ls) => JSON.stringify((ls || []).map((l) => [l.text, !!l.bold]));
      const end = E.spec.endcard;
      if (end && end.lines && std(id) && key(end.lines) !== key(std(id)) && (key(end.lines) === key(std(old)) || confirm(`Use ${brandName(id)}'s end screen lines too?`))) end.lines = JSON.parse(JSON.stringify(std(id)));
      touch(); renderAll(); toast(`This video now uses the ${window.brandName ? brandName(id) : id} brand`);
    };
    return s;
  }
  function renderAll() { applyBrand(); fixChapters(); renderBlocks(); renderInspector(); drawCanvas(); paint(); E.undoB.disabled = !E.undo.length; E.redoB.disabled = !E.redo.length; setStatus(); }

  // ---------------------------------------------------------------- cuts (split, trim, remove parts of the video)
  // The cut list (E.segs, camera-file times) changes straight away: everything after a cut moves with its words,
  // and Save writes work/edl.json too. Nothing is re-rendered; the preview already plays the camera file through the cuts.
  const MIN_CLIP = 0.1;
  const rnd = (x) => Math.round(x * 1000) / 1000;
  function setSegs(segs) {
    E.segs = segs; E.offs = []; let o = 0;
    segs.forEach((s) => { E.offs.push(o); o += s.out - s.in; });
    E.total = rnd(o); E.spec.duration = E.total;
    fitZoomMin(); E.inner.style.width = `${Math.ceil(E.total * E.pps)}px`;
  }
  // old edited time -> new edited time, through camera time. A removed moment lands where playback carries on.
  function remapper(oldSegs, newSegs) {
    const oOffs = []; let o = 0; oldSegs.forEach((s) => { oOffs.push(o); o += s.out - s.in; });
    const nOffs = []; let n = 0; newSegs.forEach((s) => { nOffs.push(n); n += s.out - s.in; });
    const oldTotal = o, newTotal = n;
    const toRawOld = (t) => {
      let lo = 0, hi = oOffs.length - 1; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (oOffs[m] <= t) lo = m; else hi = m - 1; }
      return oldSegs[lo].in + Math.min(Math.max(0, t - oOffs[lo]), oldSegs[lo].out - oldSegs[lo].in);
    };
    const find = (r) => newSegs.findIndex((s) => s.in - 1e-6 <= r && r < s.out - 1e-6);
    const nextIn = (r) => { let b = -1; newSegs.forEach((s, i) => { if (SPACE(s.in) === SPACE(r) && s.in >= r - 1e-6 && (b < 0 || s.in < newSegs[b].in)) b = i; }); return b; };
    return (t) => {
      if (t >= oldTotal - 1e-6) return { t: newTotal, kept: true };
      let r = toRawOld(t), k = find(r);
      if (k >= 0) return { t: rnd(nOffs[k] + r - newSegs[k].in), kept: true };
      if (SPACE(r) > 0) {                         // inside an insert that was taken out: land where it was
        const ok = oOffs.findIndex((o, i) => t >= o - 1e-6 && t < o + oldSegs[i].out - oldSegs[i].in);
        const after = oldSegs.slice(ok + 1).find((x) => !isIns(x));
        if (!after) return { t: newTotal, kept: false };
        r = after.in; k = find(r);
        if (k >= 0) return { t: rnd(nOffs[k] + r - newSegs[k].in), kept: false };
      }
      const n = nextIn(r);                        // a removed moment lands where playback carries on
      return n >= 0 ? { t: nOffs[n], kept: false } : { t: newTotal, kept: false };
    };
  }
  function applyCut(newSegs, msg) {
    newSegs = newSegs.filter((s) => s.out - s.in >= MIN_CLIP);
    if (!newSegs.some(isIns)) newSegs.sort((a, b) => a.in - b.in);   // with inserts the order is the editor's
    if (!newSegs.length) { toast("That would remove the whole video."); return; }
    snapshot();
    const f = remapper(E.segs, newSegs); let gone = 0;
    for (const key of ["lowerThirds", "cards", "redactions", "overlays"]) {
      E.spec[key] = E.spec[key].filter((o) => {
        const a = f(o.t), b = f(o.t + o.dur);
        if ((!a.kept && !b.kept && a.t === b.t) || b.t - a.t < 0.5) { gone++; return false; }
        if (key === "overlays" && !a.kept) o.in = rnd((o.in || 0) + Math.max(0, o.dur - (b.t - a.t)));   // its start was cut: skip that much of the clip
        o.t = a.t; o.dur = rnd(b.t - a.t); return true;
      });
    }
    const ch = E.spec.chapters.map((c) => ({ c, s: f(c.start).t })).sort((x, y) => x.s - y.s);
    E.spec.chapters = ch.filter((x, i) => !(ch[i + 1] && ch[i + 1].s - x.s < 1)).map((x) => { x.c.start = x.s; return x.c; });   // a chapter whose whole span was cut goes
    setSegs(newSegs); E.segsDirty = true; E.clipSel = null; E.mark = null; wordsForCut(f);
    sortAll(); touch(); renderAll(); seekTo(E.t);
    toast(`${msg || "Cut"}: the video is now ${mmss(E.total)}${gone ? `. ${gone} item${gone > 1 ? "s" : ""} inside the removed part ${gone > 1 ? "were" : "was"} deleted` : ""}. Undo with ⌘Z.`);
  }
  function clipIndexAt(t) { let i = E.offs.length - 1; while (i > 0 && E.offs[i] > t) i--; return i; }
  function splitAt(t) {
    const k = clipIndexAt(t), s = E.segs[k], r = toRaw(t);
    if (r - s.in < MIN_CLIP || s.out - r < MIN_CLIP) { toast("Too close to an existing cut."); return; }
    const segs = E.segs.map((x) => ({ ...x })); segs.splice(k, 1, { ...s, out: rnd(r) }, { ...s, in: rnd(r) });
    snapshot(); setSegs(segs); E.segsDirty = true; touch(); E.clipSel = k + 1; E.sel = null; renderAll();
    toast("Split. Select a clip and press Delete to remove it, or drag its ends to trim.");
  }
  function deleteClip(k) {
    if (E.segs.length <= 1) { toast("That's the only clip left."); return; }
    const segs = E.segs.map((x) => ({ ...x })); segs.splice(k, 1); applyCut(segs, "Clip deleted");
  }
  function removeRange(a, b) {
    // clip by clip on the edited timeline (an insert's time is in its own file, so camera time can't be compared across)
    const segs = E.segs.flatMap((s, k) => {
      const o = E.offs[k], lo = Math.max(a, o), hi = Math.min(b, o + s.out - s.in);
      if (hi - lo <= 1e-3) return [{ ...s }];
      const ra = s.in + (lo - o), rb = s.in + (hi - o), parts = [];
      if (ra - s.in >= MIN_CLIP) parts.push({ ...s, out: rnd(ra) });
      if (s.out - rb >= MIN_CLIP) parts.push({ ...s, in: rnd(rb) });
      return parts;
    });
    applyCut(segs, `Removed ${mmss(b - a)}`);
  }
  const rawEnd = () => { const v = $("#lfVideo"); return v && isFinite(v.duration) ? v.duration : E.segs[E.segs.length - 1].out; };
  function trimmed(k, edge, v) {
    const segs = E.segs.map((x) => ({ ...x })), s = segs[k], sp = SPACE(s.in);
    // the neighbours that limit a trim are the nearest clips from the same file (camera, or this insert's own file)
    let p = k - 1; while (p >= 0 && SPACE(segs[p].in) !== sp) p--;
    let n = k + 1; while (n < segs.length && SPACE(segs[n].in) !== sp) n++;
    const lo = p >= 0 && segs[p].out <= s.in + 1e-6 ? segs[p].out : isIns(s) ? s.vbase : 0;
    const hi = n < segs.length && segs[n].in >= s.out - 1e-6 ? segs[n].in : isIns(s) ? s.vbase + s.clip : rawEnd();
    if (edge === "in") s.in = rnd(clamp(v, lo, s.out - MIN_CLIP));
    else s.out = rnd(clamp(v, s.in + MIN_CLIP, hi));
    return segs;
  }
  function nudge(k, edge, d) { applyCut(trimmed(k, edge, E.segs[k][edge] + d), "Trimmed"); E.clipSel = k; renderInspector(); renderClips(); }
  function setMark(which, t) { E.mark = { ...(E.mark || {}), [which]: r2(t) }; renderClips(); if (markRange()) toast("Press Delete (or Remove marked part) to cut it out."); }
  function markRange() { const m = E.mark; if (m?.a == null || m?.b == null) return null; const a = Math.min(m.a, m.b), b = Math.max(m.a, m.b); return b - a >= 0.1 ? [a, b] : null; }
  function selectClip(k) { E.sel = null; E.clipSel = k; E.inner.querySelectorAll(".lfe-b.sel").forEach((b) => b.classList.remove("sel")); renderClips(); renderInspector(); drawRd(); }
  function renderClips() {
    if (!E || !E.clLane) return;
    const ln = E.clLane; ln.innerHTML = ""; E.inner.querySelectorAll(".lfe-mark").forEach((m) => m.remove());
    E.segs.forEach((s, k) => {
      const b = el("div", { class: `lfe-b cl${isIns(s) ? " ins" : ""}${E.clipSel === k ? " sel" : ""}`, style: `left:${E.offs[k] * E.pps}px;width:${Math.max(3, (s.out - s.in) * E.pps - 1)}px`,
        title: isIns(s) ? `Inserted clip · ${s.name || s.src.split(/[\\/]/).pop()} · ${mmss(E.offs[k])} · ${(s.out - s.in).toFixed(1)} s` : `Clip ${k + 1} · ${mmss(E.offs[k])} · ${(s.out - s.in).toFixed(1)} s` },
        el("i", { class: "h l" }), el("i", { class: "h r" }), isIns(s) && (s.out - s.in) * E.pps > 60 ? el("span", { class: "insl" }, "Insert") : null);
      b.onpointerdown = (e) => {
        if (e.button !== 0) return; e.stopPropagation();
        const edge = e.target.classList.contains("l") ? "in" : e.target.classList.contains("r") ? "out" : null;
        selectClip(k);
        if (!edge) { if (E.t < E.offs[k] || E.t > E.offs[k] + s.out - s.in) seekTo(E.offs[k] + 0.05); return; }
        // drag an edge: shown live on this block, applied (with everything moving) on release
        const x0 = e.clientX, v0 = s[edge], blk = ln.children[k]; let v = v0;
        try { blk.setPointerCapture(e.pointerId); } catch (err) { /* carry on */ }
        const move = (ev) => {
          v = v0 + (ev.clientX - x0) / E.pps;
          if (E.snap && !ev.altKey) {
            const tAt = E.offs[k] + (edge === "in" ? 0 : s.out - s.in) + (v - v0), w = nearestWord(tAt, 10 / E.pps);
            if (w != null) v = v0 + (w - (E.offs[k] + (edge === "in" ? 0 : s.out - s.in)));
          }
          const t = trimmed(k, edge, v)[k];
          const left = E.offs[k] + (t.in - s.in);
          blk.style.left = `${(edge === "in" ? left : E.offs[k]) * E.pps}px`;
          blk.style.width = `${Math.max(3, (t.out - t.in) * E.pps - 1)}px`;
        };
        const up = () => {
          blk.removeEventListener("pointermove", move); blk.removeEventListener("pointerup", up);
          if (Math.abs(v - v0) > 0.01) { applyCut(trimmed(k, edge, v), "Trimmed"); selectClip(k); } else renderClips();
        };
        blk.addEventListener("pointermove", move); blk.addEventListener("pointerup", up);
      };
      ln.append(b);
    });
    const m = E.mark;
    if (m && (m.a != null || m.b != null)) {
      const a = m.a ?? m.b, b = m.b ?? m.a;
      E.inner.append(el("div", { class: "lfe-mark", style: `left:${Math.min(a, b) * E.pps}px;width:${Math.max(2, Math.abs(b - a) * E.pps)}px` }));
    }
    const hb = E.heads.querySelector(".lfe-head.cl b"); if (hb) hb.textContent = String(E.segs.length);
    const bar = E.cutbar; if (!bar) return;
    bar.innerHTML = "";
    const rng = markRange();
    if (rng) bar.append(el("button", { class: "small", onclick: () => removeRange(...rng), title: "Remove the part between the marks (Delete)" }, ic("scissors"), `Remove ${mmss(rng[1] - rng[0])}`),
      el("button", { class: "small ghost", onclick: () => { E.mark = null; renderClips(); }, title: "Clear the marks (Esc)" }, ic("x")));
  }
  function clipInspector(box) {
    const k = E.clipSel, s = E.segs[k]; if (!s) { E.clipSel = null; return false; }
    const f = 1 / (E.spec.fps || 25);
    const row = (label, edge) => field(label, el("div", { class: "lfe-nudge" }, ...[[-1, "−1s"], [-0.1, "−0.1s"], [-f, "−1f"], [f, "+1f"], [0.1, "+0.1s"], [1, "+1s"]].map(([d, n]) =>
      el("button", { class: "small", onclick: () => nudge(k, edge, d) }, n))));
    box.append(el("h3", {}, `Clip ${k + 1} of ${E.segs.length}`),
      el("div", { class: "lfe-sum" }, `${mmss(E.offs[k])} – ${mmss(E.offs[k] + s.out - s.in)} on the timeline · ${(s.out - s.in).toFixed(2)} s`),
      row("Trim the start", "in"), row("Trim the end", "out"),
      el("p", { class: "hint" }, "Or drag the clip's ends on the Video track. Moving an end outwards brings back material the automatic edit cut out. Everything after it moves with the words."),
      el("div", { class: "lfe-btns" },
        el("button", { onclick: () => splitAt(E.t) }, ic("scissors"), "Split at playhead"),
        el("button", { onclick: () => deleteClip(k) }, ic("trash-2"), "Delete clip")),
      el("p", { class: "hint" }, isIns(s) ? `Inserted clip ${s.name ? `“${s.name}” ` : ""}(${(s.in - s.vbase).toFixed(2)} – ${(s.out - s.vbase).toFixed(2)} s of its ${(+s.clip || 0).toFixed(2)} s). The video pauses while it plays; Delete clip takes it out again.`
        : `Camera file: ${s.in.toFixed(2)} – ${s.out.toFixed(2)} s. To cut out a part: press I at its start, O at its end, then Delete.`));
    return true;
  }

  // ---------------------------------------------------------------- overlay videos (inserts, B-roll, testimonials), 1920x1080 frame px
  // overlays[]: {src (absolute path, linked not copied), name, t, dur, in, clip, track, mode full|pip, x, y, w, h, opacity, fade, muted, volume, duck}
  const ovDef = () => ({ x: 1920 - 704 - 80, y: 80, w: 704, h: 396 });
  // an AI studio clip laid over the video at the playhead: its sound plays and the speaker drops out (duck 0)
  async function addAiOverlay(c) {
    if (!E) return;
    const r = await post(window.studioApi("overlay"), { id: c.id });
    if (!r || !r.ok) return toast((r && r.error) || "Couldn't add it");
    const t = r2(clamp(E.t, 0, E.total - 1)), dur = r2(Math.min(r.dur || 5, E.total - t));
    snapshot();
    const o = { src: r.src, name: r.name, t, dur, in: 0, clip: r.dur || dur, track: 1 + Math.max(0, ...E.spec.overlays.filter((x) => x.t < t + dur && x.t + x.dur > t).map((x) => x.track || 1)),
      mode: "full", opacity: 1, fade: 0.2, muted: false, volume: 1, duck: 0, has_audio: r.audio };
    E.spec.overlays.push(o); sortAll(); touch(); select("ov", o, true); renderAll();
    toast(dur < (r.dur || 0) - 0.05 ? "Added at the playhead; trimmed to the end of the video." : "Added at the playhead: the speaker is muted while it plays.");
  }
  // an AI studio clip put INTO the video at the playhead: the camera clip there is split and everything after moves later.
  // Undoable like any cut; Save writes it to edl.json. Anything on screen across the playhead is offered a clean spot.
  function gapNear(t, dir) {
    const W = E.words, gaps = [0];
    for (let i = 0; i + 1 < W.length; i++) if (W[i + 1].start > W[i].end - 1e-3) gaps.push((W[i].end + W[i + 1].start) / 2);
    gaps.push(E.total);
    const ok = gaps.filter((g) => (dir < 0 ? g <= t + 1e-3 : dir > 0 ? g >= t - 1e-3 : true));
    return ok.length ? ok.reduce((b, g) => (Math.abs(g - t) < Math.abs(b - t) ? g : b)) : t;
  }
  function insertSpot(T) {
    const all = [...E.spec.lowerThirds.map((o) => ({ a: o.t, b: o.t + o.dur, what: `the lower-third “${o.title || ""}”` })),
      ...E.spec.cards.map((o) => ({ a: o.t, b: o.t + o.dur, what: `the card “${o.title || o.value || ""}”` })),
      ...E.spec.overlays.map((o) => ({ a: o.t, b: o.t + o.dur, what: `the overlay “${o.name || "video"}”` })),
      ...E.spec.redactions.map((o) => ({ a: o.t, b: o.t + o.dur, what: "a blur" }))];
    const across = all.filter((x) => x.a < T - 0.05 && x.b > T + 0.05);
    if (!across.length) return Promise.resolve(r2(gapNear(T, 0)));
    let A = Math.min(...across.map((x) => x.a)), B = Math.max(...across.map((x) => x.b));
    for (let grew = true; grew;) { grew = false; for (const x of all) if (x.a < B - 0.05 && x.b > A + 0.05 && (x.a < A - 1e-3 || x.b > B + 1e-3)) { A = Math.min(A, x.a); B = Math.max(B, x.b); grew = true; } }
    const opts = [[`after`, r2(gapNear(B + 0.05, 1))], [`before`, r2(gapNear(A, -1))]].filter(([, t]) => t >= 0 && t < E.total - 0.1).sort((x, y) => Math.abs(x[1] - T) - Math.abs(y[1] - T));
    return new Promise((res) => {
      const done = (v) => { closeModal(); res(v); };
      openModal(el("div", { class: "box" }, el("h3", {}, "Something is on screen here"),
        el("p", { class: "hint", style: "font-size:13px;line-height:1.5" }, `At ${mmss(T)}, ${across.map((x) => x.what).slice(0, 2).join(" and ")}${across.length > 2 ? " and more" : ""} would stay on screen over the whole clip. Put the clip just ${opts.map((o) => o[0]).join(" or ")} instead?`),
        el("div", { class: "btns", style: "justify-content:flex-end;margin-top:14px;flex-wrap:wrap" },
          el("button", { onclick: () => done(null) }, "Cancel"), el("button", { onclick: () => done(T) }, "Insert here anyway"),
          ...opts.map(([w, t], i) => el("button", { class: i === 0 ? "primary" : "", onclick: () => done(t) }, `Insert at ${mmss(t)} (${w})`)))));
    });
  }
  async function insertClip(c) {
    if (!E) return;
    const T = await insertSpot(E.t); if (T == null) return;
    const r = await post("/api/long/insert-clip", { root: E.root, clip: c.id }).catch(() => null);
    if (!r || !r.ok) return toast((r && r.error) || "Couldn't insert it");
    const segs = E.segs.map((x) => ({ ...x })), k = clipIndexAt(T), s = segs[k], raw = toRaw(T);
    const seg = { src: r.src, name: r.name, in: r.vbase, out: rnd(r.vbase + r.clip), vbase: r.vbase, clip: r.clip };
    if (isIns(s)) segs.splice(k + 1, 0, seg);                       // inside another insert: after it
    else if (raw - s.in < MIN_CLIP) segs.splice(k, 0, seg);          // at a clip's start: before it
    else if (s.out - raw < MIN_CLIP) segs.splice(k + 1, 0, seg);     // at its end: after it
    else segs.splice(k, 1, { ...s, out: rnd(raw) }, seg, { ...s, in: rnd(raw) });
    applyCut(segs, `“${r.name}” inserted at ${mmss(T)}`);
    window.toggleStudio?.(false); seekTo(T + 0.02);
  }
  async function addOverlayVideo() {
    let body = {};
    if (window.PORTAL) {                     // uploaded into the project's media/ folder
      const upload = await pickAndUpload("video/*", "the video");
      if (!upload) return;
      body = { upload, root: E.root };
    } else toast("Choose a video in the Finder window…");
    const r = await post("/api/long/choose-overlay", body).catch(() => null);
    if (r && r.error) toast(r.error);
    if (!r || !r.path) return;
    const t = r2(clamp(E.t, 0, E.total - 1)), dur = r2(Math.min(r.duration || 5, E.total - t, 8));
    snapshot();
    const o = { src: r.path, name: r.name, t, dur, in: 0, clip: r.duration || dur, track: 1 + Math.max(0, ...E.spec.overlays.filter((x) => x.t < t + dur && x.t + x.dur > t).map((x) => x.track || 1)),
      mode: "full", opacity: 1, fade: 0.3, muted: true, volume: 1, duck: 1, has_audio: r.audio };
    E.spec.overlays.push(o); sortAll(); touch(); select("ov", o, true); renderAll();
    toast(r.audio ? "Overlay added, muted. Unmute it in the panel to hear its sound." : "Overlay added.");
  }
  // one <video> per overlay in the preview, kept in step with the edited time
  function syncOverlays(playing) {
    if (!E.vLayer) return;
    const t = E.t, want = new Set();
    let duck = 1;
    E.spec.overlays.forEach((o) => {
      const on = t >= o.t && t < o.t + o.dur;
      if (on && (o.duck ?? 1) < duck) duck = o.duck ?? 1;
      let v = E.ovEls.get(o);
      if (!on) { if (v) v.hidden = true, v.pause(); return; }
      want.add(o);
      if (!v) {
        v = el("video", { class: "lfe-ovv", preload: "auto", playsInline: true, muted: true, src: `/api/long/overlay-file?root=${encodeURIComponent(E.root)}&src=${encodeURIComponent(o.src)}` });
        v.addEventListener("pointerdown", (e) => ovVidDrag(e, o, v));
        E.ovEls.set(o, v); E.vLayer.append(v);
      }
      const b = o.mode === "pip" ? { x: o.x ?? ovDef().x, y: o.y ?? ovDef().y, w: o.w ?? ovDef().w, h: o.h ?? ovDef().h } : { x: 0, y: 0, w: 1920, h: 1080 };
      Object.assign(v.style, { left: `${b.x / 19.2}%`, top: `${b.y / 10.8}%`, width: `${b.w / 19.2}%`, height: `${b.h / 10.8}%`, zIndex: String(o.track || 1),
        opacity: String((o.opacity ?? 1) * Math.min(1, o.fade ? Math.min(t - o.t, o.t + o.dur - t) / o.fade : 1)) });
      v.classList.toggle("pip", o.mode === "pip"); v.classList.toggle("sel", !!(E.sel && E.sel.o === o));
      v.hidden = false; v.muted = o.muted !== false; v.volume = clamp(o.volume ?? 1, 0, 1);
      const target = t - o.t + (o.in || 0);
      if (playing) { if (v.paused) { v.currentTime = target; v.play().catch(() => {}); } else if (Math.abs(v.currentTime - target) > 0.3) v.currentTime = target; }
      else { if (!v.paused) v.pause(); if (Math.abs(v.currentTime - target) > 0.04) v.currentTime = target; }
    });
    for (const [o, v] of E.ovEls) if (!E.spec.overlays.includes(o)) { v.remove(); E.ovEls.delete(o); }
    const main = $("#lfVideo"); if (main) main.volume = clamp(duck, 0, 1);
  }
  function ovVidDrag(e, o, v) {
    if (e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    if (!E.sel || E.sel.o !== o) select("ov", o, true);
    if (o.mode !== "pip") return;
    const sc = E.stage.getBoundingClientRect().width / 1920, d = ovDef();
    const b0 = { x: o.x ?? d.x, y: o.y ?? d.y, w: o.w ?? d.w, h: o.h ?? d.h }, x0 = e.clientX, y0 = e.clientY;
    const r = v.getBoundingClientRect(), corner = e.clientX > r.right - 18 && e.clientY > r.bottom - 18;   // bottom-right corner resizes
    let moved = false;
    try { v.setPointerCapture(e.pointerId); } catch (err) { /* carry on */ }
    const move = (ev) => {
      const dx = (ev.clientX - x0) / sc, dy = (ev.clientY - y0) / sc;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 3 / sc) return;
      if (!moved) { snapshot(); moved = true; }
      if (corner) { const w = clamp(Math.round(b0.w + dx), 160, 1920); Object.assign(o, { w, h: Math.round(w * b0.h / b0.w) }); }
      else { o.x = clamp(Math.round(b0.x + (ev.shiftKey && Math.abs(dy) > Math.abs(dx) ? 0 : dx)), -b0.w / 2, 1920 - b0.w / 2); o.y = clamp(Math.round(b0.y + (ev.shiftKey && Math.abs(dx) >= Math.abs(dy) ? 0 : dy)), -b0.h / 2, 1080 - b0.h / 2); }
      touch(); syncOverlays(false);
    };
    const up = () => { v.removeEventListener("pointermove", move); v.removeEventListener("pointerup", up); if (moved) renderInspector(); };
    v.addEventListener("pointermove", move); v.addEventListener("pointerup", up);
  }
  function inspectorOv(box, o, tT) {
    const on = o.muted === false;
    const set = (fn) => { snapshot(); fn(); touch(); renderBlocks(); renderInspector(); syncOverlays(false); };
    const slider = (label, key, def, min, max, step, fmt, hint) => {
      const out = el("b", {}, fmt(o[key] ?? def)), r = el("input", { type: "range", min, max, step, value: o[key] ?? def });
      r.oninput = () => { snapshot(key); o[key] = Number(r.value); out.textContent = fmt(o[key]); touch(); syncOverlays(false); };
      return field(label, el("div", { class: "lfe-slide" }, r, out), hint);
    };
    const dI = el("input", { type: "text", value: o.dur.toFixed(1) });
    dI.onchange = () => { const v = Number(dI.value); if (!(v >= 0.3)) { dI.value = o.dur.toFixed(1); return; } set(() => { o.dur = r2(Math.min(v, E.total - o.t, (o.clip || Infinity) - (o.in || 0))); }); };
    const inI = el("input", { type: "text", value: (o.in || 0).toFixed(1) });
    inI.onchange = () => { const v = Number(inI.value); if (!(v >= 0)) { inI.value = (o.in || 0).toFixed(1); return; } set(() => { o.in = r2(Math.min(v, (o.clip || Infinity) - 0.3)); }); };
    box.append(el("div", { class: "lfe-sum" }, `${o.name || "Overlay"} · track ${o.track || 1} · plays the clip from ${(o.in || 0).toFixed(1)} s`),
      field("Sound", el("button", { class: `ovsound${on ? " on" : ""}`, onclick: () => set(() => { o.muted = on; o.duck = on ? 1 : ((o.duck ?? 1) >= 0.999 ? 0.15 : o.duck); }) },
        ic(on ? "volume-2" : "volume-x"), on ? "Sound on (click to mute)" : "Muted (click to unmute)"), o.has_audio === false ? "This clip has no sound of its own." : null),
      on ? slider("Volume", "volume", 1, 0, 2, 0.05, (v) => `${Math.round(v * 100)}%`) : el("span"),
      slider("Speaker", "duck", 1, 0, 1, 0.05, (v) => `${Math.round(v * 100)}%`, "How loud the main video stays while this plays. Unmuting drops it to 15%."),
      field("Look", seg([["full", "Full screen"], ["pip", "Picture-in-picture"]], o.mode || "full", (v) => { o.mode = v; if (v === "pip" && o.x == null) Object.assign(o, ovDef()); })),
      o.mode === "pip" ? el("p", { class: "hint" }, "Drag the window on the preview to move it; drag its bottom-right corner to resize.") : el("span"),
      slider("Opacity", "opacity", 1, 0.1, 1, 0.05, (v) => `${Math.round(v * 100)}%`),
      slider("Fade", "fade", 0.3, 0, 1.5, 0.05, (v) => `${(+v).toFixed(2)} s`),
      el("div", { class: "lfe-two" }, field("Starts at", tT), field("Length (s)", dI)),
      el("div", { class: "lfe-two" }, field("Clip from (s)", inI), field("Track", el("div", { class: "lfe-btns" },
        el("button", { class: "small", onclick: () => (o.track || 1) > 1 && set(() => { o.track = (o.track || 1) - 1; }) }, "Down"),
        el("b", {}, String(o.track || 1)),
        el("button", { class: "small", onclick: () => set(() => { o.track = Math.min(6, (o.track || 1) + 1); }) }, "Up")))),
      el("p", { class: "hint" }, "A higher track sits on top. Blurs, lower-thirds, cards and captions sit above every overlay."));
  }

  // ---------------------------------------------------------------- adding and deleting
  function addLT() {
    snapshot(); const t = r2(clamp(E.t, 0, E.total - 4.5)), o = { t, dur: 4.5, title: "New title", sub: "" };
    E.spec.lowerThirds.push(o); sortAll(); touch(); select("lt", o, true); renderAll();
  }
  function addCard(type) {
    snapshot(); const t = r2(clamp(E.t, 0, E.total - 7)), base = { type, t, dur: 7 };
    const o = type === "stat" ? { ...base, value: "70%", label: "what it measures" } : type === "list" ? { ...base, title: "Three things", items: ["First", "Second", "Third"] } : { ...base, title: "New point", body: "" };
    E.spec.cards.push(o); sortAll(); touch(); select("cd", o, true); renderAll();
  }
  function addRedaction() {
    snapshot(); const t = r2(clamp(E.t, 0, E.total - 5)), o = { t, dur: 5, type: "blur", strength: 28, w: 480, h: 270, track: false, keys: [{ dt: 0, x: 720, y: 405 }] };
    E.spec.redactions.push(o); sortAll(); touch(); select("rd", o, true); renderAll();
  }
  function addChapter() {
    const t = r2(E.t), c = E.spec.chapters, cur = c.find((x) => t >= x.start && t < x.end);
    if (!cur || t - cur.start < MIN_CH || cur.end - t < MIN_CH) { toast("A chapter needs at least 10 seconds on each side. Move the playhead and try again."); return; }
    snapshot(); const o = { title: "New chapter", start: t, end: cur.end }; c.push(o); touch(); fixChapters(); select("ch", o, true); renderAll();
  }
  function deleteSel() {
    if (E.clipSel != null) { deleteClip(E.clipSel); return; }
    if (!E.sel) { const rng = markRange(); if (rng) removeRange(...rng); return; }
    const { k, o } = E.sel, a = list(k), i = a.indexOf(o);
    if (k === "ch" && i === 0) { toast("The first chapter can't be deleted (YouTube needs one at 0:00)."); return; }
    snapshot(); a.splice(i, 1); E.sel = null; touch(); renderAll();
  }

  // ---------------------------------------------------------------- inspector
  const SYNC = {};
  function field(label, input, hint) { return el("div", { class: "lfe-f" }, el("label", {}, label), input, hint ? el("small", {}, hint) : null); }
  function textIn(o, key, opts) {
    const i = el("input", { type: "text", value: o[key] || "", placeholder: opts?.ph || "" });
    i.oninput = () => { snapshot(`${key}:${idOf(o)}`); o[key] = i.value; touch(); renderBlocks(); paint(); }; return i;
  }
  function numIn(o, key, get, set, minV) {
    const i = el("input", { type: "text", value: clock(get()) });
    i.onchange = () => { const v = parseT(i.value); if (v == null) { i.value = clock(get()); return; } snapshot(); set(Math.max(minV || 0, v)); sortAll(); touch(); renderBlocks(); renderInspector(); paint(); };
    return i;
  }
  function seg(opts, cur, fn) { return el("div", { class: "lfe-seg" }, ...opts.map(([v, l]) => el("button", { class: cur === v ? "on" : "", onclick: () => { snapshot(); fn(v); touch(); renderInspector(); renderBlocks(); paint(); } }, l))); }

  function syncInspectorTimes() {
    if (!E.sel || !E.insT) return;
    const { k, o } = E.sel;
    if (E.insT.t) E.insT.t.value = clock(k === "ch" ? o.start : o.t);
    if (E.insT.d && o.dur != null) E.insT.d.value = o.dur.toFixed(1);
  }
  function warnings(k, o) {
    const w = [];
    if (k === "ch" || k === "rd") return w;
    const end = o.t + o.dur;
    if (end > E.total + 0.01) w.push("Runs past the end of the video.");
    const ch = E.spec.chapters.find((c) => o.t >= c.start && o.t < c.end);
    if (ch && end > ch.end + 0.01) w.push("Runs past the end of its chapter.");
    const same = list(k).filter((x) => x !== o && o.t < x.t + x.dur && x.t < end);
    if (same.length) w.push(k === "cd" ? "Overlaps another card." : "Overlaps another lower-third.");
    if (k === "cd" && E.spec.lowerThirds.some((x) => o.t < x.t + x.dur + 0.3 && x.t < end + 0.3)) w.push("Shares the screen with a lower-third.");
    return w;
  }
  function posFields(o) {
    E.insPos = null;
    if (typeof o.x !== "number") return el("div", { class: "lfe-f" }, el("small", {}, "Drag it on the preview to place it anywhere (Shift keeps it level). Choosing Left, Centre or Right puts it back."));
    const mk = (key) => { const i = el("input", { type: "text", value: String(o[key]) }); i.onchange = () => { const v = Math.round(Number(i.value)); if (isNaN(v)) { i.value = o[key]; return; } snapshot(); o[key] = clamp(v, 0, key === "x" ? 1840 : 1000); touch(); paint(); }; return i; };
    E.insPos = { x: mk("x"), y: mk("y") };
    return el("div", { class: "lfe-f" }, el("div", { class: "lfe-two" }, field("X", E.insPos.x), field("Y", E.insPos.y)),
      el("button", { class: "small", onclick: () => { snapshot(); delete o.x; delete o.y; touch(); renderInspector(); paint(); } }, "Back to the preset position"));
  }
  function renderInspector() {
    const box = E.ins; box.innerHTML = ""; E.insT = {}; E.insPos = null;
    if (E.clipSel != null && clipInspector(box)) return;
    if (!E.sel) {
      const c = E.spec.captions, spec = E.spec;
      const on = el("label", { class: "switch lf-cap" }, el("input", { type: "checkbox", checked: !!c.on }), el("span"), el("div", {}, el("b", {}, "Word captions"), el("small", {}, "Burned into the final video.")));
      on.querySelector("input").onchange = (e) => { snapshot(); c.on = e.target.checked; touch(); paint(); };
      const size = el("input", { type: "range", min: 30, max: 90, value: c.size }); size.oninput = () => { snapshot("capsize"); c.size = Number(size.value); touch(); paint(); };
      const bot = el("input", { type: "range", min: 40, max: 320, value: c.bottom }); bot.oninput = () => { snapshot("capbot"); c.bottom = Number(bot.value); touch(); paint(); };
      box.append(el("h3", {}, "Video"), el("div", { class: "lfe-sum" }, `${mmss(E.total)} · ${spec.chapters.length} chapters · ${spec.lowerThirds.length} lower-thirds · ${spec.cards.length} cards`),
        el("p", { class: "hint" }, "Click a chapter, lower-third or card on the timeline to edit it. Drag to move, drag the ends to resize."),
        el("h3", {}, "Captions"), on, field("Size", size), field("Height from the bottom", bot),
        el("h3", {}, "End screen"), el("div", { class: "hint" }, `${(spec.endcard?.lines || []).map((l) => l.text).join(" ")} (${spec.endcard?.duration || 0} s, added after the video)`));
      return;
    }
    const { k, o } = E.sel, tT = numIn(o, "t", () => (k === "ch" ? o.start : o.t), (v) => { if (k === "ch") o.start = v; else o.t = clamp(v, 0, E.total - o.dur); }, 0);
    E.insT.t = tT;
    const head = el("div", { class: "lfe-ih" }, el("h3", {}, k === "ch" ? "Chapter" : k === "lt" ? "Lower-third" : k === "rd" ? "Blur" : k === "ov" ? "Overlay video" : "Card"),
      el("button", { class: "small", onclick: () => seekTo(k === "ch" ? o.start : o.t) }, "Go to"), el("button", { class: "small", onclick: deleteSel }, ic("trash-2"), "Delete"));
    box.append(head);
    if (k === "ov") { inspectorOv(box, o, tT); return; }
    if (k === "ch") {
      box.append(field("Title", textIn(o, "title")), field("Starts at", tT, "Chapters run until the next one starts. Minimum 10 seconds."));
      return;
    }
    const dI = el("input", { type: "text", value: o.dur.toFixed(1) }); E.insT.d = dI;
    dI.onchange = () => { const v = Number(dI.value); if (!(v >= 1.5)) { dI.value = o.dur.toFixed(1); return; } snapshot(); o.dur = r2(Math.min(v, E.total - o.t)); touch(); renderBlocks(); renderInspector(); paint(); };
    if (k === "rd") { inspectorRd(box, o, tT, dI); return; }
    if (k === "lt") {
      box.append(field("Title", textIn(o, "title")), field("Subtitle", textIn(o, "sub", { ph: "optional" })),
        field("Side", seg([["left", "Left"], ["right", "Right"]], o.pos || "left", (v) => { o.pos = v; delete o.x; delete o.y; })), posFields(o));
    } else {
      box.append(field("Type", seg([["keypoint", "Key point"], ["stat", "Stat"], ["list", "List"]], o.type, (v) => {
        o.type = v; if (v === "stat") { o.value = o.value || "70%"; o.label = o.label || o.title || "label"; } if (v === "list" && !o.items) o.items = [o.body || "First", "Second", "Third"]; if (v === "keypoint") { o.title = o.title || o.label || "Point"; } })));
      if (o.type === "stat") box.append(field("Number", textIn(o, "value")), field("Label", textIn(o, "label")));
      else if (o.type === "list") {
        const ta = el("textarea", { class: "notes", rows: 5 }); ta.value = (o.items || []).join("\n");
        ta.oninput = () => { snapshot("items"); o.items = ta.value.split("\n").map((x) => x.trim()).filter(Boolean); touch(); paint(); };
        box.append(field("Title", textIn(o, "title")), field("Items", ta, "One per line, 3 to 5 works best."));
      } else {
        const ta = el("textarea", { class: "notes", rows: 3 }); ta.value = o.body || ""; ta.oninput = () => { snapshot("body"); o.body = ta.value; touch(); paint(); };
        box.append(field("Title", textIn(o, "title")), field("Text", ta));
      }
      box.append(field("Position", seg([["left", "Left"], ["center", "Centre"], ["right", "Right"]], o.pos || "right", (v) => { o.pos = v; delete o.x; delete o.y; })), posFields(o));
    }
    box.append(field("Animation", seg([["slide", "Slide"], ["fade", "Fade"], ["pop", "Pop"], ["none", "None"]], o.anim || (k === "lt" ? "slide" : "fade"), (v) => (o.anim = v))),
      el("div", { class: "lfe-two" }, field("Starts at", tT), field("Length (s)", dI)));
    const w = warnings(k, o);
    if (w.length) box.append(el("div", { class: "note lfe-warn" }, ...w.map((x) => el("div", {}, ic("triangle-alert"), x))));
  }

  // ---------------------------------------------------------------- preview engine
  const insUrl = (s) => `/api/long/overlay-file?root=${encodeURIComponent(E.root)}&src=${encodeURIComponent(/^(\/|[A-Za-z]:[\\/]|\\\\)/.test(s.src) ? s.src : `${E.root}/${s.src}`)}`;
  function enterIns(k, into, play) {
    const s = E.segs[k], main = $("#lfVideo"); main.pause();
    if (!E.insV) { E.insV = el("video", { class: "lfe-insv", preload: "auto", playsInline: true }); E.stage.insertBefore(E.insV, E.vLayer); }
    const v = E.insV, url = insUrl(s), at = s.in - s.vbase + into;
    const go = () => { v.currentTime = at; if (play) v.play().catch(() => {}); };
    if (v.dataset.src !== url) { v.dataset.src = url; v.src = url; v.onloadedmetadata = () => { v.onloadedmetadata = null; go(); }; } else go();
    v.hidden = false; E.insK = k; E.k = k;
  }
  function leaveIns() { if (E.insV) { E.insV.pause(); E.insV.hidden = true; } E.insK = null; }
  const isPlaying = () => (E.insK != null ? !!E.insV && !E.insV.paused : !$("#lfVideo").paused);
  function seekTo(t) {
    t = clamp(t, 0, E.total - 0.05);
    const k = clipIndexAt(t), s = E.segs[k], was = isPlaying(), v = $("#lfVideo");
    if (isIns(s)) enterIns(k, t - E.offs[k], was);
    else { const back = E.insK != null; leaveIns(); E.k = k; v.currentTime = toRaw(t); if (back && was) v.play().catch(() => {}); }
    E.t = t; paint();
  }
  function toggle() {
    if (E.insK != null) { if (E.insV.paused) E.insV.play().catch(() => {}); else E.insV.pause(); return; }
    const v = $("#lfVideo");
    if (v.paused) { if (E.t >= E.total - 0.1) { seekTo(0); if (E.insK != null) { E.insV.play().catch(() => {}); return; } } v.play().catch(() => {}); } else v.pause();
  }
  // playback moves on from segment k to the next one: another camera clip (jump if it isn't straight after) or an insert
  function advance(k) {
    const n = k + 1, s = E.segs[n], v = $("#lfVideo");
    if (!s) { v.pause(); if (E.insV) E.insV.pause(); return; }
    if (isIns(s)) { enterIns(n, 0, true); return; }
    const back = E.insK != null; leaveIns(); E.k = n;
    if (back || Math.abs(v.currentTime - s.in) > 0.05) v.currentTime = s.in;
    if (v.paused) v.play().catch(() => {});
  }
  function follow() { const x = E.t * E.pps - E.scroll.scrollLeft, w = viewW(); if (x > w - 40 || x < 0) E.scroll.scrollLeft = Math.max(0, E.t * E.pps - 80); }
  function loop() {
    if (!E) return;
    const v = $("#lfVideo");
    if (E.insK != null && E.insV && (!E.insV.paused || E.insV.ended)) {
      const s = E.segs[E.insK];
      if (!s || E.insV.ended || E.insV.currentTime >= s.out - s.vbase - 0.03) advance(E.insK);
      paint(); follow();
    } else if (v && !v.paused && E.segs.length) {
      const k = Math.min(E.k || 0, E.segs.length - 1), s = E.segs[k];
      if (isIns(s)) E.k = clipIndexAt(E.t);
      else if (v.currentTime >= s.out - 0.02) advance(k);
      else if (v.currentTime < s.in - 0.02) v.currentTime = s.in;
      paint(); follow();
    }
    raf = requestAnimationFrame(loop);
  }
  let mounted = {};
  function mount(slot, item, build) {
    const key = item ? JSON.stringify({ ...item, x: 0, y: 0 }) : "";       // moving it must not rebuild it (that would end a drag)
    if (mounted[slot] && mounted[slot].key === key && mounted[slot].item === item) { if (item && mounted[slot].el) OV.place(mounted[slot].el, item); return; }
    if (mounted[slot] && mounted[slot].el) mounted[slot].el.remove();
    mounted[slot] = { key, item, el: item ? build(item) : null };
    if (mounted[slot].el) E.ov.append(mounted[slot].el);
  }
  // cards and lower-thirds can be dragged on the preview: they get a free x,y (frame pixels), the preset sides are the default
  function ovDrag(e) {
    if (e.button !== 0) return;
    const target = e.target.closest(".ov-lt, .ov-card"); if (!target) return;
    const slot = ["lt", "cd"].find((s) => mounted[s] && mounted[s].el === target); if (!slot) return;
    const o = mounted[slot].item, k = slot; e.preventDefault(); e.stopPropagation();
    if (!E.sel || E.sel.o !== o) select(k, o, true);
    const sr = E.stage.getBoundingClientRect(), sc = sr.width / 1920, tr = target.getBoundingClientRect();
    const w = tr.width / sc, h = tr.height / sc;
    snapshot();
    const x0 = e.clientX, y0 = e.clientY, ox = typeof o.x === "number" ? o.x : (tr.left - sr.left) / sc, oy = typeof o.y === "number" ? o.y : (tr.top - sr.top) / sc;
    let moved = false;
    try { target.setPointerCapture(e.pointerId); } catch (err) { /* carry on */ }
    const move = (ev) => {
      if (!moved && Math.abs(ev.clientX - x0) + Math.abs(ev.clientY - y0) < 3) return;
      moved = true;
      let nx = ox + (ev.clientX - x0) / sc, ny = oy + (ev.clientY - y0) / sc;
      if (ev.shiftKey) { if (Math.abs(ev.clientX - x0) > Math.abs(ev.clientY - y0)) ny = oy; else nx = ox; }
      o.x = clamp(Math.round(nx), 0, Math.max(0, 1920 - Math.round(w))); o.y = clamp(Math.round(ny), 0, Math.max(0, 1080 - Math.round(h)));
      OV.place(target, o); touch(); syncPos();
    };
    const up = () => { target.removeEventListener("pointermove", move); target.removeEventListener("pointerup", up); if (moved) { renderInspector(); touch(); } else E.undo.pop(); };
    target.addEventListener("pointermove", move); target.addEventListener("pointerup", up);
  }
  function syncPos() { if (E.insPos && E.sel) { E.insPos.x.value = E.sel.o.x; E.insPos.y.value = E.sel.o.y; } }
  function paint() {
    if (!E || !E.ov) return;
    const t = E.t = editedNow(), sp = E.spec;
    E.tc.textContent = `${clock(t)} / ${mmss(E.total)}`;
    mount("lt", sp.lowerThirds.find((x) => t >= x.t && t < x.t + x.dur), (x) => OV.lowerThird(x));
    mount("cd", sp.cards.find((x) => t >= x.t && t < x.t + x.dur), (x) => OV.card(x));
    for (const s of ["lt", "cd"]) if (mounted[s] && mounted[s].el) mounted[s].el.classList.toggle("lfe-ovsel", !!(E.sel && E.sel.o === mounted[s].item));
    let capItem = null;
    if (sp.captions.on && E.words.length) {
      const W = E.words; let lo = 0, hi = W.length - 1, i = -1;
      while (lo <= hi) { const m = (lo + hi) >> 1; if (W[m].start <= t) { i = m; lo = m + 1; } else hi = m - 1; }
      if (i >= 0 && t - W[i].end < 0.6) capItem = { i, size: sp.captions.size, bottom: sp.captions.bottom };
    }
    mount("cap", capItem, (c) => OV.caption(E.words, c.i, { size: c.size / 19.2, bottom: c.bottom / 10.8 }));
    drawRd();
    syncOverlays(isPlaying());
    placePlayhead();
  }

  // ---------------------------------------------------------------- blur / hide regions (on the picture, in 1920x1080 frame pixels)
  function rdPos(o, tt) {
    const k = o.keys; if (k.length === 1 || tt <= k[0].dt) return k[0];
    for (let i = 0; i < k.length - 1; i++) if (tt < k[i + 1].dt) { const f = (tt - k[i].dt) / (k[i + 1].dt - k[i].dt); return { x: k[i].x + (k[i + 1].x - k[i].x) * f, y: k[i].y + (k[i + 1].y - k[i].y) * f }; }
    return k[k.length - 1];
  }
  const rdHandles = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
  function makeRdEl(o) {
    const b = el("div", { class: "lfe-rdbox" }, ...rdHandles.map((h) => el("i", { class: `rh ${h}`, "data-h": h })));
    b.onpointerdown = (e) => rdDrag(e, o, b, e.target.dataset.h || "move");
    return b;
  }
  function drawRd() {
    if (!E || !E.rdLayer) return;
    const t = E.t, sc = E.stage.clientWidth / 1920, sel = E.sel && E.sel.k === "rd" ? E.sel.o : null;
    const act = E.spec.redactions.filter((o) => (t >= o.t && t < o.t + o.dur) || o === sel);
    for (const [o, b] of E.rdEls) if (!act.includes(o)) { b.remove(); E.rdEls.delete(o); }
    act.forEach((o) => {
      let b = E.rdEls.get(o); if (!b) { b = makeRdEl(o); E.rdLayer.append(b); E.rdEls.set(o, b); }
      const p = rdPos(o, clamp(t - o.t, 0, o.dur)), on = t >= o.t && t < o.t + o.dur;
      b.style.left = `${p.x * sc}px`; b.style.top = `${p.y * sc}px`; b.style.width = `${o.w * sc}px`; b.style.height = `${o.h * sc}px`;
      b.className = `lfe-rdbox ${o.type}${on ? "" : " idle"}${o === sel ? " sel" : ""}`;
      const blur = o.type === "box" ? 0 : (o.type === "pixel" ? o.strength * 0.5 : o.strength) * sc;
      b.style.backdropFilter = on && blur ? `blur(${blur}px)` : "none"; b.style.webkitBackdropFilter = b.style.backdropFilter;
    });
  }
  function rdDrag(e, o, b, mode) {
    if (e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    if (!E.sel || E.sel.o !== o) select("rd", o, true);
    const tt = clamp(E.t - o.t, 0, o.dur), sc = E.stage.clientWidth / 1920;
    snapshot();
    let key;
    if (!o.track || o.keys.length === 1) { key = o.keys[0]; if (!o.track && o.keys.length > 1) o.keys = [key]; }
    else {
      key = o.keys.find((k) => Math.abs(k.dt - tt) < 0.25);
      if (!key) { const p = rdPos(o, tt); key = { dt: r2(tt), x: Math.round(p.x), y: Math.round(p.y) }; o.keys.push(key); o.keys.sort((a, b2) => a.dt - b2.dt); renderBlocks(); }
    }
    const cur = rdPos(o, tt), orig = { x: key.x, y: key.y, w: o.w, h: o.h }; void cur;
    const x0 = e.clientX, y0 = e.clientY;
    try { b.setPointerCapture(e.pointerId); } catch (err) { /* synthetic or lost pointer: carry on */ }
    const move = (ev) => {
      const dx = Math.round((ev.clientX - x0) / sc), dy = Math.round((ev.clientY - y0) / sc);
      let { x, y, w, h } = orig;
      if (mode === "move") { x += dx; y += dy; }
      else {
        if (mode.includes("e")) w += dx; if (mode.includes("s")) h += dy;
        if (mode.includes("w")) { x += dx; w -= dx; } if (mode.includes("n")) { y += dy; h -= dy; }
        if (w < 40) { if (mode.includes("w")) x -= 40 - w; w = 40; } if (h < 40) { if (mode.includes("n")) y -= 40 - h; h = 40; }
      }
      o.w = clamp(Math.round(w), 40, 1920); o.h = clamp(Math.round(h), 40, 1080);
      key.x = clamp(Math.round(x), 0, 1920 - o.w); key.y = clamp(Math.round(y), 0, 1080 - o.h);
      touch(); drawRd(); syncRd();
    };
    const up = () => { b.removeEventListener("pointermove", move); b.removeEventListener("pointerup", up); renderBlocks(); renderInspector(); };
    b.addEventListener("pointermove", move); b.addEventListener("pointerup", up);
  }
  function syncRd() {
    if (!E.insRd || !E.sel || E.sel.k !== "rd") return;
    const o = E.sel.o, p = rdPos(o, clamp(E.t - o.t, 0, o.dur));
    E.insRd.x.value = Math.round(p.x); E.insRd.y.value = Math.round(p.y); E.insRd.w.value = o.w; E.insRd.h.value = o.h;
  }
  function inspectorRd(box, o, tT, dI) {
    const numF = (label, key) => {
      const i = el("input", { type: "text", value: "" });
      i.onchange = () => {
        const v = Math.round(Number(i.value)); if (isNaN(v)) { syncRd(); return; }
        snapshot(); const tt = clamp(E.t - o.t, 0, o.dur);
        if (key === "w" || key === "h") o[key] = clamp(v, 40, key === "w" ? 1920 : 1080);
        else { let kk = (!o.track || o.keys.length === 1) ? o.keys[0] : o.keys.find((k) => Math.abs(k.dt - tt) < 0.25); if (!kk) { const p = rdPos(o, tt); kk = { dt: r2(tt), x: Math.round(p.x), y: Math.round(p.y) }; o.keys.push(kk); o.keys.sort((a, b) => a.dt - b.dt); } kk[key] = v; }
        o.keys.forEach((k) => { k.x = clamp(k.x, 0, 1920 - o.w); k.y = clamp(k.y, 0, 1080 - o.h); });
        touch(); renderBlocks(); drawRd(); syncRd();
      };
      E.insRd[key] = i; return field(label, i);
    };
    E.insRd = {};
    box.append(field("Effect", seg([["blur", "Blur"], ["pixel", "Pixelate"], ["box", "Black box"]], o.type, (v) => (o.type = v))));
    if (o.type !== "box") {
      const st = el("input", { type: "range", min: 6, max: 70, value: o.strength }); st.oninput = () => { snapshot("rdstrength"); o.strength = Number(st.value); touch(); drawRd(); };
      box.append(field(o.type === "pixel" ? "Block size" : "Strength", st));
    }
    const tr = el("label", { class: "switch lf-cap" }, el("input", { type: "checkbox", checked: !!o.track }), el("span"),
      el("div", {}, el("b", {}, "Follow movement"), el("small", {}, "Move the playhead, then drag the box to where it should be. Each move adds a point and the box glides between them.")));
    tr.querySelector("input").onchange = (ev) => { snapshot(); o.track = ev.target.checked; if (!o.track && o.keys.length > 1) o.keys = [o.keys[0]]; touch(); renderBlocks(); renderInspector(); drawRd(); };
    box.append(tr);
    if (o.track && o.keys.length) {
      box.append(el("div", { class: "lfe-kfs" }, ...o.keys.map((k, i) => el("div", { class: "lfe-kf" }, el("button", { class: "small", onclick: () => seekTo(o.t + k.dt) }, `+${k.dt.toFixed(1)} s`),
        el("span", {}, `x ${k.x}, y ${k.y}`), o.keys.length > 1 ? el("button", { class: "small", title: "Remove this point", onclick: () => { snapshot(); o.keys.splice(i, 1); touch(); renderBlocks(); renderInspector(); drawRd(); } }, ic("x")) : null))));
    }
    box.append(el("div", { class: "lfe-two" }, numF("X", "x"), numF("Y", "y")), el("div", { class: "lfe-two" }, numF("Width", "w"), numF("Height", "h")),
      el("div", { class: "lfe-two" }, field("Starts at", tT), field("Length (s)", dI)),
      el("p", { class: "hint" }, "Drag the box on the preview to move it; drag its square handles to resize. Use the blur for faces, names, numbers or tabs that shouldn't be seen."));
    syncRd();
  }

  function onKey(e) {
    const v = $("#lfview"); if (!E || !v || v.hidden) return;
    const typing = e.target.closest && e.target.closest("input[type=text], textarea, [contenteditable]");
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(); return; }
    if (mod && e.key.toLowerCase() === "z") { if (typing) return; e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (typing) return;
    if (e.code === "Space") { e.preventDefault(); toggle(); }
    else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); deleteSel(); }
    else if (!mod && e.key.toLowerCase() === "s") { e.preventDefault(); splitAt(E.t); }
    else if (!mod && e.key.toLowerCase() === "i") { e.preventDefault(); setMark("a", E.t); }
    else if (!mod && e.key.toLowerCase() === "o") { e.preventDefault(); setMark("b", E.t); }
    else if (e.key === "Escape") { if (E.mark) { E.mark = null; renderClips(); } else if (E.clipSel != null) { E.clipSel = null; renderClips(); renderInspector(); } }
    else if (e.key === "ArrowLeft") { e.preventDefault(); seekTo(E.t - (e.shiftKey ? 10 : 1)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); seekTo(E.t + (e.shiftKey ? 10 : 1)); }
  }

  return { show, stop: stopAll, isDirty: () => !!(E && E.dirty), seek: (t) => E && seekTo(t),
    info: () => E && { t: E.t, total: E.total, k: E.k, insK: E.insK, segs: E.segs.map((x) => ({ src: x.src || null, in: x.in, out: x.out })), dirty: E.dirty } };
})();
