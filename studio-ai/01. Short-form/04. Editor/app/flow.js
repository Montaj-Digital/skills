// Splash screen ("Think it. Upload it. Create it.") and the new-video wizard:
// ① who it is for (brand) → ② choose a look (Clean / Takeover) → ③ format, upload and details → ④ create → the timeline opens.
"use strict";

const W = { step: 1, brand: "default", look: "clean", format: "reel", file: null, url: null, name: "", notes: "", root: null, raw: null, timer: 0 };
const WZ_FORMATS = [["reel", "Reel", "9:16", 9, 16], ["feed", "Feed", "4:5", 4, 5], ["square", "Square", "1:1", 1, 1], ["landscape", "Landscape", "16:9", 16, 9]];

// ---------------------------------------------------------------- sections: Short-form | Long-form
// Long-form is optional: the server says so in /api/sections, and its screens come from /long/app/long.js.
let SECTIONS = { long: false };
const sectionsReady = fetch("/api/sections").then((r) => r.json()).then((s) => {
  SECTIONS = s;
  if (s.long) document.head.append(el("link", { rel: "stylesheet", href: "/long/app/long.css" }));
}).catch(() => {});
let section = "short";
try { section = sessionStorage.getItem("section") === "long" ? "long" : "short"; } catch (e) {}
function setSection(s) { section = s; try { sessionStorage.setItem("section", s); } catch (e) {} }
function loadLong() {
  if (typeof LF !== "undefined") return Promise.resolve();
  return new Promise((ok, no) => document.body.append(el("script", { src: "/long/app/long.js", onload: ok, onerror: () => no(new Error("long-form didn't load")) })));
}
// the New button and the splash: Short-form goes on to the wizard below, Long-form to long.js
async function newInSection() {
  await sectionsReady;
  if (section === "long" && SECTIONS.long) { try { await loadLong(); } catch (e) { toast(e.message); return; } LF.openWizard(); } else openWizard();
}
async function openCreate() {
  await sectionsReady;
  if (!SECTIONS.long) { setSection("short"); return openWizard(); }
  leave(() => {
    S.leaving = false; hideHome();
    const w = wizardEl(); w.innerHTML = "";
    const pick = (sec) => { setSection(sec); closeWizard(); newInSection(); };
    const card = (sec, title, sub, best, icon) => el("button", { class: "look", onclick: () => pick(sec) },
      el("div", { class: "sec-ico" }, ic(icon)),
      el("div", { class: "look-t" }, el("b", {}, title), el("span", {}, sub), el("ul", {}, ...best.map((x) => el("li", {}, ic("check"), x)))),
      el("span", { class: "look-go" }, `Start ${title}`, ic("chevron-right")));
    w.append(el("div", { class: "wz-in" },
      el("div", { class: "wz-top" }, el("span"), el("button", { class: "icon ghost", title: "Close", "aria-label": "Close", onclick: () => { closeWizard(); if (!S.spec || S.mode === "new") showHome(true); } }, ic("x"))),
      el("h2", { class: "wz-h" }, "What are you ", el("span", { class: "gt" }, "creating"), "?"),
      el("p", { class: "wz-sub" }, "Pick the kind of video. Both use the same brand and the same editor."),
      el("div", { class: "looks" },
        card("short", "Short-form", "Reels and social: seconds to a few minutes.", ["Reel, Feed, Square or short Landscape", "Punch-in zooms and word captions", "Glass cards and takeovers"], "clapperboard"),
        card("long", "Long-form", "YouTube and webinars: 60+ minutes.", ["Picks the file in place, no copying", "Chapters and YouTube timestamps", "Lower-thirds and an occasional card"], "film"))));
  });
}
// the Short-form | Long-form switch at the top of Open
function sectionSwitch(after) {
  if (!SECTIONS.long) return null;
  return el("div", { class: "secsw", role: "tablist", "aria-label": "Section" }, ...[["short", "Short-form"], ["long", "Long-form"]].map(([k, l]) =>
    el("button", { role: "tab", class: section === k ? "on" : "", "aria-selected": String(section === k), onclick: () => { setSection(k); after(); } }, l)));
}

// ---------------------------------------------------------------- splash (once per browser session)
function shouldSplash() { try { return !sessionStorage.getItem("splashSeen"); } catch (e) { return true; } }
function showSplash(p) {
  if ($("#splash")) return;
  const step = 0.55, t0 = 0.45;
  const lines = [["Think it.", "l1"], ["Upload it.", "l2"], ["Create it.", "l3"]];
  const s = el("div", { class: "splash", id: "splash", role: "dialog", "aria-label": "Studio AI" },
    el("i", { class: "orb o1" }), el("i", { class: "orb o2" }), el("i", { class: "orb o3" }),
    el("div", { class: "splash-in" },
      el("img", { class: "splash-logo logo-light", src: "/brand/logo-light.svg", alt: "Your brand" }),
      el("img", { class: "splash-logo logo-dark", src: "/brand/logo-white.svg", alt: "Your brand" }),
      el("div", { class: "splash-kicker" }, "Studio AI"),
      el("h1", { class: "splash-lines" }, ...lines.map(([t, c], i) => el("span", { class: `sl ${c}`, style: `animation-delay:${t0 + i * step}s` }, t))),
      el("div", { class: "splash-cta", style: `animation-delay:${t0 + lines.length * step + 0.15}s` },
        el("button", { class: "primary big", id: "splashGo", onclick: () => { closeSplash(); openCreate(); } }, "Let's create", ic("chevron-right")),
        el("div", { class: "splash-alt" },
          el("button", { class: "linkish", onclick: () => { closeSplash(); showHome(true); } }, "Open a past video"),
          p && !p.none ? el("button", { class: "linkish", onclick: closeSplash }, `Continue editing ${p.name}`) : null))));
  document.body.append(s);
  try { sessionStorage.setItem("splashSeen", "1"); } catch (e) {}
  setTimeout(() => $("#splashGo")?.focus(), (t0 + lines.length * step + 0.4) * 1000);
}
function closeSplash() {
  const s = $("#splash"); if (!s) return;
  s.classList.add("out"); setTimeout(() => s.remove(), 380);
}

// ---------------------------------------------------------------- wizard shell
function openWizard() {
  leave(() => {
    S.leaving = false;
    Object.assign(W, { step: 1, brand: W.brand || "default", look: "clean", format: "reel", file: null, name: "", notes: "" });
    hideHome(); drawWizard();
  });
}
function wizardEl() {
  let w = $("#wizard");
  if (!w) { w = el("div", { id: "wizard", class: "wizard" }); document.body.append(w); }
  w.hidden = false; return w;
}
function closeWizard() { const w = $("#wizard"); if (w) w.hidden = true; clearTimeout(W.timer); }
const wizardOpen = () => { const w = $("#wizard"); return !!(w && !w.hidden); };

function drawWizard() {
  const w = wizardEl(); w.innerHTML = "";
  const labels = ["Who it's for", "Choose a look", "Upload and details", "Create"];
  const stepper = el("ol", { class: "stepper" }, ...labels.map((l, i) =>
    el("li", { class: i + 1 === W.step ? "on" : i + 1 < W.step ? "done" : "" }, el("b", {}, i + 1 < W.step ? ic("check") : String(i + 1)), l)));
  const close = W.step < 4 ? el("button", { class: "icon ghost", title: "Close", "aria-label": "Close", onclick: () => { closeWizard(); if (!S.spec || S.mode === "new") showHome(true); } }, ic("x")) : null;
  const body = el("div", { class: "wz-body" });
  w.append(el("div", { class: "wz-in" }, el("div", { class: "wz-top" }, stepper, close), body));
  if (W.step === 1) { if (window.brandStep) brandStep(body, W.brand, (id) => { W.brand = id; W.step = 2; drawWizard(); }); else { W.step = 2; drawWizard(); } }
  else if (W.step === 2) stepLook(body); else if (W.step === 3) stepUpload(body); else stepCreate(body);
}

// ---------------------------------------------------------------- ② look (① who it is for is brandStep() in brands.js)
function stepLook(b) {
  const looks = [
    { key: "clean", title: "Clean", sub: "Glass cards and word-by-word captions over the footage.",
      best: ["Talking-head explainers", "Tips and how-tos", "When the speaker carries it"] },
    { key: "takeover", title: "Takeover", sub: "Cards, plus gradient cutaways for the key points.",
      best: ["Lists, tools and big numbers", "A recap at the end", "A livelier, more produced edit"] },
  ];
  b.append(el("h2", { class: "wz-h" }, "Choose a ", el("span", { class: "gt" }, "look")),
    el("p", { class: "wz-sub" }, "Claude plans the video in this style. You can still add or remove anything in the editor."),
    el("div", { class: "wz-actions left" }, el("button", { onclick: () => { W.step = 1; drawWizard(); } }, ic("arrow-left"), "Back")),
    el("div", { class: "looks" }, ...looks.map((L) => el("button", { class: `look${W.look === L.key ? " on" : ""}`, onclick: () => { W.look = L.key; W.step = 3; drawWizard(); } },
      lookDemo(L.key),
      el("div", { class: "look-t" }, el("b", {}, L.title), el("span", {}, L.sub),
        el("ul", {}, ...L.best.map((x) => el("li", {}, ic("check"), x)))),
      el("span", { class: "look-go" }, `Use ${L.title}`, ic("chevron-right"))))));
}
// tiny looping mock-ups of each look
function lookDemo(k) {
  const person = () => el("i", { class: "person" }, el("i", { class: "head" }), el("i", { class: "body" }));
  if (k === "clean") return el("div", { class: "demo" }, el("div", { class: "phone footage" }, person(),
    el("i", { class: "dcap" }, el("i", { class: "w1" }, "the key"), " ", el("i", { class: "w2" }, "point")),
    el("i", { class: "gcard" }, el("i", { class: "gi" }), el("i", { class: "gl" }), el("i", { class: "gl s" }))));
  return el("div", { class: "demo" }, el("div", { class: "phone grad" },
    el("i", { class: "pip footage" }, person()), el("i", { class: "kick" }), el("i", { class: "ttl" }),
    el("i", { class: "mrow r1" }), el("i", { class: "mrow r2" }), el("i", { class: "mrow r3" })));
}

// ---------------------------------------------------------------- ② upload and details
function stepUpload(b) {
  const F = WZ_FORMATS.find((f) => f[0] === W.format);
  const k = Math.min(560 / F[3], 440 / F[4]);
  const fileIn = el("input", { type: "file", accept: "video/*,.mov,.mp4,.m4v", hidden: true });
  fileIn.onchange = (e) => pickFile(e.target.files[0]);
  const drop = el("div", { class: `wz-drop${W.file ? " has" : ""}`, style: `width:${Math.round(F[3] * k)}px;height:${Math.round(F[4] * k)}px` });
  if (W.file) {
    const v = el("video", { muted: true, loop: true, playsInline: true, autoplay: true }); v.src = W.url;
    drop.append(v, el("button", { class: "small change", onclick: (e) => { e.stopPropagation(); fileIn.click(); } }, "Change video"));
  } else {
    drop.append(el("div", { class: "dz-in" }, el("div", { class: "dz-ic" }, ic("film")), el("b", {}, "Drop the raw video here"),
      el("span", {}, "or"), el("button", { onclick: (e) => { e.stopPropagation(); fileIn.click(); } }, "Choose a file"),
      el("small", {}, "MP4 or MOV, straight from the camera")));
  }
  drop.addEventListener("click", () => { if (!W.file) fileIn.click(); });
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => pickFile(e.dataTransfer.files[0]));

  const err = el("div", { class: "err" });
  const name = el("input", { type: "text", placeholder: "AI tools for agencies", value: W.name });
  name.oninput = () => { W.name = name.value; err.textContent = ""; };
  const notes = el("textarea", { class: "notes", placeholder: "What the cards should say, tools or numbers to show, takes to drop, a different call to action…" });
  notes.value = W.notes; notes.oninput = () => (W.notes = notes.value);
  const fmts = el("div", { class: "wz-fmts" }, ...WZ_FORMATS.map(([key, l, r, w, h]) =>
    el("button", { class: `wz-fmt${W.format === key ? " on" : ""}`, onclick: () => { W.format = key; drawWizard(); } },
      el("span", { class: "shape", style: `aspect-ratio:${w}/${h}` }), el("b", {}, l), el("small", {}, r))));
  const create = () => {
    if (!W.file) { err.textContent = "Choose the raw video first."; return; }
    if (!W.name.trim()) { err.textContent = "Give the video a name."; name.focus(); return; }
    W.step = 4; drawWizard(); uploadAndStart();
  };
  b.append(el("h2", { class: "wz-h" }, "Upload and ", el("span", { class: "gt" }, "details")),
    el("p", { class: "wz-sub" }, el("span", { class: "tag" }, window.brandName ? brandName(W.brand) : "Your brand"), " ", el("span", { class: "tag" }, W.look === "takeover" ? "Takeover look" : "Clean look"), " Pick the format, drop in the raw video and give it a name."),
    el("div", { class: "wz-grid" },
      el("div", { class: "wz-left" }, drop, fileIn),
      el("div", { class: "wz-right" },
        el("label", { class: "wz-l" }, "Format"), fmts,
        el("label", { class: "wz-l" }, "Video name"), name,
        el("label", { class: "wz-l" }, "Notes for Claude ", el("span", { class: "opt" }, "optional")), notes,
        claudeNote(), err,
        el("div", { class: "wz-actions" },
          el("button", { onclick: () => { W.step = 2; drawWizard(); } }, ic("arrow-left"), "Back"),
          el("button", { class: "primary big", onclick: create }, ic("sparkles"), "Create video")))));
}
function pickFile(f) {
  if (!f) return;
  if (!/^video\//.test(f.type) && !/\.(mov|mp4|m4v|webm|mkv)$/i.test(f.name)) { toast("That isn't a video file."); return; }
  if (W.url) URL.revokeObjectURL(W.url);
  W.file = f; W.url = URL.createObjectURL(f);
  if (!W.name) W.name = f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  drawWizard();
}

// ---------------------------------------------------------------- ③ create
function stepCreate(b) {
  const left = el("div", { class: "wz-left" });
  const src = W.url || (W.root ? `/api/new/raw?root=${encodeURIComponent(W.root)}` : null);
  if (src) { const v = el("video", { class: "wz-raw", muted: true, loop: true, playsInline: true, autoplay: true }); v.src = src; left.append(v); }
  b.append(el("h2", { class: "wz-h" }, "Creating your ", el("span", { class: "gt" }, "video")),
    el("p", { class: "wz-sub", id: "wzSub" }, "Copying the video into 05. Projects…"),
    el("div", { class: "wz-grid" }, left,
      el("div", { class: "wz-right", id: "wzJob" }, el("div", { class: "progress" }, el("i", { id: "wzBar" })), el("div", { class: "hint", id: "wzPct" }, "Uploading 0%"))));
}
async function uploadAndStart() {
  if (window.PORTAL) {                       // the portal: a resumable upload, then the camera file moves into a new project
    const bar = () => $("#wzBar"), pct = () => $("#wzPct");
    let r;
    try {
      const upload = await uploadFile(W.file, (p) => { if (bar()) bar().style.width = p * 100 + "%"; if (pct()) pct().textContent = `Uploading ${Math.round(p * 100)}%`; });
      r = await fetch("/api/new/upload", { method: "POST", body: JSON.stringify({ upload, name: W.name.trim(), file: W.file.name }) }).then((x) => x.json());
    } catch (e) { r = { error: e.message }; }
    if (r.error || !r.root) { W.step = 3; drawWizard(); toast(r.error || "The upload failed."); return; }
    W.root = r.root; W.raw = r.raw;
    try { localStorage.setItem("newjob", JSON.stringify({ root: r.root, raw: r.raw, name: W.name.trim() })); } catch (e) {}
    const st = await fetch("/api/new/start", { method: "POST", body: JSON.stringify({ root: r.root, raw: r.raw, notes: W.notes, format: W.format, template: W.look, brand: W.brand }) }).then((x) => x.json());
    return showWizardJob(st);
  }
  const xhr = new XMLHttpRequest();
  xhr.open("PUT", `/api/new/upload?name=${encodeURIComponent(W.name.trim())}&file=${encodeURIComponent(W.file.name)}`);
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const p = (e.loaded / e.total) * 100, bar = $("#wzBar"), t = $("#wzPct");
    if (bar) bar.style.width = p + "%"; if (t) t.textContent = `Uploading ${Math.round(p)}%`;
  };
  xhr.onload = async () => {
    const r = JSON.parse(xhr.responseText || "{}");
    if (xhr.status !== 200) { W.step = 3; drawWizard(); toast(r.error || "The upload failed."); return; }
    W.root = r.root; W.raw = r.raw;
    try { localStorage.setItem("newjob", JSON.stringify({ root: r.root, raw: r.raw, name: W.name.trim() })); } catch (e) {}
    const st = await fetch("/api/new/start", { method: "POST", body: JSON.stringify({ root: r.root, raw: r.raw, notes: W.notes, format: W.format, template: W.look, brand: W.brand }) }).then((x) => x.json());
    showWizardJob(st);
  };
  xhr.onerror = () => { W.step = 3; drawWizard(); toast("The upload failed. Is the editor still running?"); };
  xhr.send(W.file);
}
function showWizardJob(st) {
  clearTimeout(W.timer);
  const box = $("#wzJob"); if (!box || !st || !st.steps) return;
  box.innerHTML = "";
  const finished = st.steps.filter((s) => s.state === "done" || s.state === "skipped").length;
  const sub = $("#wzSub");
  if (sub) sub.textContent = st.done ? "Done. Opening the timeline…" : st.error ? "A step failed. Fix the cause, then retry from there." :
    "This takes a few minutes. You can leave this tab open and come back.";
  box.append(el("div", { class: "progress" }, el("i", { style: `width:${Math.round((finished / st.steps.length) * 100)}%` })),
    el("ul", { class: "steps big" }, ...st.steps.map((s) => el("li", { class: s.state },
      el("span", { class: "ic" }, s.state === "done" ? ic("check") : s.state === "failed" ? ic("x") : s.state === "skipped" ? "–" : ""),
      el("span", { class: "lbl" }, s.label), s.info ? el("span", { class: "inf" }, s.info) : null))));
  const failed = st.steps.find((s) => s.state === "failed");
  if (st.error) box.append(el("div", { class: "err" }, st.error));
  if (failed) box.append(el("div", { class: "wz-actions" },
    el("button", { onclick: () => { try { localStorage.removeItem("newjob"); } catch (e) {} W.step = 3; drawWizard(); } }, "Start over"),
    el("button", { class: "primary", onclick: async () => showWizardJob(await fetch("/api/new/start", { method: "POST", body: JSON.stringify({ root: st.root, raw: W.raw, from: failed.key }) }).then((x) => x.json())) },
      `Retry from “${failed.label}”`)));
  if (!st.claude && !st.done) box.append(claudeNote());
  box.append(el("details", {}, el("summary", { class: "hint" }, "Details"), el("pre", { class: "log" }, (st.log || []).join("\n"))));
  if (st.done) { try { localStorage.removeItem("newjob"); } catch (e) {} setTimeout(() => openReel(st.edit), 700); return; }
  if (st.running) W.timer = setTimeout(async () => {
    const s2 = await fetch(`/api/new/status?root=${encodeURIComponent(st.root)}`).then((x) => x.json()).catch(() => null);
    showWizardJob(s2 && s2.steps ? s2 : st);
  }, 1200);
}
// a video that was being created when the page was reloaded: back to step ③
async function resumeWizardJob() {
  let j; try { j = JSON.parse(localStorage.getItem("newjob") || "null"); } catch (e) {}
  if (!j) return false;
  const st = await fetch(`/api/new/status?root=${encodeURIComponent(j.root)}`).then((x) => (x.ok ? x.json() : null)).catch(() => null);
  if (!st) { try { localStorage.removeItem("newjob"); } catch (e) {} return false; }
  Object.assign(W, { step: 4, root: j.root, raw: j.raw, name: j.name, file: null, url: null });
  drawWizard(); showWizardJob(st);
  return true;
}
