// Builds the long-form graphics as DOM from longform.json items. Shared by the editor preview and the render compositions.
"use strict";
(function (root) {
  const h = (tag, cls, ...kids) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    kids.flat().forEach((k) => { if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k))); });
    return e;
  };
  const OV = {
    // a free position in 1920x1080 frame pixels (top-left corner); without x and y the preset side is used
    place(e, x) {
      if (typeof x.x === "number" && typeof x.y === "number") {
        e.style.left = `${x.x / 19.2}cqw`; e.style.top = `${x.y / 19.2}cqw`; e.style.right = "auto"; e.style.bottom = "auto"; e.style.marginLeft = "0";
      } else ["left", "top", "right", "bottom", "marginLeft"].forEach((k) => (e.style[k] = ""));
      return e;
    },
    ANIMS: ["slide", "fade", "pop", "none"],
    lowerThird(x) {
      return OV.place(h("div", `ov-lt pos-${x.pos === "right" ? "right" : "left"} a-${x.anim || "slide"}`, h("b", "", x.title || ""), x.sub ? h("span", "", x.sub) : null), x);
    },
    card(x) {
      const pos = ["left", "center", "right"].includes(x.pos) ? x.pos : "right";
      const body = x.type === "stat" ? [h("b", "big", x.value || ""), h("span", "", x.label || "")]
        : x.type === "list" ? [h("div", "bar"), h("b", "", x.title || ""), h("ul", "", (x.items || []).map((i) => h("li", "", i)))]
        : [h("div", "bar"), h("b", "", x.title || ""), x.body ? h("span", "", x.body) : null];
      return OV.place(h("div", `ov-card pos-${pos} a-${x.anim || "fade"}`, body), x);
    },
    // the end screen (rendered after the video): lines [{text, bold}], optional logo URL
    endcard(x) {
      const e = h("div", "ov-end a-fade", x.logo ? h("img", "logo") : null, h("div", "lines", (x.lines || []).map((l) => h("span", l.bold ? "bold" : "", l.text))));
      if (x.logo) e.querySelector("img").src = x.logo;
      return e;
    },
    // a group of up to 4 words with word i highlighted; opts {size, bottom} in cqw / percent of the frame width
    caption(words, i, opts) {
      const o = Object.assign({ size: 3.3, bottom: 6 }, opts || {});
      const g = i - (i % 4);
      const e = h("div", "ov-cap");
      e.style.fontSize = `${o.size}cqw`; e.style.bottom = `${o.bottom}%`;
      words.slice(g, g + 4).forEach((w, j) => e.append(h("span", g + j === i ? "on" : g + j < i ? "past" : "", w.text + " ")));
      return e;
    },
  };
  root.OV = OV;
})(window);
