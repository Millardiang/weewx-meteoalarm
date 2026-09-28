/* Area picker for the weewx-meteoalarm_warnings WeeWX extension.
 *
 * The page is the same for everyone. The installer opens it with the station and
 * the current choice in the URL fragment, which browsers never send to the server:
 *   map/#lat=51.48&lon=-0.01&areas=UK258,UK271&level=2&poly=51.3,-0.5;51.7,-0.5;51.7,0.2
 * The fragment is kept up to date as you choose, so reloading keeps your choice. */
(function () {
  "use strict";

  var AREAS_URL = "../areas/";
  var MIN_AREA_ZOOM = 5;
  var HIGHLIGHT_BORDERS = ["UK"];   // countries whose area borders are drawn bolder (UK counties)
  var cfg = readFragment();

  function readFragment() {
    var q = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    var lat = parseFloat(q.get("lat")), lon = parseFloat(q.get("lon"));
    return {
      emma_ids: (q.get("areas") || "").split(",").map(function (c) { return c.trim(); }).filter(function (c) {
        return /^[A-Za-z]{2}[0-9]{3,4}$/.test(c);
      }),
      polygon: (q.get("poly") || "").split(";").join(" "),
      min_level: q.get("level"),
      station: isFinite(lat) && isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lat, lon] : null
    };
  }

  function writeFragment(sel) {
    var parts = [];
    if (station) { parts.push("lat=" + station[0], "lon=" + station[1]); }
    if (sel.length) { parts.push("areas=" + sel.join(",")); }
    parts.push("level=" + state.minLevel);
    if (state.polygon.length) {
      parts.push("poly=" + state.polygon.map(function (p) { return p[1].toFixed(4) + "," + p[0].toFixed(4); }).join(";"));
    }
    var hash = "#" + parts.join("&");
    if (window.location.hash !== hash && window.history && window.history.replaceState) {
      window.history.replaceState(null, "", hash);
    }
  }

  var state = {
    mode: "pick",
    selected: new Set((cfg.emma_ids || []).map(function (c) { return String(c).toUpperCase(); })),
    polygon: parseCap(cfg.polygon || ""),      // [[lon, lat], ...] or []
    drawing: [],                               // corners while drawing
    touched: new Set(),                        // codes the polygon touches
    minLevel: Math.min(4, Math.max(1, Number(cfg.min_level) || 2))
  };
  var index = {};          // code -> [name, country, bbox|null]
  var countryBox = {};     // country -> [minlon, minlat, maxlon, maxlat]
  var loaded = {};         // country -> Promise<L.GeoJSON>
  var layers = {};         // code -> leaflet layer

  var $ = function (id) { return document.getElementById(id); };

  // ------------------------------------------------------------------ map
  var map = L.map("mp-map", { preferCanvas: true, doubleClickZoom: true }).setView([51, 10], 4);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 12,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);
  var polyLayer = L.polygon([], { color: "#c2410c", weight: 2, dashArray: "6 4", fillOpacity: 0.08, interactive: false }).addTo(map);
  var drawLine = L.polyline([], { color: "#c2410c", weight: 2, dashArray: "4 4", interactive: false }).addTo(map);
  var cornerLayer = L.layerGroup().addTo(map);

  // the weather station, from [Station] latitude/longitude in weewx.conf
  var station = null;
  if (cfg.station && (cfg.station[0] || cfg.station[1])) {
    station = [Number(cfg.station[0]), Number(cfg.station[1])];
    L.circleMarker(station, { radius: 6, color: "#111", weight: 2, fillColor: "#fff", fillOpacity: 1 })
      .bindTooltip("Your weather station", { permanent: false }).addTo(map);
  }

  function style(feature) {
    var code = feature.properties.code;
    if (state.selected.has(code)) {
      return { color: "#0b5cad", weight: 2, fillColor: "#0b5cad", fillOpacity: 0.45 };
    }
    if (state.touched.has(code)) {
      return { color: "#c46a00", weight: 1.5, fillColor: "#ff9500", fillOpacity: 0.35 };
    }
    if (HIGHLIGHT_BORDERS.indexOf(code.slice(0, 2)) >= 0) {
      return { color: "#1d2330", weight: 1.6, opacity: 0.85, fillColor: "#3b82f6", fillOpacity: 0.04 };
    }
    return { color: "#5d6675", weight: 0.6, fillColor: "#3b82f6", fillOpacity: 0.04 };
  }

  function restyle() {
    Object.keys(layers).forEach(function (code) { layers[code].setStyle(style(layers[code].feature)); });
  }

  function loadCountry(country) {
    if (!loaded[country]) {
      loaded[country] = fetch(AREAS_URL + country + ".geojson")
        .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); })
        .then(function (data) {
          return L.geoJSON(data, {
            style: style,
            onEachFeature: function (feature, layer) {
              var p = feature.properties;
              layers[p.code] = layer;
              layer.bindTooltip("<strong>" + esc(p.code) + "</strong> " + esc(p.name), { sticky: true, className: "mp-tip" });
              layer.on("click", function (e) {
                if (state.mode === "pick") { toggle(p.code); L.DomEvent.stop(e); }
              });
            }
          }).addTo(map);
        })
        .catch(function () { delete loaded[country]; return null; });
    }
    return loaded[country];
  }

  function countriesIn(box) {
    return Object.keys(countryBox).filter(function (c) { return overlap(countryBox[c], box); });
  }

  function loadVisible() {
    var zoomedIn = map.getZoom() >= MIN_AREA_ZOOM;
    $("mp-hint").hidden = zoomedIn;
    if (!zoomedIn) { return; }
    var b = map.getBounds();
    countriesIn([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]).forEach(loadCountry);
  }
  map.on("moveend", loadVisible);

  // ------------------------------------------------------------------ geometry ([lon, lat])
  function bbox(ring) {
    var b = [Infinity, Infinity, -Infinity, -Infinity];
    ring.forEach(function (p) {
      b[0] = Math.min(b[0], p[0]); b[1] = Math.min(b[1], p[1]);
      b[2] = Math.max(b[2], p[0]); b[3] = Math.max(b[3], p[1]);
    });
    return b;
  }
  function overlap(a, b) { return a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3]; }
  function inRing(pt, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi) { inside = !inside; }
    }
    return inside;
  }
  function orient(a, b, c) { return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]); }
  function cross(p1, p2, q1, q2) {
    return (orient(q1, q2, p1) > 0) !== (orient(q1, q2, p2) > 0) && (orient(p1, p2, q1) > 0) !== (orient(p1, p2, q2) > 0);
  }
  function ringsIntersect(a, b) {
    if (!overlap(bbox(a), bbox(b))) { return false; }
    if (inRing(a[0], b) || inRing(b[0], a)) { return true; }
    for (var i = 0; i < a.length; i++) {
      var p1 = a[i === 0 ? a.length - 1 : i - 1], p2 = a[i];
      for (var j = 0; j < b.length; j++) {
        if (cross(p1, p2, b[j === 0 ? b.length - 1 : j - 1], b[j])) { return true; }
      }
    }
    return false;
  }
  function outerRings(geom) {
    if (geom.type === "Polygon") { return [geom.coordinates[0]]; }
    if (geom.type === "MultiPolygon") { return geom.coordinates.map(function (p) { return p[0]; }); }
    return [];
  }

  function parseCap(text) {
    var pts = String(text).trim().split(/\s+/).map(function (pair) {
      var v = pair.split(",").map(Number);
      return v.length === 2 && isFinite(v[0]) && isFinite(v[1]) ? [v[1], v[0]] : null;
    }).filter(Boolean);
    if (pts.length > 1 && pts[0][0] === pts[pts.length - 1][0] && pts[0][1] === pts[pts.length - 1][1]) { pts.pop(); }
    return pts.length >= 3 ? pts : [];
  }
  function toCap(pts) {
    return pts.concat([pts[0]]).map(function (p) { return p[1].toFixed(4) + "," + p[0].toFixed(4); }).join(" ");
  }

  function computeTouched() {
    state.touched = new Set();
    var poly = state.polygon;
    if (!poly.length) { restyle(); render(); return Promise.resolve(); }
    var box = bbox(poly);
    return Promise.all(countriesIn(box).map(loadCountry)).then(function () {
      Object.keys(index).forEach(function (code) {
        var b = index[code][2], layer = layers[code];
        if (b && layer && overlap(box, b) && outerRings(layer.feature.geometry).some(function (r) { return ringsIntersect(poly, r); })) {
          state.touched.add(code);
        }
      });
      restyle();
      render();
    });
  }

  // ------------------------------------------------------------------ selection
  function toggle(code) {
    if (state.selected.has(code)) { state.selected.delete(code); } else { state.selected.add(code); }
    restyle();
    render();
  }

  function zoomTo(code) {
    var e = index[code];
    if (!e || !e[2]) { return; }
    loadCountry(e[1]);
    map.fitBounds([[e[2][1], e[2][0]], [e[2][3], e[2][2]]], { maxZoom: 9, padding: [20, 20] });
  }

  function chip(code, removable) {
    var e = index[code] || [code, code.slice(0, 2), null];
    var li = document.createElement("li");
    var name = document.createElement("span");
    name.className = "mp-name";
    name.innerHTML = esc(e[0]) + " <code>" + esc(code) + "</code>" + (e[2] ? "" : ' <span class="mp-flag">no outline</span>');
    name.title = e[2] ? "Show on map" : "No outline available for this area";
    name.addEventListener("click", function () { zoomTo(code); });
    li.appendChild(name);
    if (removable) {
      var x = document.createElement("button");
      x.type = "button";
      x.setAttribute("aria-label", "Remove " + e[0]);
      x.textContent = "×";
      x.addEventListener("click", function () { toggle(code); });
      li.appendChild(x);
    }
    return li;
  }

  function render() {
    var sel = Array.from(state.selected).sort();
    var ul = $("mp-selected");
    ul.replaceChildren.apply(ul, sel.map(function (c) { return chip(c, true); }));
    $("mp-none").hidden = sel.length > 0 || state.polygon.length > 0;
    $("mp-count").textContent = sel.length ? "(" + sel.length + ")" : "";

    var touched = Array.from(state.touched).filter(function (c) { return !state.selected.has(c); }).sort();
    $("mp-poly-box").hidden = !state.polygon.length;
    $("mp-poly-count").textContent = touched.length;
    var pl = $("mp-poly-list");
    pl.replaceChildren.apply(pl, touched.map(function (c) { return chip(c, false); }));

    polyLayer.setLatLngs(state.polygon.map(function (p) { return [p[1], p[0]]; }));
    $("mp-clear-poly").disabled = !state.polygon.length && !state.drawing.length;
    $("mp-level").value = String(state.minLevel);

    var lines = ["[Meteoalarm]", "    emma_ids = " + (sel.length ? sel.join(", ") : '""')];
    lines.push("    polygon = " + (state.polygon.length ? '"' + toCap(state.polygon) + '"' : '""'));
    lines.push("    min_level = " + state.minLevel);
    $("mp-output").textContent = lines.join("\n");
    writeFragment(sel);
    // setup code for the installer: MA1:<codes>:<min level>:<lat,lon;lat,lon;...>
    var empty = !sel.length && !state.polygon.length;
    var poly = state.polygon.map(function (p) { return p[1].toFixed(4) + "," + p[0].toFixed(4); }).join(";");
    $("mp-code").textContent = empty ? "Choose an area or draw a polygon first."
      : "MA1:" + sel.join(",") + ":" + state.minLevel + ":" + poly;
    $("mp-code").classList.toggle("mp-muted", empty);
    $("mp-copy-code").disabled = empty;
    $("mp-copy-code-msg").textContent = "";
  }

  // ------------------------------------------------------------------ drawing
  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll(".mp-modes button").forEach(function (b) {
      var on = b.getAttribute("data-mode") === mode;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll("[data-help]").forEach(function (p) { p.hidden = p.getAttribute("data-help") !== mode; });
    document.querySelector(".mp-draw-tools").hidden = mode !== "draw";
    map.getContainer().classList.toggle("mp-drawing", mode === "draw");
    if (mode === "draw") { map.doubleClickZoom.disable(); } else { map.doubleClickZoom.enable(); cancelDrawing(); }
  }

  function redrawCorners() {
    cornerLayer.clearLayers();
    drawLine.setLatLngs(state.drawing.map(function (p) { return [p[1], p[0]]; }));
    state.drawing.forEach(function (p, i) {
      var m = L.circleMarker([p[1], p[0]], {
        radius: i === 0 ? 7 : 5, color: "#c2410c", weight: 2, fillColor: "#fff", fillOpacity: 1
      }).addTo(cornerLayer);
      if (i === 0) {
        m.bindTooltip("Click to finish");
        m.on("click", function (e) { L.DomEvent.stop(e); finish(); });
      }
    });
    $("mp-finish").disabled = state.drawing.length < 3;
    $("mp-undo").disabled = !state.drawing.length;
    $("mp-clear-poly").disabled = !state.polygon.length && !state.drawing.length;
  }

  function cancelDrawing() { state.drawing = []; redrawCorners(); }

  function finish() {
    if (state.drawing.length < 3) { return; }
    state.polygon = state.drawing.slice();
    cancelDrawing();
    computeTouched();
  }

  map.on("click", function (e) {
    if (state.mode !== "draw") { return; }
    if (!state.drawing.length) { state.polygon = []; state.touched = new Set(); restyle(); render(); }
    state.drawing.push([e.latlng.lng, e.latlng.lat]);
    redrawCorners();
  });
  map.on("dblclick", function () { if (state.mode === "draw") { finish(); } });

  // ------------------------------------------------------------------ controls
  document.querySelectorAll(".mp-modes button").forEach(function (b) {
    b.addEventListener("click", function () { setMode(b.getAttribute("data-mode")); });
  });
  $("mp-finish").addEventListener("click", finish);
  $("mp-undo").addEventListener("click", function () { state.drawing.pop(); redrawCorners(); });
  $("mp-clear-poly").addEventListener("click", function () {
    state.polygon = []; state.touched = new Set(); cancelDrawing(); restyle(); render();
  });
  $("mp-level").addEventListener("change", function (e) { state.minLevel = Number(e.target.value); render(); });
  // navigator.clipboard only exists on https:// and localhost; fall back to a hidden textarea
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      if (ok) { resolve(); } else { reject(); }
    });
  }
  function selectText(el) {
    var r = document.createRange();
    r.selectNodeContents(el);
    var s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  }
  $("mp-copy-code").addEventListener("click", function () {
    copyText($("mp-code").textContent).then(function () {
      $("mp-copy-code-msg").textContent = "Copied. Now paste it into the terminal.";
    }, function () {
      selectText($("mp-code"));
      $("mp-copy-code-msg").textContent = "Selected; press Ctrl+C (Cmd+C on a Mac) to copy.";
    });
  });
  $("mp-copy").addEventListener("click", function () {
    var btn = $("mp-copy");
    copyText($("mp-output").textContent).then(function () {
      btn.textContent = "Copied";
      setTimeout(function () { btn.textContent = "Copy settings"; }, 1500);
    }, function () { selectText($("mp-output")); btn.textContent = "Selected; press Ctrl+C"; });
  });
  $("mp-locate").addEventListener("click", function () {
    if (!navigator.geolocation) { return; }
    navigator.geolocation.getCurrentPosition(function (pos) {
      map.setView([pos.coords.latitude, pos.coords.longitude], 8);
    });
  });
  function pickFromSearch() {
    var code = $("mp-search").value.trim().split(/\s/)[0].toUpperCase();
    if (!index[code]) { return; }
    state.selected.add(code);
    $("mp-search").value = "";
    zoomTo(code);
    restyle();
    render();
  }
  $("mp-search").addEventListener("change", pickFromSearch);
  $("mp-search").addEventListener("keydown", function (e) { if (e.key === "Enter") { pickFromSearch(); } });

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ------------------------------------------------------------------ start
  fetch(AREAS_URL + "index.json")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      index = data;
      var opts = document.createDocumentFragment();
      Object.keys(index).sort().forEach(function (code) {
        var e = index[code];
        if (e[2]) {
          var cb = countryBox[e[1]] || [Infinity, Infinity, -Infinity, -Infinity];
          countryBox[e[1]] = [Math.min(cb[0], e[2][0]), Math.min(cb[1], e[2][1]), Math.max(cb[2], e[2][2]), Math.max(cb[3], e[2][3])];
        }
        var o = document.createElement("option");
        o.value = code + " " + e[0];
        opts.appendChild(o);
      });
      $("mp-codes").appendChild(opts);

      // open on the current selection
      var boxes = [];
      state.selected.forEach(function (c) { if (index[c] && index[c][2]) { boxes.push(index[c][2]); loadCountry(index[c][1]); } });
      if (state.polygon.length) { boxes.push(bbox(state.polygon)); }
      if (boxes.length) {
        var b = boxes.reduce(function (a, x) { return [Math.min(a[0], x[0]), Math.min(a[1], x[1]), Math.max(a[2], x[2]), Math.max(a[3], x[3])]; });
        map.fitBounds([[b[1], b[0]], [b[3], b[2]]], { maxZoom: 9, padding: [30, 30] });
      } else if (station) {
        map.setView(station, 8);   // nothing chosen yet: start at the weather station
      }
      render();
      loadVisible();
      computeTouched();
    })
    .catch(function (err) {
      $("mp-none").textContent = "Could not load the area list (" + err.message + "). Check your internet connection and reload.";
    });
})();
