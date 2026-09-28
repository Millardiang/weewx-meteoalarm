#
#    Copyright (c) 2026 Ian Millard
#
#    Weather warnings from www.meteoalarm.org for WeeWX.
#
#    Inspired by get-meteoalarm-warning-inc.php by Ken True (saratoga-weather.org),
#    adapted with permission from wrnWarningEU-CAP.php by Wim van der Kuil
#    (pwsdashboard.com).
#
#    Released under the GNU General Public License v3; see LICENSE.
#
"""MeteoAlarm weather warnings for WeeWX.

Adds the search-list tag $meteoalarm to Cheetah templates. It fetches the
MeteoAlarm feed for each country you watch (cached, so at most once every
cache_max_age seconds), keeps the warnings that cover your areas, and hands
them to the templates.

Areas are chosen in weewx.conf, most easily with the map page this
extension's skin generates:

[Meteoalarm]
    # EMMA_IDs to watch, comma separated
    emma_ids = DK002, DK004
    # and/or a polygon, as CAP-style "lat,lon lat,lon ..." pairs; areas it
    # touches are added, and alerts drawn as polygons/circles that cross it match
    polygon = ""
    min_level = 2          # 1 green, 2 yellow, 3 orange, 4 red
    cache_max_age = 300    # seconds
    timeout = 30           # seconds per feed download
    date_format = %Y-%m-%d
    time_format = %H:%M

Can also be run directly to test a configuration:

    python3 meteoalarm.py --emma-ids UK258 [--polygon "..."] [--test-file feed.json]
"""

import html
import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    from weewx.cheetahgenerator import SearchList
except ImportError:  # running standalone
    class SearchList:
        def __init__(self, generator):
            self.generator = generator

log = logging.getLogger(__name__)

VERSION = "1.0.0"
FEED_URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-{slug}"
USER_AGENT = "weewx-meteoalarm/%s" % VERSION

# area-code prefix -> feed name
FEEDS = {
    "AT": "austria", "BA": "bosnia-herzegovina", "BE": "belgium", "BG": "bulgaria",
    "CH": "switzerland", "CY": "cyprus", "CZ": "czechia", "DE": "germany",
    "DK": "denmark", "EE": "estonia", "EI": "ireland", "ES": "spain", "FI": "finland",
    "FR": "france", "GR": "greece", "HR": "croatia", "HU": "hungary",
    "IE": "ireland", "IL": "israel", "IS": "iceland", "IT": "italy",
    "LT": "lithuania", "LU": "luxembourg", "LV": "latvia", "MD": "moldova",
    "ME": "montenegro", "MK": "republic-of-north-macedonia", "MT": "malta",
    "NL": "netherlands", "NO": "norway", "PL": "poland", "PT": "portugal",
    "RO": "romania", "RS": "serbia", "SE": "sweden", "SI": "slovenia",
    "SK": "slovakia", "UK": "united-kingdom",
}

# rough extents of countries whose areas have no shapes yet (lon/lat box)
NO_SHAPE_BOXES = {"CH": (5.9, 45.8, 10.5, 47.8)}

LEVEL_COLORS = {1: "#29d660", 2: "#FFDB23", 3: "#FF9500", 4: "#FF0100"}
LEVEL_NAMES = {1: "Green", 2: "Yellow", 3: "Orange", 4: "Red"}
SEVERITY = {1: "Minor", 2: "Moderate", 3: "Severe", 4: "Extreme"}
LEVEL_ADVICE = {
    2: "The weather is potentially dangerous. Be attentive if you practise activities exposed to "
       "meteorological risks and keep informed about the expected conditions.",
    3: "The weather is dangerous. Damage and casualties are likely. Be very vigilant, keep regularly "
       "informed and follow any advice given by your authorities.",
    4: "The weather is very dangerous. Major damage and threat to life are likely over a wide area. "
       "Follow orders and advice from your authorities under all circumstances.",
}
COLOR_WORDS = ("Green", "Yellow", "Orange", "Red", "Amber", "Moderate", "Severe", "Extreme")
ICONS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13}   # icons/meteoalarm_N.svg that exist

LANG_NAMES = {
    "bg": "Български", "ca": "Català", "cs": "Čeština", "cy": "Cymraeg", "da": "Dansk",
    "de": "Deutsch", "el": "Ελληνικά", "en": "English", "es": "Español", "et": "Eesti",
    "fi": "Suomi", "fr": "Français", "ga": "Gaeilge", "he": "עברית", "hr": "Hrvatski",
    "hu": "Magyar", "is": "Íslenska", "it": "Italiano", "lb": "Lëtzebuergesch",
    "lt": "Lietuvių", "lv": "Latviešu", "mk": "Македонски", "mt": "Malti", "nl": "Nederlands",
    "no": "Norsk", "nb": "Norsk", "nn": "Nynorsk", "pl": "Polski", "pt": "Português",
    "ro": "Română", "ru": "Русский", "sk": "Slovenčina", "sl": "Slovenščina", "sr": "Srpski",
    "sv": "Svenska", "uk": "Українська",
}


# ----------------------------------------------------------------------------- config

def to_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        value = ",".join(value)
    return [v.strip().upper() for v in str(value).split(",") if v.strip()]


class Options:
    """Settings from [Meteoalarm] in weewx.conf, overridable per skin."""

    def __init__(self, conf, weewx_root=".", skin_root="skins", sqlite_root="archive", station=None):
        conf = dict(conf or {})
        self.station = station_position(station)
        self.emma_ids = to_list(conf.get("emma_ids"))
        polygon = conf.get("polygon") or ""
        if isinstance(polygon, (list, tuple)):
            # an unquoted "lat,lon lat,lon" line in weewx.conf is split at the commas; rejoin it
            polygon = ",".join(polygon)
        self.polygon_text = " ".join(str(polygon).split())
        self.polygon = parse_cap_polygon(self.polygon_text) if self.polygon_text else []
        try:
            self.min_level = min(4, max(1, int(conf.get("min_level", 2))))
        except ValueError:
            self.min_level = 2
        self.cache_max_age = int(conf.get("cache_max_age", 300))
        self.timeout = int(conf.get("timeout", 30))
        self.date_format = conf.get("date_format", "%Y-%m-%d")
        self.time_format = conf.get("time_format", "%H:%M")
        self.test_file = conf.get("test_file")
        self.areas_dir = conf.get("areas_dir") or os.path.join(weewx_root, skin_root, "Meteoalarm", "areas")
        self.cache_file = conf.get("cache_file") or os.path.join(weewx_root, sqlite_root, "meteoalarm-cache.json")


def station_position(station):
    """[lat, lon] from the [Station] section of weewx.conf, or None."""
    try:
        lat, lon = float(station["latitude"]), float(station["longitude"])
    except (TypeError, KeyError, ValueError):
        return None
    return [lat, lon] if -90 <= lat <= 90 and -180 <= lon <= 180 else None


# ----------------------------------------------------------------------------- geometry
# Points are (lon, lat). Only outer rings are used; good enough for "does it touch".

def parse_cap_polygon(text):
    """CAP polygon "lat,lon lat,lon ..." -> [(lon, lat), ...]."""
    pts = []
    for pair in str(text).replace(";", " ").split():
        try:
            lat, lon = (float(v) for v in pair.split(","))
        except ValueError:
            continue
        pts.append((lon, lat))
    return pts if len(pts) >= 3 else []


def circle_to_polygon(text, sides=24):
    """CAP circle "lat,lon radius_km" -> polygon approximating it."""
    try:
        centre, radius = str(text).split()
        lat, lon = (float(v) for v in centre.split(","))
        r = float(radius)
    except ValueError:
        return []
    dlat = r / 111.32
    dlon = r / (111.32 * max(0.01, math.cos(math.radians(lat))))
    return [(lon + dlon * math.cos(2 * math.pi * i / sides), lat + dlat * math.sin(2 * math.pi * i / sides))
            for i in range(sides)]


def bbox(ring):
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_overlap(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def point_in_ring(pt, ring):
    x, y = pt
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _segments_cross(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def rings_intersect(a, b):
    """True if two simple polygons (outer rings) overlap or touch."""
    if not a or not b or not bbox_overlap(bbox(a), bbox(b)):
        return False
    if point_in_ring(a[0], b) or point_in_ring(b[0], a):
        return True
    for i in range(len(a)):
        p1, p2 = a[i - 1], a[i]
        for j in range(len(b)):
            if _segments_cross(p1, p2, b[j - 1], b[j]):
                return True
    return False


def outer_rings(geometry):
    if geometry["type"] == "Polygon":
        return [[tuple(p) for p in geometry["coordinates"][0]]]
    if geometry["type"] == "MultiPolygon":
        return [[tuple(p) for p in poly[0]] for poly in geometry["coordinates"]]
    return []


class Areas:
    """Area names, shapes and geocode aliases shipped in skins/Meteoalarm/areas."""

    def __init__(self, directory):
        self.dir = directory
        self.index = self._load("index.json")
        self.aliases = self._load("aliases.json")
        self._shapes = {}

    def _load(self, name):
        path = os.path.join(self.dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError) as e:
            log.error("meteoalarm: cannot read %s: %s", path, e)
            return {}

    def name(self, code):
        entry = self.index.get(code)
        return entry[0] if entry else code

    def shapes(self, country):
        if country not in self._shapes:
            data = self._load("%s.geojson" % country) if self.index else {}
            self._shapes[country] = {f["properties"]["code"]: outer_rings(f["geometry"])
                                     for f in data.get("features", [])}
        return self._shapes[country]

    def touching(self, polygon):
        """EMMA_IDs whose shape overlaps the polygon."""
        if not polygon:
            return []
        box = bbox(polygon)
        hits = []
        for code, (_name, country, area_box) in sorted(self.index.items()):
            if area_box and bbox_overlap(box, area_box):
                if any(rings_intersect(polygon, ring) for ring in self.shapes(country).get(code, [])):
                    hits.append(code)
        return hits


# ----------------------------------------------------------------------------- feeds

def parse_time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def fetch_feed(feed, opts):
    if opts.test_file:   # a saved feed, or a folder of <feed name>.json files
        path = opts.test_file
        if os.path.isdir(path):
            path = os.path.join(path, feed + ".json")
            if not os.path.exists(path):
                return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    url = FEED_URL.format(slug=feed)
    start = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=opts.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.error("meteoalarm: failed to fetch %s: %s", url, e)
        return None
    log.debug("meteoalarm: fetched %s in %.2fs", url, time.time() - start)
    return data


def area_hits(info, codes, aliases, polygon):
    """Which of our areas an alert <info> block covers, as dicts code/desc/note."""
    hits = []
    for area in as_list(info.get("area")):
        desc = area.get("areaDesc", "")
        matched = False
        for geo in as_list(area.get("geocode")):
            value, name = geo.get("value"), geo.get("valueName")
            if not isinstance(value, str) or not isinstance(name, str):
                continue
            if name == "EMMA_ID" and value in codes:
                hits.append({"code": value, "desc": desc, "note": ""})
                matched = True
                continue
            alias = aliases.get("%s|%s" % (value, name))
            if alias in codes:
                hits.append({"code": alias + "*", "desc": desc,
                             "note": "EMMA_ID %s matched through %s geocode %s." % (alias, name, value)})
                matched = True
        if polygon and not matched:
            shapes = [parse_cap_polygon(p) for p in as_list(area.get("polygon"))]
            shapes += [circle_to_polygon(c) for c in as_list(area.get("circle"))]
            if any(rings_intersect(polygon, s) for s in shapes if s):
                hits.append({"code": "polygon", "desc": desc,
                             "note": "Matched because the alert's own outline crosses your polygon."})
    return hits


def collect(feeds, codes, aliases, polygon, now):
    """{warning id: {language: info}} for current alerts (or starting within 24 h) in our areas."""
    warns = {}
    for feed_name, feed in feeds.items():
        for warning in feed.get("warnings") or []:
            wid = "%s/%s" % (feed_name, warning.get("uuid", ""))
            for alert in warning.values():
                if not isinstance(alert, dict) or "info" not in alert:
                    continue
                infos = as_list(alert["info"])
                if not infos:
                    continue
                expires = parse_time(infos[0].get("expires"))
                if expires is None or now > expires:
                    continue
                effective = parse_time(infos[0].get("onset")) or parse_time(infos[0].get("effective")) or now
                if (effective - now).total_seconds() > 24 * 3600:
                    continue
                for info in infos:
                    hits = area_hits(info, codes, aliases, polygon)
                    if hits:
                        entry = {k: v for k, v in info.items() if k != "area"}
                        entry.update(forus=hits, sent=alert.get("sent"))
                        warns.setdefault(wid, {})[info.get("language", "")] = entry
    return warns


def load_warnings(opts, areas, codes):
    """Cached warnings, refreshed from the feeds when older than cache_max_age."""
    signature = {"codes": sorted(codes), "polygon": opts.polygon_text}
    try:
        with open(opts.cache_file, encoding="utf-8") as fh:
            cache = json.load(fh)
        fresh = time.time() - cache.get("fetched", 0) <= opts.cache_max_age
        if fresh and cache.get("signature") == signature and not opts.test_file:
            return cache["warnings"], cache["fetched"]
    except (OSError, ValueError, KeyError):
        pass

    feeds = {}
    wanted = {FEEDS[c[:2]] for c in codes if c[:2] in FEEDS}
    if opts.polygon:   # alerts drawn as polygons can come from any feed the polygon reaches
        box = bbox(opts.polygon)
        wanted |= {FEEDS[v[1]] for v in areas.index.values()
                   if v[2] and v[1] in FEEDS and bbox_overlap(box, v[2])}
        wanted |= {FEEDS[c] for c, b in NO_SHAPE_BOXES.items() if bbox_overlap(box, b)}
    for name in sorted(wanted):
        data = fetch_feed(name, opts)
        if data:
            feeds[name] = data
    warnings = collect(feeds, set(codes), areas.aliases, opts.polygon, datetime.now(timezone.utc))
    fetched = time.time()
    try:
        with open(opts.cache_file, "w", encoding="utf-8") as fh:
            json.dump({"fetched": fetched, "signature": signature, "warnings": warnings}, fh)
    except OSError as e:
        log.error("meteoalarm: cannot write cache %s: %s", opts.cache_file, e)
    return warnings, fetched


# ----------------------------------------------------------------------------- template model

def esc(text):
    return html.escape(str(text or ""), quote=True)


def text_to_html(text, url=""):
    out = esc(str(text or "").strip())
    if url:
        e = esc(url)
        out = out.replace(e, '<a href="%s" target="_blank" rel="noopener">%s</a>' % (e, e))
    return out.replace("\r\n", "\n").replace("\n", "<br/>")


def leading_int(value):
    try:
        return int(str(value).split(";")[0].strip())
    except ValueError:
        return 0


class Alert:
    """One warning, ready for a template. Text attributes are already HTML-escaped."""

    def __init__(self, languages, number, opts):
        info = next(iter(languages.values()))
        level_raw = type_raw = ""
        for p in as_list(info.get("parameter")):
            if p.get("valueName") == "awareness_level":
                level_raw = p.get("value", "")
            elif p.get("valueName") == "awareness_type" or not type_raw:
                type_raw = p.get("value", "")
        self.level = leading_int(level_raw)
        self.type_no = leading_int(type_raw)
        parts = type_raw.split(";")
        slug = parts[1].strip() if len(parts) > 1 else ""
        self.event_type = esc(slug.replace("-", " ").title())
        self.icon = "meteoalarm_%s.svg" % (self.type_no if self.type_no in ICONS else "000")
        self.color = LEVEL_COLORS.get(self.level, "#fff")
        self.level_name = LEVEL_NAMES.get(self.level, "")
        self.severity = SEVERITY.get(self.level, "")
        self.advice = LEVEL_ADVICE.get(self.level, "")
        title = str(info.get("event", ""))
        for word in COLOR_WORDS:
            title = title.replace(word, "")
        title = title.strip()
        self.title = esc(title[:1].upper() + title[1:]) or self.event_type
        self.anchor = "alert%d" % number

        def local(value):
            dt = parse_time(value)
            return dt.astimezone() if dt else None

        self.onset = local(info.get("onset") or info.get("effective"))
        self.expires = local(info.get("expires"))
        self.sent = local(info.get("sent"))
        fmt_full = "%s %s" % (opts.date_format, opts.time_format)
        self.onset_text = esc(self.onset.strftime(fmt_full)) if self.onset else ""
        if self.expires:
            same_day = self.onset and self.onset.date() == self.expires.date()
            self.expires_text = esc(self.expires.strftime(opts.time_format if same_day else fmt_full))
        else:
            self.expires_text = ""
        self.sent_text = esc(self.sent.strftime(fmt_full)) if self.sent else ""

        web = str(info.get("web") or "").strip()
        u = urlparse(web)
        self.web = esc(web)
        self.origin_url = esc("%s://%s/" % (u.scheme, u.netloc)) if u.scheme and u.netloc else ""
        self.sender_name = esc(info.get("senderName") or "")
        self.areas = [{"code": esc(h["code"]), "desc": esc(h["desc"]), "note": esc(h["note"]),
                       "country": h["code"][:2] if h["code"] != "polygon" else ""}
                      for h in info["forus"]]
        self.languages = []
        for i, (lang, t) in enumerate(languages.items()):
            headline = esc(str(t.get("headline") or "").strip())
            description = text_to_html(t.get("description"), web)
            if description == headline:
                description = ""
            self.languages.append({
                "code": esc(lang), "id": "%s-%d" % (self.anchor, i),
                "name": esc(LANG_NAMES.get(lang[:2].lower(), lang)),
                "headline": headline, "description": description,
                "instruction": text_to_html(t.get("instruction"), web),
            })


class Meteoalarm:
    """The $meteoalarm tag. Work is done on first use, so unused skins pay nothing."""

    def __init__(self, opts):
        self.opts = opts
        self._done = False

    def _load(self):
        if self._done:
            return
        self._done = True
        opts = self.opts
        self._areas = Areas(opts.areas_dir)
        self._polygon_codes = self._areas.touching(opts.polygon)
        self._codes = list(dict.fromkeys(opts.emma_ids + self._polygon_codes))
        self._alerts, self._max_level, self._updated = [], 0, None
        if not self._codes and not opts.polygon:
            return
        warnings, fetched = load_warnings(opts, self._areas, self._codes)
        self._updated = datetime.fromtimestamp(fetched).astimezone()
        n = 0
        for languages in warnings.values():
            n += 1
            alert = Alert(languages, n, opts)
            if not 1 <= alert.level <= 4:
                continue
            self._max_level = max(self._max_level, alert.level)
            if alert.level >= opts.min_level:
                self._alerts.append(alert)
        self._alerts.sort(key=lambda a: (-a.level, a.onset or datetime.max.replace(tzinfo=timezone.utc)))

    # --- configuration -----------------------------------------------------
    @property
    def configured(self):
        return bool(self.opts.emma_ids or self.opts.polygon)

    @property
    def area_codes(self):
        self._load()
        return self._codes

    @property
    def polygon_area_codes(self):
        self._load()
        return self._polygon_codes

    @property
    def area_list(self):
        """[{code, name}] for every area watched (escaped)."""
        self._load()
        return [{"code": c, "name": esc(self._areas.name(c))} for c in self._codes]

    @property
    def polygon(self):
        return esc(self.opts.polygon_text)

    @property
    def min_level(self):
        return self.opts.min_level

    @property
    def min_level_name(self):
        return LEVEL_NAMES[self.opts.min_level]

    # --- warnings ----------------------------------------------------------
    @property
    def alerts(self):
        self._load()
        return self._alerts

    @property
    def has_alerts(self):
        return bool(self.alerts)

    @property
    def count(self):
        return len(self.alerts)

    @property
    def max_level(self):
        """Highest level of any current warning, including ones below min_level."""
        self._load()
        return self._max_level

    @property
    def max_color(self):
        return LEVEL_COLORS.get(self.max_level, LEVEL_COLORS[1])

    @property
    def updated(self):
        self._load()
        fmt = "%s %s" % (self.opts.date_format, self.opts.time_format)
        return esc(self._updated.strftime(fmt)) if self._updated else ""

    @property
    def summary(self):
        """Alerts grouped by area for a compact display:
        [{area, country, icons: [{color, icon, title, anchor, level_name}]}]"""
        groups = {}
        for a in self.alerts:
            for area in a.areas:
                key = (area["desc"], area["country"])
                icons = groups.setdefault(key, {})
                icons.setdefault((a.level, a.icon), {"color": a.color, "icon": a.icon, "title": a.event_type,
                                                     "anchor": a.anchor, "level_name": a.level_name})
        return [{"area": desc, "country": esc(FEEDS.get(country, country).replace("-", " ").title()) if country else "",
                 "icons": sorted(icons.values(), key=lambda i: i["color"])}
                for (desc, country), icons in groups.items()]

    @property
    def json(self):
        """Current warnings as a JSON document, for other programs."""
        out = []
        for a in self.alerts:
            out.append({
                "level": a.level, "level_name": a.level_name, "type": html.unescape(a.event_type),
                "title": html.unescape(a.title),
                "onset": a.onset.isoformat() if a.onset else None,
                "expires": a.expires.isoformat() if a.expires else None,
                "areas": [{k: html.unescape(v) for k, v in ar.items()} for ar in a.areas],
                "headline": {l["code"]: html.unescape(l["headline"]) for l in a.languages},
            })
        return json.dumps({"updated": self._updated.isoformat() if self._updated else None,
                           "max_level": self.max_level, "alerts": out}, ensure_ascii=False, indent=1)


class MeteoalarmSearchList(SearchList):
    """Search-list extension providing $meteoalarm."""

    def __init__(self, generator):
        super().__init__(generator)
        config = generator.config_dict
        conf = dict(config.get("Meteoalarm", {}))
        conf.update(generator.skin_dict.get("Meteoalarm", {}))   # per-skin overrides
        sqlite_root = config.get("DatabaseTypes", {}).get("SQLite", {}).get("SQLITE_ROOT", "archive")
        self.opts = Options(conf, weewx_root=config.get("WEEWX_ROOT", "."),
                            skin_root=config.get("StdReport", {}).get("SKIN_ROOT", "skins"),
                            sqlite_root=sqlite_root, station=config.get("Station"))

    def get_extension_list(self, timespan, db_lookup):
        return [{"meteoalarm": Meteoalarm(self.opts)}]


# ----------------------------------------------------------------------------- choosing areas
# Areas are chosen on the area map published on GitHub Pages. The installer (and
# "meteoalarm.py --setup") prints a link to it with the station and current choice
# in the URL fragment, which browsers never send to the server, and reads back the
# setup code the map shows: MA1:<EMMA codes>:<min level>:<lat,lon;lat,lon;...>

MAX_CORNERS = 200
MAP_URL = "https://millardiang.github.io/weewx-meteoalarm_warnings/v1/map/"


def clean_polygon(text):
    """Validate a polygon "lat,lon lat,lon ..." (or ; separated); return it as a closed CAP string."""
    pts = []
    for pair in str(text or "").replace(";", " ").split():
        try:
            lat, lon = (float(v) for v in pair.split(","))
        except ValueError:
            raise ValueError("polygon corner %r is not lat,lon" % pair)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("polygon corner %r is off the map" % pair)
        pts.append((lat, lon))
    if pts and pts[0] == pts[-1]:
        pts.pop()
    if not pts:
        return ""
    if len(pts) < 3:
        raise ValueError("a polygon needs at least 3 corners")
    if len(pts) > MAX_CORNERS:
        raise ValueError("a polygon can have at most %d corners" % MAX_CORNERS)
    pts.append(pts[0])
    return " ".join("%.4f,%.4f" % p for p in pts)


def clean_selection(emma_ids, polygon, min_level, known_codes=None):
    """Check a selection; returns {"emma_ids": [...], "polygon": str, "min_level": int}."""
    if isinstance(emma_ids, str):
        emma_ids = emma_ids.split(",")
    codes = []
    for c in emma_ids or []:
        c = str(c).strip().upper()
        if not c:
            continue
        if not re.fullmatch(r"[A-Z]{2}[0-9]{3,4}", c):
            raise ValueError("%s is not an EMMA code" % c)
        if known_codes and c not in known_codes:
            raise ValueError("unknown area code %s" % c)
        if c not in codes:
            codes.append(c)
    polygon = clean_polygon(polygon)
    try:
        level = int(min_level)
    except (TypeError, ValueError):
        raise ValueError("the level must be 1 to 4")
    if not 1 <= level <= 4:
        raise ValueError("the level must be 1 to 4")
    if not codes and not polygon:
        raise ValueError("choose at least one area or draw a polygon")
    return {"emma_ids": sorted(codes), "polygon": polygon, "min_level": level}


def parse_setup_code(text, known_codes=None):
    """Read the code shown on the map page."""
    code = str(text or "").strip().strip("'\"` ")
    if not code.upper().startswith("MA1:"):
        raise ValueError("a setup code starts with MA1:  (copy it from the map page)")
    parts = code.split(":", 3)
    if len(parts) != 4:
        raise ValueError("the setup code is incomplete; copy the whole line")
    return clean_selection(parts[1], parts[3], parts[2], known_codes)


def describe_selection(sel, names=None):
    names = names or {}
    out = ["%s (%s)" % (c, names[c][0]) if c in names else c for c in sel["emma_ids"]]
    if sel["polygon"]:
        out.append("a polygon with %d corners" % (len(sel["polygon"].split()) - 1))
    return ", ".join(out) + "; warnings from %s up" % LEVEL_NAMES[sel["min_level"]].lower()


def apply_selection(config_dict, sel):
    """Write a selection into [Meteoalarm] of a ConfigObj dictionary."""
    if "Meteoalarm" not in config_dict:
        config_dict["Meteoalarm"] = {}
    sec = config_dict["Meteoalarm"]
    sec["emma_ids"] = ", ".join(sel["emma_ids"])
    sec["polygon"] = sel["polygon"]
    sec["min_level"] = str(sel["min_level"])


def web_folder(config_dict, weewx_root):
    """Where the Meteoalarm report writes its pages (the folder the map goes in)."""
    std = config_dict.get("StdReport", {})
    folder = std.get("Meteoalarm", {}).get("HTML_ROOT") or \
        os.path.join(std.get("HTML_ROOT", "public_html"), "meteoalarm")
    return os.path.abspath(os.path.join(weewx_root, folder))


def map_link(config_dict):
    """Link to the area map, opening on the station and the current settings.
    Everything personal is in the fragment (after #), which the browser keeps to itself."""
    sec = config_dict.get("Meteoalarm", {}) or {}
    base = str(sec.get("map_url") or MAP_URL).split("#")[0]
    parts = []
    station = station_position(config_dict.get("Station"))
    if station:
        parts.append("lat=%s&lon=%s" % (round(station[0], 4), round(station[1], 4)))
    codes = to_list(sec.get("emma_ids"))
    if codes:
        parts.append("areas=" + ",".join(codes))
    try:
        parts.append("level=%d" % min(4, max(1, int(sec.get("min_level", 2)))))
    except (TypeError, ValueError):
        parts.append("level=2")
    polygon = sec.get("polygon") or ""
    if isinstance(polygon, (list, tuple)):
        polygon = ",".join(polygon)
    pts = str(polygon).split()
    if len(pts) >= 4 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) >= 3:
        parts.append("poly=" + ";".join(pts))
    return base + "#" + "&".join(parts)


def interactive_setup(config_dict, weewx_root, skin_dir, out=print, ask=input):
    """Show the link to the area map and ask for the setup code. Returns the selection or None."""
    try:
        with open(os.path.join(skin_dir, "areas", "index.json"), encoding="utf-8") as fh:
            known = json.load(fh)
    except (OSError, ValueError):
        known = None
    out("")
    out("Please select your location(s) from the map. Open this link in a browser on any device:")
    out("")
    out("    " + map_link(config_dict))
    out("")
    out("It opens at your station. Pick your areas or draw a polygon, press 'Copy setup code',")
    out("and paste the code here. (Your station's position is in the part after '#', which")
    out("the browser keeps to itself; nothing about your station is sent anywhere.)")
    for _attempt in range(5):
        try:
            answer = ask("Setup code (or press Enter to skip): ").strip()
        except EOFError:
            return None
        if not answer:
            return None
        try:
            sel = parse_setup_code(answer, known)
        except ValueError as e:
            out("That didn't work: %s. Try again." % e)
            continue
        out("Warning areas: " + describe_selection(sel, known))
        return sel
    return None


def _save_config(config, config_path):
    import shutil
    backup = "%s.%s" % (config_path, time.strftime("%Y%m%d%H%M%S"))
    shutil.copy2(config_path, backup)
    config.write()
    print("Saved in %s (previous version kept as %s)." % (config_path, backup))


def setup_from_command_line(config_path):
    """meteoalarm.py --setup: choose areas again and save them in weewx.conf."""
    config, weewx_root = _load_config(config_path)
    skin_dir = os.path.join(weewx_root, config.get("StdReport", {}).get("SKIN_ROOT", "skins"), "Meteoalarm")
    sel = interactive_setup(config, weewx_root, skin_dir)
    if not sel:
        print("Nothing changed.")
        return 1
    apply_selection(config, sel)
    _save_config(config, config_path)
    print("Restart WeeWX to use the new areas, e.g.  sudo systemctl restart weewx")
    return 0


# ----------------------------------------------------------------------------- Seasons banner
# The installer can add a warning banner to the Seasons skin's home page. The snippet
# only loads banner.html (written by this extension's report, empty when there are
# no warnings), so Seasons keeps working even if this extension is removed.

BANNER_START = "<!-- meteoalarm banner: added by the meteoalarm extension; " \
               "remove with  meteoalarm.py --remove-banner -->"
BANNER_END = "<!-- end meteoalarm banner -->"
BANNER_ANCHOR = '#include "titlebar.inc"'


def seasons_paths(config_dict, weewx_root):
    """(Seasons index.html.tmpl, folder the Seasons report writes to)."""
    std = config_dict.get("StdReport", {})
    report = std.get("SeasonsReport", {})
    template = os.path.join(weewx_root, std.get("SKIN_ROOT", "skins"), report.get("skin", "Seasons"),
                            "index.html.tmpl")
    site = os.path.abspath(os.path.join(weewx_root, report.get("HTML_ROOT") or std.get("HTML_ROOT", "public_html")))
    return template, site


def banner_snippet(banner_url, indent="    "):
    js = """#raw
<div id="meteoalarm-banner"></div>
<script>
(function () {
  var el = document.getElementById("meteoalarm-banner");
  var base = new URL(%s, document.baseURI);
  function load() {
    fetch(base.href + "?t=" + Math.floor(Date.now() / 60000), { cache: "no-cache" })
      .then(function (r) { return r.ok ? r.text() : ""; })
      .then(function (html) {
        var t = document.createElement("template");
        t.innerHTML = html;
        t.content.querySelectorAll("[src],[href]").forEach(function (n) {
          ["src", "href"].forEach(function (a) {
            var v = n.getAttribute(a);
            if (v && v.charAt(0) !== "#") { n.setAttribute(a, new URL(v, base).href); }
          });
        });
        el.replaceChildren(t.content);
      })
      .catch(function () {});
  }
  load();
  setInterval(load, 5 * 60 * 1000);
})();
</script>
#end raw""" % json.dumps(banner_url)
    lines = [BANNER_START] + js.splitlines() + [BANNER_END]
    return "".join(indent + line + "\n" if line else "\n" for line in lines)


def _strip_banner(text):
    start = text.find(BANNER_START)
    if start < 0:
        return text, False
    end = text.find(BANNER_END, start)
    if end < 0:
        raise ValueError("the banner's end marker is missing; remove it by hand")
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end + 1
    return text[:line_start] + text[line_end:], True


def add_seasons_banner(config_dict, weewx_root):
    """Add (or refresh) the banner in the Seasons home page. Returns the template path."""
    template, site = seasons_paths(config_dict, weewx_root)
    if not os.path.isfile(template):
        raise ValueError("there is no Seasons skin at %s" % template)
    with open(template, encoding="utf-8") as fh:
        text = fh.read()
    text, _had = _strip_banner(text)
    at = text.find(BANNER_ANCHOR)
    if at < 0:
        raise ValueError("couldn't find %s in %s to put the banner after" % (BANNER_ANCHOR, template))
    line_start = text.rfind("\n", 0, at) + 1
    indent = text[line_start:at] if not text[line_start:at].strip() else ""
    line_end = text.find("\n", at)
    line_end = len(text) if line_end < 0 else line_end + 1
    rel = os.path.relpath(os.path.join(web_folder(config_dict, weewx_root), "banner.html"), site)
    text = text[:line_end] + banner_snippet(rel.replace(os.sep, "/"), indent) + text[line_end:]
    backup = template + ".before-meteoalarm"
    if not os.path.exists(backup):
        import shutil
        shutil.copy2(template, backup)
    with open(template, "w", encoding="utf-8") as fh:
        fh.write(text)
    return template


def remove_seasons_banner(config_dict, weewx_root):
    """Take the banner out again. Returns the template path, or None if it wasn't there."""
    template, _site = seasons_paths(config_dict, weewx_root)
    try:
        with open(template, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    text, had = _strip_banner(text)
    if not had:
        return None
    with open(template, "w", encoding="utf-8") as fh:
        fh.write(text)
    return template


def _load_config(config_path):
    try:
        import configobj
    except ImportError:
        raise SystemExit("Run this with WeeWX's Python, e.g. ~/weewx-venv/bin/python3 %s"
                         % os.path.abspath(__file__))
    config = configobj.ConfigObj(config_path, encoding="utf-8", interpolation=False, file_error=True)
    weewx_root = os.path.join(os.path.dirname(os.path.abspath(config_path)),
                              os.path.expanduser(config.get("WEEWX_ROOT") or "."))
    return config, weewx_root


# ----------------------------------------------------------------------------- standalone test

if __name__ == "__main__":
    import argparse
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    default_areas = os.path.normpath(os.path.join(here, "..", "..", "skins", "Meteoalarm", "areas"))
    p = argparse.ArgumentParser(description="Show MeteoAlarm warnings for a configuration, "
                                            "or (--setup) choose your warning areas again.")
    p.add_argument("--setup", action="store_true", help="choose your areas on the map and save them in weewx.conf")
    p.add_argument("--map-link", action="store_true", help="print the link to the area map for your settings")
    p.add_argument("--add-banner", action="store_true", help="add the warning banner to the Seasons home page")
    p.add_argument("--remove-banner", action="store_true", help="take the banner out of the Seasons home page")
    p.add_argument("--config", default=os.path.normpath(os.path.join(here, "..", "..", "weewx.conf")),
                   help="weewx.conf for --setup (default: the one this file is installed under)")
    p.add_argument("--emma-ids", default="")
    p.add_argument("--polygon", default="", help='CAP style "lat,lon lat,lon ..."')
    p.add_argument("--min-level", type=int, default=1)
    p.add_argument("--areas-dir", default=default_areas)
    p.add_argument("--test-file", help="use a saved feed instead of downloading")
    p.add_argument("--json", action="store_true", help="print the $meteoalarm.json document")
    args = p.parse_args()
    if args.setup:
        sys.exit(setup_from_command_line(args.config))
    if args.map_link:
        print(map_link(_load_config(args.config)[0]))
        sys.exit(0)
    if args.add_banner or args.remove_banner:
        cfg, root = _load_config(args.config)
        try:
            if args.add_banner:
                print("Added the warning banner to %s. It appears after the next report cycle."
                      % add_seasons_banner(cfg, root))
            else:
                done = remove_seasons_banner(cfg, root)
                print("Removed the warning banner from %s." % done if done else "There was no banner to remove.")
        except ValueError as e:
            sys.exit("Could not do that: %s" % e)
        sys.exit(0)
    logging.basicConfig(level=logging.INFO)
    import tempfile
    opts = Options({"emma_ids": args.emma_ids, "polygon": args.polygon, "min_level": args.min_level,
                    "areas_dir": args.areas_dir, "test_file": args.test_file, "cache_max_age": 0,
                    "cache_file": os.path.join(tempfile.gettempdir(), "meteoalarm-test-cache.json")})
    m = Meteoalarm(opts)
    print("Watching:", ", ".join("%s (%s)" % (a["code"], html.unescape(a["name"])) for a in m.area_list) or "-")
    if args.json:
        print(m.json)
        sys.exit(0)
    for a in m.alerts:
        print("%-6s %-20s %s - %s  %s" % (a.level_name, html.unescape(a.event_type), a.onset_text,
                                         a.expires_text, "; ".join(html.unescape(x["desc"]) for x in a.areas)))
    if not m.alerts:
        print("No current warnings at %s level or above." % m.min_level_name)
