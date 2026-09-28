#!/usr/bin/env python3
"""End-to-end test: install the extension into a throwaway WeeWX station and use it.

Needs WeeWX 5 installed for the Python running this (pip install weewx), so
that `weectl` is available. Downloads nothing: the warnings come from sample
feeds written by tests/make_fixtures.py.

    python3 tests/smoke_test.py            # uses a temporary folder, then deletes it
    python3 tests/smoke_test.py --keep     # keep the station to look at

It checks that:
  - `weectl extension install` takes a setup code and adds the Seasons banner;
  - the reports build, with the expected warnings in every output;
  - the map link carries the station only after '#', and no page on the WeeWX
    website contains the station's position; the map website builds;
  - the banner is empty when no warning reaches min_level;
  - `meteoalarm.py --remove-banner` restores the Seasons template exactly;
  - `weectl extension uninstall` removes the extension and Seasons still builds.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP_CODE = "MA1:AT008,DK002:2:51.3,-0.5;51.7,-0.5;51.7,0.2"
# expected from tests/make_fixtures.py with that code at min_level 2:
#   DK002 wind (direct), AT008 rain (via NUTS alias AT11), UK rain (its polygon crosses ours)
EXPECTED = {"Wind Warning", "Rain Warning"}
EXPECTED_COUNT = 3


class Failed(Exception):
    pass


def check(condition, message):
    if not condition:
        raise Failed(message)
    print("ok    " + message)


def weectl():
    exe = shutil.which("weectl", path=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
    if not exe:
        sys.exit("weectl not found: install WeeWX 5 for this Python first (pip install weewx)")
    return exe


def run(args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)
    out = r.stdout + r.stderr
    if r.returncode != 0 or "Traceback" in out:
        raise Failed("command failed: %s\n%s" % (" ".join(map(str, args)), out[-3000:]))
    return out


def set_option(conf, section, key, value):
    import configobj   # comes with WeeWX
    cfg = configobj.ConfigObj(str(conf), encoding="utf-8", interpolation=False)
    cfg.setdefault(section, {})[key] = value
    cfg.write()


def add_archive_data(station, conf):
    """Reports are skipped on an empty database, so add an hour of records."""
    code = (
        "import time, configobj, weewx, weewx.manager\n"
        "cfg = configobj.ConfigObj(%r); cfg['WEEWX_ROOT'] = %r\n"
        "with weewx.manager.open_manager_with_config(cfg, 'wx_binding', initialize=True) as m:\n"
        "    now = int(time.time()) // 300 * 300\n"
        "    for t in range(now - 3600, now + 1, 300):\n"
        "        m.addRecord({'dateTime': t, 'usUnits': weewx.US, 'interval': 5, 'outTemp': 60.0})\n"
    ) % (str(conf), str(station))
    run([sys.executable, "-c", code])


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--keep", action="store_true", help="keep the test station")
    args = p.parse_args()

    sys.dont_write_bytecode = True      # don't leave __pycache__ in bin/user
    sys.path.insert(0, str(ROOT / "bin" / "user"))
    import meteoalarm
    link = meteoalarm.map_link({"Station": {"latitude": "51.48", "longitude": "-0.01"},
                                "Meteoalarm": {"emma_ids": "UK258, UK271", "min_level": "3",
                                               "polygon": "51.3,-0.5 51.7,-0.5 51.7,0.2 51.3,-0.5"}})
    check(link == meteoalarm.MAP_URL + "#lat=51.48&lon=-0.01&areas=UK258,UK271&level=3"
          "&poly=51.3,-0.5;51.7,-0.5;51.7,0.2", "map link carries the settings after '#' only")
    check("#" not in meteoalarm.MAP_URL and "?" not in meteoalarm.MAP_URL, "nothing personal before the '#'")

    wx = weectl()
    tmp = Path(tempfile.mkdtemp(prefix="meteoalarm-smoke-"))
    station, conf = tmp / "station", tmp / "station" / "weewx.conf"
    ok = False
    try:
        print("Station in %s" % station)
        run([wx, "station", "create", str(station), "--no-prompt", "--driver=weewx.drivers.simulator",
             "--latitude=51.48", "--longitude=-0.01", "--location=Smoke test"])
        with conf.open("a", encoding="utf-8") as fh:        # log to the console, not syslog
            fh.write("\n[Logging]\n    [[root]]\n        handlers = console,\n")
        seasons = station / "skins" / "Seasons" / "index.html.tmpl"
        original = seasons.read_text(encoding="utf-8")

        # install from this checkout, as a user would with a setup code and the banner
        out = run([wx, "extension", "install", str(ROOT), "-y", "--config=%s" % conf,
                   "--setup-code=%s" % SETUP_CODE, "--banner"])
        check("Warning areas: AT008" in out and "Added the warning banner" in out,
              "install accepted the setup code and added the banner")
        text = conf.read_text(encoding="utf-8")
        check(re.search(r'^\s*emma_ids = "?AT008, DK002"?$', text, re.M) and
              re.search(r"^\s*polygon = \"51\.3000,-0\.5000 ", text, re.M) and
              re.search(r"^\s*min_level = 2$", text, re.M), "[Meteoalarm] saved in weewx.conf")
        check(seasons.read_text(encoding="utf-8").count("meteoalarm banner: added") == 1,
              "banner block is in the Seasons template once")
        run([wx, "extension", "install", str(ROOT), "-y", "--config=%s" % conf, "--no-map", "--banner"])
        check(seasons.read_text(encoding="utf-8").count("meteoalarm banner: added") == 1,
              "installing again doesn't add a second banner")

        # sample feeds instead of meteoalarm.org
        run([sys.executable, str(ROOT / "tests" / "make_fixtures.py")])
        set_option(conf, "Meteoalarm", "test_file", str(ROOT / "tests" / "feeds"))
        add_archive_data(station, conf)

        out = run([wx, "report", "run", "SeasonsReport", "Meteoalarm", "--config=%s" % conf])
        check("Generated" in out and "Meteoalarm" in out, "reports built")
        web = station / "public_html"
        ma = web / "meteoalarm"
        data = json.loads((ma / "meteoalarm.json").read_text(encoding="utf-8"))
        titles = {a["title"] for a in data["alerts"]}
        check(len(data["alerts"]) == EXPECTED_COUNT and titles == EXPECTED,
              "meteoalarm.json has %d warnings: %s" % (len(data["alerts"]), sorted(titles)))
        details = (ma / "index.html").read_text(encoding="utf-8")
        check(all(t in details for t in EXPECTED) and 'id="alert1"' in details, "warnings page lists them")
        check("Weather warnings" in (ma / "summary.html").read_text(encoding="utf-8"), "summary box built")
        banner = (ma / "banner.html").read_text(encoding="utf-8")
        check("Weather warnings in force" in banner and "#FF9500" in banner, "banner shows, coloured orange")
        check('id="meteoalarm-banner"' in (web / "index.html").read_text(encoding="utf-8"),
              "Seasons home page loads the banner")
        check(not (ma / "map").exists() and not (ma / "areas").exists(), "no map on the WeeWX website")
        leaks = [str(f.relative_to(web)) for f in web.rglob("*") if f.is_file() and f.suffix in (".html", ".json")
                 and "51.48" in f.read_text(encoding="utf-8", errors="ignore")
                 and "meteoalarm" in str(f)]
        check(not leaks, "no meteoalarm page contains the station's position %s" % (leaks or ""))
        out = run([sys.executable, str(station / "bin" / "user" / "meteoalarm.py"), "--map-link", "--config", str(conf)])
        check(out.strip().startswith(meteoalarm.MAP_URL + "#lat=51.48&lon=-0.01&areas=AT008,DK002&level=2&poly="),
              "meteoalarm.py --map-link prints the link for the saved settings")

        # the map website builds
        site = tmp / "site"
        run([sys.executable, str(ROOT / "tools" / "build_site.py"), str(site)])
        check((site / "v1" / "map" / "index.html").exists() and (site / "v1" / "areas" / "UK.geojson").exists()
              and (site / "index.html").exists(), "map website builds (v1/map, v1/areas)")

        # nothing at red: banner empty
        set_option(conf, "Meteoalarm", "min_level", "4")
        run([wx, "report", "run", "Meteoalarm", "--config=%s" % conf])
        check(not (ma / "banner.html").read_text(encoding="utf-8").strip(), "banner empty with no warnings")

        # take the banner out, uninstall, Seasons still fine
        module = station / "bin" / "user" / "meteoalarm.py"
        out = run([sys.executable, str(module), "--remove-banner", "--config", str(conf)])
        check(seasons.read_text(encoding="utf-8") == original, "--remove-banner restores the template exactly")
        run([wx, "extension", "uninstall", "meteoalarm", "-y", "--config=%s" % conf])
        check(not module.exists() and not (station / "skins" / "Meteoalarm").exists(), "uninstall removed the files")
        text = conf.read_text(encoding="utf-8")
        check("emma_ids" not in text and "[[Meteoalarm]]" not in text, "uninstall removed the settings and report")
        out = run([wx, "report", "run", "SeasonsReport", "--config=%s" % conf])
        check("Generated" in out, "Seasons still builds")
        ok = True
    except Failed as e:
        print("FAIL  %s" % e)
    finally:
        if args.keep or not ok:
            print("Test station kept in %s" % station)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print("\nSmoke test %s." % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    t = time.time()
    code = main()
    print("(%.0f s)" % (time.time() - t))
    sys.exit(code)
