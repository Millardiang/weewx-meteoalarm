#!/usr/bin/env python3
"""Checks to run before a release (and in CI on every push).

    python3 tools/check_release.py               # everyday checks
    python3 tools/check_release.py --release     # also: changelog section is dated
    python3 tools/check_release.py --tag v1.0.0  # also: tag matches the version
    python3 tools/check_release.py --notes       # print this version's changelog section

Checks that:
  - the version is the same, valid SemVer, in meteoalarm.py, install.py and skin.conf;
  - CHANGELOG.md has a section for it;
  - install.py lists exactly the files in bin/ and skins/;
  - the Python files compile, and the area data files load and agree with each other;
  - docs/ (the map website on GitHub Pages) matches site/ and the area data.
Exits non-zero if anything fails.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$")
problems = []


def fail(msg):
    problems.append(msg)
    print("FAIL  " + msg)


def ok(msg):
    print("ok    " + msg)


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def versions():
    found = {}
    for path, rx in (("bin/user/meteoalarm.py", r'^VERSION = "([^"]+)"$'),
                     ("install.py", r'^\s*version="([^"]+)",$'),
                     ("skins/Meteoalarm/skin.conf", r"^SKIN_VERSION = (\S+)$")):
        m = re.findall(rx, read(path), re.M)
        found[path] = m[0] if len(m) == 1 else None
    return found


def changelog_section(version):
    """(heading line, body) of the changelog section for version, or (None, None)."""
    text = read("CHANGELOG.md")
    m = re.search(r"^## \[%s\](.*)$" % re.escape(version), text, re.M)
    if not m:
        return None, None
    rest = text[m.end():]
    end = re.search(r"^## \[|^\[[^\]]+\]: ", rest, re.M)
    return m.group(0), rest[:end.start() if end else len(rest)].strip()


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--release", action="store_true", help="require a dated changelog section")
    p.add_argument("--tag", help="the git tag being released, e.g. v1.0.0")
    p.add_argument("--notes", action="store_true", help="print the changelog section and exit")
    args = p.parse_args()

    found = versions()
    version = found["bin/user/meteoalarm.py"]

    if args.notes:
        _heading, body = changelog_section(version or "")
        if not body:
            sys.exit("no changelog section for %s" % version)
        print(body)
        return 0

    # versions
    if None in found.values() or len(set(found.values())) != 1:
        fail("versions differ or are missing: %s" % found)
    elif not SEMVER.match(version):
        fail("version %r is not MAJOR.MINOR.PATCH" % version)
    else:
        ok("version %s in all three files" % version)
    if args.tag:
        if args.tag != "v%s" % version:
            fail("tag %s doesn't match version %s (expected v%s)" % (args.tag, version, version))
        else:
            ok("tag %s matches" % args.tag)

    # changelog
    heading, body = changelog_section(version or "")
    if not heading:
        fail("CHANGELOG.md has no '## [%s]' section" % version)
    elif not body:
        fail("CHANGELOG.md section [%s] is empty" % version)
    elif args.release and not re.search(r"\] - \d{4}-\d{2}-\d{2}$", heading):
        fail("CHANGELOG.md section [%s] has no release date: %s" % (version, heading))
    else:
        ok("CHANGELOG.md: %s" % heading)
    if "## [Unreleased]" not in read("CHANGELOG.md"):
        fail("CHANGELOG.md has no '## [Unreleased]' section for the next changes")

    # install file list
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_install_files.py")],
                       capture_output=True, text=True)
    (ok if r.returncode == 0 else fail)(r.stdout.strip().replace("\n", "; "))

    # python compiles (without leaving __pycache__ behind)
    bad = []
    for path in ["bin/user/meteoalarm.py", "install.py"] + \
            [str(x.relative_to(ROOT)) for x in sorted((ROOT / "tools").glob("*.py"))] + \
            [str(x.relative_to(ROOT)) for x in sorted((ROOT / "tests").glob("*.py"))]:
        try:
            src = read(path)
            compile(src, path, "exec")
        except SyntaxError as e:
            bad.append("%s: %s" % (path, e))
    (fail if bad else ok)("; ".join(bad) if bad else "Python files compile")

    # area data
    areas = ROOT / "skins" / "Meteoalarm" / "areas"
    try:
        index = json.loads((areas / "index.json").read_text(encoding="utf-8"))
        json.loads((areas / "aliases.json").read_text(encoding="utf-8"))
        shaped = {}
        for f in sorted(areas.glob("*.geojson")):
            for feat in json.loads(f.read_text(encoding="utf-8"))["features"]:
                shaped[feat["properties"]["code"]] = f.stem
        missing = [c for c, e in index.items() if e[2] and shaped.get(c) != e[1]]
        extra = [c for c in shaped if c not in index]
        if missing or extra:
            fail("area data disagrees: %d codes without outlines, %d outlines not in index.json"
                 % (len(missing), len(extra)))
        else:
            ok("area data: %d areas, %d with outlines" % (len(index), len(shaped)))
    except (OSError, ValueError, KeyError) as e:
        fail("area data unreadable: %s" % e)

    # the map website in docs/ matches site/ and the area data
    import filecmp
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_site.py"), tmp], capture_output=True, text=True)
        major = "v%s" % (version or "0").split(".")[0]
        if r.returncode:
            fail("tools/build_site.py failed: %s" % r.stderr.strip())
        else:
            stale = []
            for f in sorted(Path(tmp).rglob("*")):
                if f.is_file():
                    rel = f.relative_to(tmp)
                    live = ROOT / "docs" / rel
                    if not live.exists() or not filecmp.cmp(f, live, shallow=False):
                        stale.append(str(rel))
            extra = [str(f.relative_to(ROOT / "docs")) for f in (ROOT / "docs" / major).rglob("*")
                     if f.is_file() and not (Path(tmp) / f.relative_to(ROOT / "docs")).exists()] \
                if (ROOT / "docs" / major).exists() else []
            if stale or extra:
                fail("docs/ is out of date (%s); run  python3 tools/build_site.py  and commit docs/"
                     % ", ".join((stale + extra)[:5]))
            else:
                ok("docs/ (the map website) is up to date")

    print()
    if problems:
        print("%d problem(s)." % len(problems))
        return 1
    print("All checks passed for %s." % version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
