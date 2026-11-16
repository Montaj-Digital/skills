// Render dialog for the long-form editor: a quick preview (about a minute from the playhead) or the full video.
// Uses the short-form app's modal (openModal / closeModal) and helpers (el, ic, toast).
"use strict";

const LFR = (() => {
  const get = (p) => fetch(p).then((r) => r.json());
  const post = (p, b) => fetch(p, { method: "POST", body: JSON.stringify(b || {}) }).then((r) => r.json());
  const mmss = (t) => { t = Math.max(0, Math.round(t)); const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60; return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`; };
  const nice = (t) => { const m = Math.round(t / 60); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : m < 1 ? `${Math.round(t)} s` : `${m} min`; };
  let C = null, timer = 0;
  const ratio = () => { try { return Number(localStorage.getItem("lfRenderRatio")) || 0; } catch (e) { return 0; } };

  async function open(ctx) {
    C = ctx; clearTimeout(timer);
    if (ctx.dirty()) { const ok = await ctx.save(); if (!ok) return; }
    const st = await get(`/api/long/render-status?root=${encodeURIComponent(C.root)}`).catch(() => ({}));
    if (st && st.running) return progress(st);
    choose();
  }
  const box = (...kids) => { openModal(el("div", { class: "box lfr" }, ...kids)); };
  const close = () => { clearTimeout(timer); closeModal(); };

  function choose() {
    const r = ratio();
    const est = r ? `about ${nice(r * C.total)}` : "roughly 20 to 40 minutes for an hour";
    const len = el("select", {}, ...[30, 60, 120].map((n) => el("option", { value: n, selected: n === 60 }, `${n} seconds`)));
    box(el("h3", {}, "Render"),
      el("div", { class: "lfr-opts" },
        el("div", { class: "lfr-opt" }, el("b", {}, "Preview"), el("p", {}, `Renders a short piece starting at the playhead (${mmss(C.t)}), with the real graphics and captions. Check the look before the full render.`),
          el("label", { class: "lfr-len" }, "Length ", len), el("button", { class: "primary", onclick: () => start("preview", C.t, Number(len.value)) }, ic("circle-play"), "Render preview")),
        el("div", { class: "lfr-opt" }, el("b", {}, "Full video"), el("p", {}, `All ${nice(C.total)} plus the end screen, 1920×1080. Takes ${est}. You can leave the editor open and keep working in another window.`),
          el("small", {}, "Saved to 06. Renders/Long-form 16x9 with a chapters file next to it."), el("button", { class: "primary", onclick: () => start("full") }, ic("clapperboard"), "Render full video"))),
      el("div", { class: "btns", style: "justify-content:flex-end;margin-top:12px" }, el("button", { onclick: close }, "Close")));
  }

  async function start(mode, t0, length) {
    const st = await post("/api/long/render-start", { root: C.root, mode, t0, length });
    if (st.error) { toast(st.error); return; }
    progress(st);
  }

  function progress(st) {
    clearTimeout(timer);
    const finished = st.steps.filter((s) => s.state === "done" || s.state === "skipped").length;
    const failed = st.steps.find((s) => s.state === "failed");
    const pct = st.done ? 100 : Math.round(((finished + (st.steps.find((s) => s.key === "video" && s.state === "running") ? st.pct / 100 : 0)) / st.steps.length) * 100);
    const title = st.mode === "preview" ? "Rendering the preview" : "Rendering the full video";
    const kids = [el("h3", {}, st.done ? (st.mode === "preview" ? "Preview ready" : "Video ready") : failed || st.error ? "Render stopped" : title),
      el("div", { class: "progress" }, el("i", { style: `width:${pct}%` })),
      el("ul", { class: "steps big" }, ...st.steps.map((s) => el("li", { class: s.state }, el("span", { class: "ic" }, s.state === "done" ? ic("check") : s.state === "failed" ? ic("x") : s.state === "skipped" ? "–" : ""), el("span", { class: "lbl" }, s.label), s.info ? el("span", { class: "inf" }, s.info) : null)))];
    if (st.error) kids.push(el("div", { class: "err" }, st.error));
    if (st.done && st.mode === "preview") {
      kids.push(el("video", { class: "lfr-vid", controls: true, autoplay: true, src: `/api/long/render-file?root=${encodeURIComponent(C.root)}&name=preview.mp4&v=${Date.now()}` }),
        el("div", { class: "btns", style: "justify-content:flex-end;margin-top:12px" }, el("button", { onclick: choose }, "Back"), el("button", { class: "primary", onclick: () => start("full") }, ic("clapperboard"), "Render the full video")));
    } else if (st.done) {
      kids.push(el("div", { class: "hint" }, st.output.replace(/^\/Users\/[^/]+/, "~")),
        el("div", { class: "btns", style: "justify-content:flex-end;margin-top:12px" },
          window.PORTAL ? el("button", { onclick: () => downloadFile(st.output) }, ic("download"), "Download")
            : el("button", { onclick: () => post("/api/long/reveal", { root: C.root, what: "output", path: st.output }) }, ic("folder-open"), "Show in Finder"),
          window.openPosts ? el("button", { onclick: () => { close(); window.openPosts(); } }, ic("send"), "Prepare posts") : null,
          el("button", { class: "primary", onclick: close }, "Done")));
    } else if (st.running) {
      kids.push(el("div", { class: "hint" }, st.mode === "full" ? "You can close this window; the render keeps going. Open Render again to see how far it is." : "Usually a minute or two."),
        el("div", { class: "btns", style: "justify-content:space-between;margin-top:12px" }, el("button", { onclick: close }, "Hide"), el("button", { onclick: async () => { await post("/api/long/render-stop", { root: C.root }); } }, "Stop")));
    } else {
      kids.push(el("div", { class: "btns", style: "justify-content:flex-end;margin-top:12px" }, el("button", { onclick: choose }, "Back"), el("button", { class: "primary", onclick: () => start(st.mode, C.t) }, "Try again")));
    }
    if (st.log && st.log.length) kids.push(el("details", {}, el("summary", { class: "hint" }, "Details"), el("pre", { class: "log" }, st.log.join("\n"))));
    if (!$(".lfr")) box(...kids); else { const b = $(".lfr"); b.innerHTML = ""; b.append(...kids); }
    if (st.running) timer = setTimeout(async () => {
      if (!$(".lfr")) return;                              // the window was hidden
      const s2 = await get(`/api/long/render-status?root=${encodeURIComponent(C.root)}`).catch(() => null);
      progress(s2 && s2.steps ? s2 : st);
    }, 1200);
  }

  return { open };
})();
