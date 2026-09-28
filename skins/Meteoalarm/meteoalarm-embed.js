/*
 * meteoalarm-embed.js - show the Meteoalarm skin's warning box on any page.
 *
 *   <div data-meteoalarm-src="meteoalarm/summary.html"></div>
 *   <script src="meteoalarm/meteoalarm-embed.js" defer></script>
 *
 * The fragment must come from the same site as the page. Its relative links
 * (icons, details page) are rewritten to point next to the fragment, so it
 * works from any folder. The box refreshes itself every 5 minutes.
 */
(function () {
  "use strict";
  var REFRESH_MS = 5 * 60 * 1000;

  function load(el) {
    var src = el.getAttribute("data-meteoalarm-src");
    var base = new URL(src, document.baseURI);
    var url = new URL(base.href);
    url.searchParams.set("t", Math.floor(Date.now() / 60000));   // skip stale caches
    fetch(url.href, { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) { throw new Error(r.status + " " + r.statusText); }
        return r.text();
      })
      .then(function (html) {
        var tpl = document.createElement("template");
        tpl.innerHTML = html;
        tpl.content.querySelectorAll("[src],[href]").forEach(function (node) {
          ["src", "href"].forEach(function (attr) {
            var v = node.getAttribute(attr);
            if (v && v.charAt(0) !== "#") { node.setAttribute(attr, new URL(v, base).href); }
          });
        });
        el.replaceChildren(tpl.content);
      })
      .catch(function (err) {
        if (!el.childNodes.length) { el.textContent = "Weather warnings are unavailable right now."; }
        if (window.console) { console.warn("meteoalarm: could not load " + src + ": " + err.message); }
      });
  }

  function init() {
    var boxes = document.querySelectorAll("[data-meteoalarm-src]");
    boxes.forEach(load);
    if (boxes.length) {
      setInterval(function () { boxes.forEach(load); }, REFRESH_MS);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
