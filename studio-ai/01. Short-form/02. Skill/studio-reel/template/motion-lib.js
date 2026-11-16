// Motion helpers for the reel template. build.py appends one block of calls per
// card and caption, with times in seconds on the edited timeline.
//
// Glass elements only ever animate opacity/transform on THEMSELVES: a filter or
// opacity on an ancestor would cut their backdrop blur, so blur-ins are kept to
// the content inside each card.
var tl = gsap.timeline({ paused: true });
var OUT = "power3.out";

// Centre every card group on the frame's centre line from its laid-out size
// (re-run once fonts are in, since text sets widths).
// Reel: centre on x=540. Other formats (window.__LAYOUT has cx): scale the group onto the panel point
// (cx, cy) — chips on (cx, chipY) — or onto the card's own data-y. Landscape's panel sits beside the speaker.
function centreCards() {
  var L = window.__LAYOUT || {};
  document.querySelectorAll(".card-host").forEach(function (h) {
    var l = Infinity, r = -Infinity, t = Infinity, b = -Infinity;
    h.querySelectorAll(":scope > .g, :scope > .swap").forEach(function (e) {
      l = Math.min(l, e.offsetLeft); r = Math.max(r, e.offsetLeft + e.offsetWidth);
      t = Math.min(t, e.offsetTop); b = Math.max(b, e.offsetTop + e.offsetHeight);
    });
    if (!(l < r)) return;
    var x = h.dataset.x ? parseFloat(h.dataset.x) : null;   // moved sideways in the editor (group centre)
    if (!L.cx) { h.style.transform = "translateX(" + Math.round((x == null ? 540 : x) - (l + r) / 2) + "px)"; return; }
    var chip = h.classList.contains("is-chip");
    var s = chip ? L.chipScale : L.scale, gx = (l + r) / 2, gy = (t + b) / 2;
    var cy = h.dataset.y ? parseFloat(h.dataset.y) : (chip ? L.chipY : L.cy);
    h.style.transformOrigin = gx + "px " + gy + "px";
    h.style.transform = "translate(" + Math.round((x == null ? L.cx : x) - gx) + "px," + Math.round(cy - gy) + "px) scale(" + s + ")";
  });
}
centreCards();
if (document.fonts) document.fonts.ready.then(centreCards);

function $all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
function exists(list) { return list.filter(function (s) { return document.querySelector(s); }); }

// captions: each word blurs + rises in as it is spoken; the group clears before the next
function word(sel, t) {
  tl.fromTo(sel, { opacity: 0, y: 12, filter: "blur(8px)" },
    { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.24, ease: "power2.out" }, t);
}
function capOut(sel, t) { tl.to(sel, { opacity: 0, duration: 0.12, ease: "none" }, t - 0.12); }

// outline glow flares as a card lands, then settles to a soft rest
function glow(sel, t, stagger) {
  tl.fromTo(sel, { "--gl": 1 }, { "--gl": 0.22, duration: 1.2, ease: "power2.out", stagger: stagger || 0 }, t + 0.2);
}
function gIn(sel, t, from, stagger) {
  tl.fromTo(sel, Object.assign({ opacity: 0, scale: 0.94, y: 18 }, from || {}),
    { opacity: 1, scale: 1, y: 0, duration: 0.45, ease: OUT, stagger: stagger || 0 }, t);
  glow(sel, t, stagger);
}
function gPop(sel, t) {
  tl.fromTo(sel, { opacity: 0, scale: 0.4 }, { opacity: 1, scale: 1, duration: 0.55, ease: "back.out(1.7)" }, t);
  glow(sel, t);
}
function gBounce(sel, t) {
  tl.fromTo(sel, { opacity: 0, scale: 0.8, y: 20 }, { opacity: 1, scale: 1, y: 0, duration: 0.5, ease: "back.out(1.5)" }, t);
  glow(sel, t);
}
function gOut(sel, t, stagger) {
  tl.to(sel, { opacity: 0, scale: 0.97, y: 8, duration: 0.25, ease: "power2.in", stagger: stagger || 0 }, t - 0.25);
}
function cIn(sel, t, stagger) {
  tl.fromTo(sel, { opacity: 0, y: 8, filter: "blur(10px)" },
    { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.38, ease: OUT, stagger: stagger == null ? 0.07 : stagger }, t);
}
function popIn(sel, t) {
  tl.fromTo(sel, { opacity: 0, scale: 0.5 }, { opacity: 1, scale: 1, duration: 0.5, ease: "back.out(1.7)" }, t);
}
function draw(sel, t, dur) {
  tl.fromTo(sel, { strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: dur || 0.7, ease: "power2.inOut", stagger: 0.05 }, t);
}
function fadeOut(sel, t) { tl.to(sel, { opacity: 0, duration: 0.25 }, t - 0.25); }

// ---------------- card types ----------------
var CARD = {
  questions: function (id, c) {
    c.times.forEach(function (t, i) {
      var q = "#" + id + "-q" + i;
      gIn(q, t, { x: -24, y: 0 });
      cIn([q + " .dot", q + " .ptxt"], t + 0.1);
    });
    if (c.dim_at) tl.to(exists(c.times.slice(0, -1).map(function (_, i) { return "#" + id + "-q" + i + " .ptxt"; })), { opacity: 0.62, duration: 0.4 }, c.dim_at);
    gOut("#" + id + " .g", c.out, 0.06);
  },
  hub: function (id, c) {
    var h = "#" + id;
    gIn(h + " .side", c.t, { scale: 0.8, y: 0 }, 0.08);
    cIn(h + " .side .ic", c.t + 0.1, 0.08);
    gPop(h + " .hub", c.t_hub);
    cIn(h + " .orb", c.t_hub + 0.15, 0);
    draw(h + " .ln", c.t_lines, 0.75);
    if (c.t_pulse) tl.to(h + " .orb", { scale: 1.12, duration: 0.18, ease: "power2.out" }, c.t_pulse)
      .to(h + " .orb", { scale: 1, duration: 0.3, ease: "power2.inOut" }, c.t_pulse + 0.18);
    fadeOut(h + " .lines", c.out);
    gOut(h + " .g", c.out);
  },
  statement: function (id, c) {
    var h = "#" + id;
    gIn(h + " .statement", c.t);
    cIn(h + " .kick", c.t + 0.18);
    tl.fromTo(h + " .sicon", { opacity: 0 }, { opacity: 1, duration: 0.2 }, c.t_icon);
    draw(h + " .sicon .ic *", c.t_icon, 0.6);
    var leads = c.leads || [];
    leads.forEach(function (l, i) {  // each lead word blurs in on its cue, then gives way to the next
      var el = $all(h + " .sword.lead")[i], next = i + 1 < leads.length ? leads[i + 1].t : c.t_word;
      cIn(el, l.t);
      tl.to(el, { opacity: 0, y: -10, filter: "blur(8px)", duration: 0.2, ease: "power2.in" }, next - 0.18);
    });
    cIn(h + " .sword.final", c.t_word);
    tl.fromTo(h + " .uline", { scaleX: 0 }, { scaleX: 1, duration: 0.45, ease: "power2.inOut" }, c.t_word + 0.25);
    gOut(h + " .statement", c.out);
  },
  compare: function (id, c) {
    var a = "#" + id + "-a", b = "#" + id + "-b";
    gIn(a, c.t_left); cIn([a + " .kick", a + " .ra"], c.t_left + 0.12);
    gIn(b, c.t_right); cIn([b + " .kick", b + " .ra"], c.t_right + 0.12);
    if (c.t_swap) {
      tl.fromTo("#" + id + " .swap", { opacity: 0, scale: 0.3, rotate: -180 }, { opacity: 1, scale: 1, rotate: 0, duration: 0.55, ease: "back.out(1.6)" }, c.t_swap);
      tl.to([a + " .ra", b + " .ra"], { opacity: 0, filter: "blur(10px)", y: -8, duration: 0.25, ease: "power2.in" }, c.t_swap + 0.17);
      tl.fromTo([a + " .rb", b + " .rb"], { opacity: 0, filter: "blur(10px)", y: 10 }, { opacity: 1, filter: "blur(0px)", y: 0, duration: 0.38, ease: OUT }, c.t_swap + 0.37);
    }
    gOut([a, b, "#" + id + " .swap"], c.out, 0.04);
  },
  steps: function (id, c) {
    var n = c.times.length, prev = 0;
    tl.fromTo("#" + id + " .bar", { opacity: 0 }, { opacity: 1, duration: 0.3 }, c.times[0] - 0.05);
    c.times.forEach(function (t, i) {
      var s = "#" + id + "-s" + i, to = i === n - 1 && c.t_highlight ? 0.86 : (i + 1) / n;
      gIn(s, t);
      cIn(exists([s + " .num", s + " .sic", s + " .slab", s + " .ssub"]), t + 0.1);
      tl.fromTo("#" + id + " .bar i", { scaleX: prev }, { scaleX: to, duration: 0.6, ease: "power2.inOut", immediateRender: i === 0 }, t + 0.1);
      prev = to;
    });
    if (c.t_highlight) {
      tl.to("#" + id + "-s" + (n - 1), { "--gl": 1, duration: 0.45, ease: OUT }, c.t_highlight);  // last step lights up and stays lit
      tl.fromTo("#" + id + " .bar i", { scaleX: prev }, { scaleX: 1, duration: 0.5, ease: "power2.inOut" }, c.t_highlight);
    }
    fadeOut("#" + id + " .bar", c.out);
    gOut("#" + id + " .step", c.out, 0.05);
  },
  chip: function (id, c) {
    gIn("#" + id + " .chip", c.t, { y: -14 });
    cIn("#" + id + " .chip > *", c.t + 0.09, 0.1);
    gOut("#" + id + " .chip", c.out);
  },
  feature: function (id, c) {
    var h = "#" + id;
    gIn(h + " .hug", c.t);
    popIn(h + " .itile", c.t + 0.07);
    cIn(h + " .kick", c.t + 0.12);
    cIn(h + "-w1", c.t_title || c.t + 0.2);
    if (document.querySelector(h + "-w2")) cIn(h + "-w2", c.t_rest || c.t + 0.42);
    gOut(h + " .hug", c.out);
  },
  tiles: function (id, c) {
    c.times.forEach(function (t, i) {
      var a = "#" + id + "-a" + i;
      gBounce(a, t);
      cIn(exists([a + " .logo", a + " .ic", a + " span"]), t + 0.1);
    });
    if (c.t_plus) { gIn("#" + id + " .plus", c.t_plus, { y: 14 }); cIn("#" + id + " .plus > *", c.t_plus + 0.1); }
    gOut("#" + id + " .g", c.out, 0.04);
  },
  connect: function (id, c) {
    var h = "#" + id;
    gPop(h + " .ctile", c.t);
    cIn([h + " .ctile .logo", h + " .cname"], c.t + 0.12);
    gIn(h + " .mini", c.t + 0.12, { scale: 0.8, y: 0 }, 0.07);
    draw(h + " .ln", c.t_lines, 0.6);
    tl.fromTo(h + " .mbadge", { opacity: 0, y: -12 }, { opacity: 1, y: 0, duration: 0.35, ease: OUT }, c.t_lines);
    if (c.t_spin) tl.fromTo(h + " .ctile .logo", { rotate: 0 }, { rotate: 90, duration: 0.8, ease: "power2.inOut" }, c.t_spin);
    fadeOut(h + " .lines", c.out);
    gOut(h + " .g", c.out, 0.03);
  },
  chat: function (id, c) {
    var h = "#" + id;
    gIn(h + " .chat", c.t);
    cIn(h + " .chead > *", c.t + 0.1, 0.06);
    tl.fromTo(h + " .ubub", { opacity: 0, scale: 0.9 }, { opacity: 1, scale: 1, duration: 0.3, ease: OUT, transformOrigin: "right center" }, c.t_type);
    var ch = $all(h + " .ubub .ch"), step = (c.t_type_end - c.t_type) / Math.max(ch.length, 1);
    ch.forEach(function (e, i) { tl.set(e, { display: "inline" }, c.t_type + 0.02 + i * step); });
    tl.fromTo(h + " .dots", { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.3, ease: OUT }, c.t_dots);
    $all(h + " .dots i").forEach(function (d, i) {
      tl.fromTo(d, { y: 0 }, { y: -6, duration: 0.16, ease: "sine.out", yoyo: true, repeat: 1 }, c.t_dots + 0.05 + i * 0.1);
    });
    tl.to(h + " .dots", { opacity: 0, duration: 0.15 }, c.t_result - 0.07);
    tl.fromTo(h + " .pull", { opacity: 0 }, { opacity: 1, duration: 0.25 }, c.t_result);
    cIn([h + " .pull > span:first-child", h + " .pull .pl"], c.t_result, 0.06);
    gOut(h + " .chat", c.out);
  },
  text: function (id, c) {
    var h = "#" + id, box = h + " .tbox", anim = c.anim || "words";
    if (anim === "pop") gPop(box, c.t); else gIn(box, c.t);
    cIn(exists([h + " .kick"]), c.t + 0.1);
    cIn(h + " .tw", c.t + (anim === "pop" ? 0.15 : 0.12), anim === "words" ? 0.08 : 0);
    if (c.out < window.__DUR - 0.05) gOut(box, c.out);
  },
  task: function (id, c) {
    var h = "#" + id;
    gIn(h + " .hug", c.t);
    popIn(h + " .itile", c.t + 0.1);
    cIn([h + " .kick", h + " .stitle", h + " .ssub2", h + " .tog"], c.t + 0.15);
    if (c.t_toggle) {
      tl.to(h + " .tog i", { x: 38, duration: 0.3, ease: "power2.inOut" }, c.t_toggle);
      tl.to(h + " .tog", { "--on": 1, duration: 0.3, ease: "power2.inOut" }, c.t_toggle);
    }
    if (c.out < window.__DUR - 0.05) gOut(h + " .hug", c.out);
  }
};

// end screen: gradient fades up over the last frame, lines rise in order, the bold offer lands, then the logo
function endcard(t) {
  tl.fromTo("#end", { opacity: 0 }, { opacity: 1, duration: 0.45, ease: "power2.out" }, t - 0.45);
  tl.fromTo("#end", { "--bgz": 1.08 }, { "--bgz": 1, duration: 3.8, ease: "power2.out" }, t - 0.45);
  tl.fromTo("#end .er", { opacity: 0, y: 20, filter: "blur(10px)" }, { opacity: 0.95, y: 0, filter: "blur(0px)", duration: 0.45, ease: OUT, stagger: 0.12 }, t + 0.05);
  var n = document.querySelectorAll("#end .er").length;
  tl.fromTo("#end .eb", { opacity: 0, y: 30, scale: 0.94, filter: "blur(14px)" },
    { opacity: 1, y: 0, scale: 1, filter: "blur(0px)", duration: 0.55, ease: OUT, stagger: 0.13 }, t + 0.15 + n * 0.12);
  tl.fromTo("#end .elogo", { opacity: 0, y: 16, filter: "blur(10px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.5, ease: OUT },
    t + 0.55 + n * 0.12 + document.querySelectorAll("#end .eb").length * 0.13);
}

// effects on the a-roll, on top of the base edit's own zooms:
//   punch: quick scale-in on a word, eases back out before `until`; push: slow drift in from t to until;
//   flash: a white flash that fades in 0.35 s (a cut or a turn in the argument)
function fx(f) {
  var o = { transformOrigin: "50% 32%" };
  if (f.kind === "punch") {
    tl.fromTo("#a-roll", Object.assign({ scale: 1 }, o), { scale: f.to || 1.15, duration: 0.14, ease: "power3.out", immediateRender: false }, f.t);
    tl.to("#a-roll", { scale: 1, duration: 0.35, ease: "power3.inOut" }, f.until - 0.35);
  } else if (f.kind === "push") {
    tl.fromTo("#a-roll", Object.assign({ scale: 1 }, o), { scale: f.to || 1.08, duration: f.until - f.t, ease: "sine.inOut", immediateRender: false }, f.t);
    tl.set("#a-roll", { scale: 1 }, f.until);
  } else if (f.kind === "flash") {
    tl.fromTo("#flash", { opacity: f.strength || 0.85 }, { opacity: 0, duration: 0.35, ease: "power2.out", immediateRender: false }, f.t);
  }
}

// ---------------- takeovers: gradient cutaways ----------------
// full: the gradient wipes in as a circle while the footage pushes in, then wipes up and away.
// pip:  the footage shrinks into a rounded window over the gradient, then grows back to full frame.
var PIP = { left: 150, top: 110, width: 780, height: 720, borderRadius: 48 };
function takeover(id, k) {
  var h = "#" + id, bg = h + "-bg", t = k.t, out = k.out, pip = k.mode === "pip";
  var FULL = { left: 0, top: 0, width: window.__LAYOUT.w, height: window.__LAYOUT.h, borderRadius: 0 };
  tl.fromTo(bg + " .b1", { x: -60, y: 0 }, { x: 140, y: 120, duration: out - t, ease: "sine.inOut" }, t);   // the background drifts
  tl.fromTo(bg + " .b2", { x: 80, y: 0 }, { x: -160, y: -140, duration: out - t, ease: "sine.inOut" }, t);
  tl.fromTo(bg + " .b3", { x: 0, scale: 0.8 }, { x: -120, scale: 1.2, duration: out - t, ease: "sine.inOut" }, t);
  tl.fromTo(bg, { "--bgz": 1.14 }, { "--bgz": 1.02, duration: out - t, ease: "power2.out" }, t);
  var c0 = t + 0.3;
  if (pip) {
    tl.fromTo(bg, { opacity: 0 }, { opacity: 1, duration: 0.15 }, t);
    tl.fromTo("#a-roll", FULL, Object.assign({ duration: 0.7, ease: "expo.inOut" }, PIP), t);
    tl.fromTo(h + "-frame", { opacity: 0, scale: 1.04 }, { opacity: 1, scale: 1, duration: 0.35, ease: OUT }, t + 0.55);
    c0 = t + 0.55;
  } else {
    tl.fromTo(bg, { clipPath: "circle(0% at 50% 40%)" }, { clipPath: "circle(120% at 50% 40%)", duration: 0.6, ease: "expo.inOut" }, t);
    tl.fromTo("#a-roll", { scale: 1 }, { scale: 1.25, duration: 0.6, ease: "expo.in", immediateRender: false }, t);
    tl.set("#a-roll", { scale: 1 }, t + 0.62);
  }
  tl.fromTo(h + " .tkkick", { opacity: 0, y: -20, scale: 0.9 }, { opacity: 1, y: 0, scale: 1, duration: 0.45, ease: "back.out(1.8)" }, c0);
  tl.fromTo(h + " .tw", { opacity: 0, y: 60, rotate: 4, filter: "blur(12px)" },
    { opacity: 1, y: 0, rotate: 0, filter: "blur(0px)", duration: 0.55, ease: "back.out(1.6)", stagger: 0.09 }, k.t_title || c0 + 0.12);
  if (k.stat) {
    var st = k.stat, ts = st.t || c0 + 0.15;
    tl.fromTo(h + " .tkval", { opacity: 0, scale: 0.4, filter: "blur(20px)" },
      { opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.6, ease: "back.out(1.5)" }, ts);
    if (st.count) {  // counts up to the number, seek-safe (text is set from the tween's progress)
      var el = document.querySelector(h + " .tkval"), o = { v: 0 };
      tl.fromTo(o, { v: 0 }, { v: st.count, duration: st.count_dur || 0.9, ease: "power2.out",
        onUpdate: function () { el.textContent = (st.prefix || "") + Math.round(o.v) + (st.suffix || ""); } }, ts);
    }
    if (st.bar) {
      tl.fromTo(h + " .tkbar", { opacity: 0 }, { opacity: 1, duration: 0.3 }, ts + 0.1);
      tl.fromTo(h + " .tkbar i", { scaleX: 0 }, { scaleX: st.bar, duration: st.count_dur || 0.9, ease: "power2.out" }, ts + 0.1);
    }
    tl.fromTo(h + " .tklabel", { opacity: 0, y: 30, filter: "blur(10px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.45, ease: OUT }, st.t_label || ts + 0.4);
  }
  (k.items || []).forEach(function (it, i) {  // rows swing in from alternating sides on their words
    var r = h + "-r" + i;
    tl.fromTo(r, { opacity: 0, x: i % 2 ? 80 : -80, scale: 0.9 }, { opacity: 1, x: 0, scale: 1, duration: 0.55, ease: "back.out(1.6)" }, it.t);
    tl.fromTo(r, { "--gl": 1 }, { "--gl": 0, duration: 1.1, ease: "power2.out" }, it.t + 0.15);
    tl.fromTo(r + " .tkb", { scale: 0, rotate: -90 }, { scale: 1, rotate: 0, duration: 0.5, ease: "back.out(2)" }, it.t + 0.1);
  });
  if (k.last) return;  // runs into the end screen
  tl.to(h + " .tkbody", { opacity: 0, y: -40, duration: 0.3, ease: "power2.in" }, out - 0.45);
  if (pip) {
    tl.to(h + "-frame", { opacity: 0, duration: 0.15 }, out - 0.55);
    tl.fromTo("#a-roll", PIP, Object.assign({ duration: 0.55, ease: "expo.inOut", immediateRender: false }, FULL), out - 0.55);
  } else {
    tl.to(bg, { clipPath: "inset(0% 0% 100% 0%)", duration: 0.45, ease: "expo.inOut" }, out - 0.45);
    tl.fromTo("#a-roll", { scale: 1.2 }, { scale: 1, duration: 0.6, ease: "expo.out", immediateRender: false }, out - 0.4);
  }
}

// blur / box regions that follow movement: glide between the key points (dt from the region's start)
function redact(id, r) {
  // the box is placed at its first point (left/top); it moves by transform so it glides smoothly in the render
  var k = r.keys, x0 = k[0].x, y0 = k[0].y;
  for (var i = 1; i < k.length; i++) {
    tl.fromTo("#" + id, { x: k[i - 1].x - x0, y: k[i - 1].y - y0 }, { x: k[i].x - x0, y: k[i].y - y0, duration: Math.max(0.04, k[i].dt - k[i - 1].dt),
      ease: "none", immediateRender: false }, r.t + k[i - 1].dt);
  }
}

// overlay videos fade in and out (opacity); the clip's own sound fades via data-fade-in / data-fade-out
function ovfade(id, o) {
  var sel = "#" + id, f = Math.min(o.fade || 0, o.dur / 2);
  if (!f) return;
  tl.fromTo(sel, { opacity: 0 }, { opacity: o.opacity, duration: f, ease: "power1.out", immediateRender: false }, o.t);
  tl.to(sel, { opacity: 0, duration: f, ease: "power1.in" }, o.t + o.dur - f);
}
