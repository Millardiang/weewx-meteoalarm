#!/usr/bin/env python3
"""Build the area map website that GitHub Pages serves from the docs/ folder.

    python3 tools/build_site.py            # updates docs/
    python3 tools/build_site.py OUT        # builds into another folder

writes
    docs/v<MAJOR>/map/        the map page, script and styles (from site/map/)
    docs/v<MAJOR>/areas/      area outlines and names (from skins/Meteoalarm/areas/)
    docs/index.html           forwards to the newest map
    docs/.nojekyll

Run it after changing site/ or the area data, and commit docs/ with the change;
tools/check_release.py fails if docs/ is out of date. Only the current major
version's folder is replaced, so older installs keep a map that writes setup
codes they understand. GitHub Pages: Settings -> Pages -> Deploy from a branch ->
main, /docs.
"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def major_version():
    text = (ROOT / "bin" / "user" / "meteoalarm.py").read_text(encoding="utf-8")
    return re.search(r'^VERSION = "(\d+)\.', text, re.M).group(1)


def main(out):
    out = Path(out)
    major = "v" + major_version()
    dest = out / major
    if dest.exists():
        shutil.rmtree(dest)          # other versions' folders are kept
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "site" / "map", dest / "map")
    (dest / "areas").mkdir(parents=True)
    for f in sorted((ROOT / "skins" / "Meteoalarm" / "areas").iterdir()):
        if f.suffix in (".json", ".geojson", ".txt"):
            shutil.copy2(f, dest / "areas" / f.name)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "index.html").write_text(
        '<!DOCTYPE html>\n<meta charset="utf-8">\n<title>MeteoAlarm area map</title>\n'
        '<script>location.replace("%s/map/" + location.hash);</script>\n'
        '<p><a href="%s/map/">MeteoAlarm area map</a></p>\n' % (major, major), encoding="utf-8")
    n = sum(1 for _ in dest.rglob("*") if _.is_file())
    print("built %s: %d files, map at /%s/map/" % (dest, n, major))


if __name__ == "__main__":
    if len(sys.argv) > 2:
        sys.exit(__doc__)
    main(sys.argv[1] if len(sys.argv) == 2 else ROOT / "docs")
