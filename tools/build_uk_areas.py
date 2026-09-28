#!/usr/bin/env python3
"""Build outlines for the UK MeteoAlarm areas (EMMA_IDs UK201-UK353).

MeteoAlarm's UK areas are counties, unitary authorities and council areas,
except that London's boroughs and five metropolitan counties are one area each,
and Northern Ireland uses its six historic counties. This script assembles them
from open data and writes a GeoJSON file in the format tools/build_areas.py
takes as an extra input:

    python3 tools/build_uk_areas.py GB.geojson NI_COUNTIES.shp uk-areas.geojson
    python3 tools/build_areas.py geocodes.json uk-areas.geojson

Inputs
  GB.geojson     ONS Counties and Unitary Authorities (December 2019), GB, as
                 GeoJSON with AREACD/AREANM properties. ONSvisual publishes it as
                 TopoJSON (github.com/ONSvisual/topojson_boundaries,
                 geogUACounty2019GB.json); convert with topojson-client:
                 topo2geo geogUACounty2019GB2=GB.geojson < geogUACounty2019GB.json
  NI_COUNTIES    OSNI Open Data Largescale Boundaries - County Boundaries
                 (shapefile, Irish Grid).

Both are © Crown copyright and database right, released under the Open
Government Licence v3.0; see skins/Meteoalarm/areas/SOURCES.txt.

Needs (build time only): pip install shapely pyshp pyproj
"""
import json
import re
import sys
from pathlib import Path

import pyproj
import shapefile
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parent.parent

# ONS names that differ from MeteoAlarm's
RENAMED = {
    "County Durham": "Durham",
    "Na h-Eileanan Siar": "Eilean Siar",
    "Aberdeen City": "Aberdeen",
    "Dundee City": "Dundee",
    "Glasgow City": "Glasgow",
}

# MeteoAlarm areas made of several ONS areas (metropolitan districts / London boroughs)
def group_of(code):
    if code.startswith("E09"):
        return "Greater London"
    if code.startswith("E08"):
        n = int(code[3:])
        for lo, hi, name in ((1, 10, "Greater Manchester"), (11, 15, "Merseyside"),
                             (16, 19, "South Yorkshire"), (25, 31, "West Midlands Conurbation"),
                             (32, 36, "West Yorkshire")):
            if lo <= n <= hi:
                return name
    return None   # Tyne and Wear's districts are separate MeteoAlarm areas


def norm(name):
    name = name.lower().replace("city of", "").replace("county of", "").replace("council", "")
    return re.sub(r"[^a-z]", "", name)


def main(gb_path, ni_path, out_path):
    index = json.loads((ROOT / "skins" / "Meteoalarm" / "areas" / "index.json").read_text(encoding="utf-8"))
    uk = {code: entry[0] for code, entry in index.items() if code.startswith("UK")}
    by_name = {norm(name): code for code, name in uk.items()}
    parts = {}

    for f in json.loads(Path(gb_path).read_text(encoding="utf-8"))["features"]:
        cd, nm = f["properties"]["AREACD"], f["properties"]["AREANM"]
        target = group_of(cd) or RENAMED.get(nm, nm)
        code = by_name.get(norm(target))
        if not code:
            sys.exit("no MeteoAlarm area for %s %s" % (cd, nm))
        parts.setdefault(code, []).append(shape(f["geometry"]).buffer(0))

    # Northern Ireland: Irish Grid (TM65) -> WGS84
    to_wgs84 = pyproj.Transformer.from_crs("EPSG:29902", "EPSG:4326", always_xy=True).transform
    reader = shapefile.Reader(str(ni_path))
    names = [fld[0] for fld in reader.fields[1:]]
    for sr in reader.iterShapeRecords():
        county = dict(zip(names, sr.record))["CountyName"].title()
        code = by_name.get(norm("County " + county))
        if not code:
            sys.exit("no MeteoAlarm area for NI county %s" % county)
        parts.setdefault(code, []).append(transform(to_wgs84, shape(sr.shape.__geo_interface__)).buffer(0))

    missing = sorted(set(uk) - set(parts))
    if missing:
        sys.exit("no outline for: " + ", ".join("%s %s" % (c, uk[c]) for c in missing))

    features = []
    for code in sorted(parts):
        geom = unary_union(parts[code])
        features.append({"type": "Feature",
                         "properties": {"code": code, "country": "UK", "name": uk[code], "type": "EMMA_ID"},
                         "geometry": mapping(geom)})
    Path(out_path).write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    print("wrote %d UK areas to %s" % (len(features), out_path))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
