#!/usr/bin/env python3
"""Build the area files used by the map and by polygon matching.

Input:  a GeoJSON FeatureCollection of MeteoAlarm areas with properties
        code / country / name / type (type == "EMMA_ID"), e.g. geocodes.json
        from the MIT-licensed `meteoalarm` Python package
        (https://github.com/NiklasJordan/meteoalarm, src/meteoalarm/assets).
        Extra GeoJSON files in the same format can be given to add areas
        (e.g. UK or Swiss regions) or override existing ones.

Output (in skins/Meteoalarm/areas/):
  index.json    {code: [name, country, [minlon, minlat, maxlon, maxlat] | null]}
                covering every code in the geometry *and* in codenames.json
  XX.geojson    simplified shapes for country XX
  aliases.json  NUTS/FIPS geocode -> EMMA_ID aliases

Needs shapely (build time only):  pip install shapely
Usage: python3 tools/build_areas.py geocodes.json [extra.geojson ...]
"""
import json
import sys
from pathlib import Path

from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "skins" / "Meteoalarm" / "areas"
TOLERANCE = 0.003   # degrees (~300 m); plenty for picking areas
DIGITS = 4          # ~10 m


def rnd(obj):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(obj[0], DIGITS), round(obj[1], DIGITS)]
        return [rnd(o) for o in obj]
    return obj


def main(paths):
    features = {}
    for path in paths:
        for f in json.loads(Path(path).read_text(encoding="utf-8"))["features"]:
            p = f["properties"]
            if p.get("type", "EMMA_ID") == "EMMA_ID":
                features[p["code"]] = f
    codenames = json.loads((ROOT / "data" / "meteoalarm-codenames.json").read_text(encoding="utf-8"))

    OUT.mkdir(parents=True, exist_ok=True)
    index, by_country = {}, {}
    for code, f in sorted(features.items()):
        geom = shape(f["geometry"]).simplify(TOLERANCE, preserve_topology=True)
        if geom.is_empty:
            continue
        p = f["properties"]
        name = p.get("name") or codenames.get(code, code)
        index[code] = [name, code[:2], [round(v, DIGITS) for v in geom.bounds]]
        by_country.setdefault(code[:2], []).append({
            "type": "Feature",
            "properties": {"code": code, "name": name},
            "geometry": {"type": geom.geom_type, "coordinates": rnd(mapping(geom)["coordinates"])},
        })
    for code, name in codenames.items():
        if code[:2].isupper() and code[2:].isdigit() and code not in index:
            index[code] = [name, code[:2], None]   # selectable from the list only

    for country, feats in by_country.items():
        (OUT / f"{country}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                                    encoding="utf-8")
    aliases = json.loads((ROOT / "data" / "meteoalarm-geocode-aliases.json").read_text(encoding="utf-8"))
    (OUT / "aliases.json").write_text(json.dumps(aliases, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    shaped = sum(1 for v in index.values() if v[2])
    print(f"{len(index)} areas ({shaped} with shapes) in {len(by_country)} country files -> {OUT}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
