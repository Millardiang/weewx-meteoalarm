#!/usr/bin/env python3
"""Check that install.py lists exactly the files in bin/ and skins/ (run before a release)."""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tree = ast.parse(open(os.path.join(ROOT, "install.py")).read())
listed = set()
for node in tree.body:
    if isinstance(node, ast.Assign) and node.targets[0].id == "FILES":
        for _folder, files in ast.literal_eval(node.value):
            listed.update(files)
present = set()
for top in ("bin/user", "skins/Meteoalarm"):
    for folder, _dirs, names in os.walk(os.path.join(ROOT, top)):
        if "__pycache__" in folder:
            continue
        present.update(os.path.relpath(os.path.join(folder, n), ROOT) for n in names if not n.startswith("."))
missing, extra = sorted(present - listed), sorted(listed - present)
for f in missing:
    print("not in install.py:", f)
for f in extra:
    print("listed but missing:", f)
print("install.py file list OK" if not (missing or extra) else "install.py file list needs updating")
sys.exit(1 if missing or extra else 0)
