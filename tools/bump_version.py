#!/usr/bin/env python3
"""Set the extension's version everywhere it appears.

    python3 tools/bump_version.py 1.1.0

Updates bin/user/meteoalarm.py (VERSION), install.py (version=) and
skins/Meteoalarm/skin.conf (SKIN_VERSION), and moves the changes listed under
"## [Unreleased]" in CHANGELOG.md into a new "## [1.1.0] - <today>" section.
Run tools/check_release.py afterwards.
"""
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$")

# file -> (pattern whose group 1 is the version, replacement template)
PLACES = {
    "bin/user/meteoalarm.py": (r'^VERSION = "([^"]+)"$', 'VERSION = "{v}"'),
    "install.py": (r'^(\s*version=)"([^"]+)",$', None),
    "skins/Meteoalarm/skin.conf": (r"^SKIN_VERSION = (\S+)$", "SKIN_VERSION = {v}"),
}


def set_version(path, pattern, template, version):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    rx = re.compile(pattern, re.M)
    if len(rx.findall(text)) != 1:
        sys.exit("expected exactly one version in %s" % path)
    if template is None:   # install.py keeps its indentation
        text = rx.sub(lambda m: '%s"%s",' % (m.group(1), version), text)
    else:
        text = rx.sub(template.format(v=version), text)
    p.write_text(text, encoding="utf-8")


def update_changelog(version, today):
    p = ROOT / "CHANGELOG.md"
    text = p.read_text(encoding="utf-8")
    if re.search(r"^## \[%s\]" % re.escape(version), text, re.M):
        return "CHANGELOG.md already has a [%s] section" % version
    if "## [Unreleased]" not in text:
        sys.exit("CHANGELOG.md has no '## [Unreleased]' section to release")
    text = text.replace("## [Unreleased]", "## [Unreleased]\n\n## [%s] - %s" % (version, today), 1)
    # link references at the bottom
    repo = "https://github.com/Millardiang/weewx-meteoalarm_warnings"
    m = re.search(r"^\[Unreleased\]: .*/compare/v([^.]+\.[^.]+\.[^.]+)\.\.\.HEAD$", text, re.M)
    if m:
        prev = m.group(1)
        text = text.replace(m.group(0), "[Unreleased]: %s/compare/v%s...HEAD\n[%s]: %s/compare/v%s...v%s"
                            % (repo, version, version, repo, prev, version))
    p.write_text(text, encoding="utf-8")
    return "CHANGELOG.md: new section [%s] - %s" % (version, today)


def main(argv):
    if len(argv) != 1 or not SEMVER.match(argv[0]):
        sys.exit(__doc__)
    version = argv[0]
    for path, (pattern, template) in PLACES.items():
        set_version(path, pattern, template, version)
        print("%s -> %s" % (path, version))
    print(update_changelog(version, datetime.date.today().isoformat()))


if __name__ == "__main__":
    main(sys.argv[1:])
