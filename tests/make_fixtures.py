"""Write sample MeteoAlarm feeds (tests/feeds/<feed>.json) with times relative to now."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

now = datetime.now(timezone.utc)
iso = lambda h: (now + timedelta(hours=h)).isoformat(timespec="seconds")


def info(lang, headline, level, typ, area, geocodes=(), polygon=None, start=-2, end=10, event="Yellow Wind Warning"):
    a = {"areaDesc": area, "geocode": [{"valueName": n, "value": v} for v, n in geocodes]}
    if polygon:
        a["polygon"] = [polygon]
    return {"language": lang, "event": event, "headline": headline,
            "description": "Gusts of 90 km/h <possible>.\nSee https://example.org/warn for details.",
            "instruction": "Secure loose objects.", "onset": iso(start), "effective": iso(start),
            "expires": iso(end), "web": "https://example.org/warn", "senderName": "Test Met Service",
            "parameter": [{"valueName": "awareness_level", "value": level},
                          {"valueName": "awareness_type", "value": typ}],
            "area": [a]}


def warning(uuid, *infos):
    return {"uuid": uuid, "alert": {"sent": iso(-3), "sender": "test", "info": list(infos)}}


feeds = {
    "denmark": [
        warning("dk-wind",
                info("da-DK", "Gult varsel for vind", "2; yellow; Moderate", "1; wind", "Nordjylland", [("DK002", "EMMA_ID")]),
                info("en-GB", "Yellow wind warning", "2; yellow; Moderate", "1; wind", "Nordjylland", [("DK002", "EMMA_ID")])),
        warning("dk-expired",
                info("en-GB", "Expired", "4; red; Extreme", "1; wind", "Nordjylland", [("DK002", "EMMA_ID")], start=-10, end=-1)),
        warning("dk-future",
                info("en-GB", "Starts in 2 days", "3; orange; Severe", "1; wind", "Nordjylland", [("DK002", "EMMA_ID")], start=48, end=60)),
        warning("dk-green",
                info("en-GB", "Green", "1; green; Minor", "1; wind", "Nordjylland", [("DK002", "EMMA_ID")])),
    ],
    "austria": [
        warning("at-rain", info("de-DE", "Starkregen", "3; orange; Severe", "10; rain", "Burgenland",
                                [("AT11", "NUTS2")], event="Orange Rain Warning")),
    ],
    "united-kingdom": [
        # Met Office style: warning drawn as a polygon over south-east England
        warning("uk-poly", info("en-GB", "Yellow warning of rain", "2; yellow; Moderate", "10; rain",
                                "London & South East England", [("UK999", "EMMA_ID")],
                                polygon="51.2,-0.8 51.8,-0.8 51.8,0.6 51.2,0.6 51.2,-0.8",
                                event="Yellow Rain Warning")),
        warning("uk-scot", info("en-GB", "Yellow warning of snow", "2; yellow; Moderate", "2; snow-ice",
                                "Highlands", [("UK266", "EMMA_ID")],
                                polygon="57,-6 58,-6 58,-4 57,-4 57,-6", event="Yellow Snow Warning")),
    ],
}
out = Path(__file__).parent / "feeds"
out.mkdir(exist_ok=True)
for name, warnings in feeds.items():
    (out / (name + ".json")).write_text(json.dumps({"warnings": warnings}, indent=1))
print("wrote", ", ".join(feeds))
