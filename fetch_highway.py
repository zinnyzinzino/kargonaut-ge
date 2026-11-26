"""Fetch the real road line through our 8 cities for the landing page's map (static/data/highway.json).

REAL data: OSRM (OpenStreetMap) car route Batumi -> Poti -> Samtredia -> Kutaisi -> Zestafoni -> Gori -> Tbilisi
-> Rustavi, the same service and city points as data/routes.json. Run once; the file is committed, so the site
never calls OSRM itself.

    python fetch_highway.py
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from core.geo import CITY_COORDS

ORDER = ["Batumi", "Poti", "Samtredia", "Kutaisi", "Zestafoni", "Gori", "Tbilisi", "Rustavi"]
OUT = Path(__file__).resolve().parent / "static" / "data" / "highway.json"
KEEP_EVERY_M = 400   # thin the line: a point at most every ~400 m is plenty for a picture


def _metres(a, b):
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * 111_320, (a[1] - b[1]) * 111_320 * math.cos(lat))


def main():
    coords = ";".join(f"{CITY_COORDS[c][1]},{CITY_COORDS[c][0]}" for c in ORDER)
    url = f"https://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"
    # Windows' own certificate store (truststore, as logimind-ai's generate_routes.py): Python's bundled one
    # rejected the server here with "certificate has expired". Verification stays on either way.
    try:
        import ssl
        import truststore
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        context = None
    with urlopen(Request(url, headers={"User-Agent": "kargonaut-ge/1 (route picture)"}), timeout=60,
                 context=context) as r:
        route = json.load(r)["routes"][0]
    points = [[round(lat, 5), round(lng, 5)] for lng, lat in route["geometry"]["coordinates"]]
    thin = [points[0]]
    for p in points[1:-1]:
        if _metres(thin[-1], p) >= KEEP_EVERY_M:
            thin.append(p)
    thin.append(points[-1])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "OSRM / OpenStreetMap, car profile",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cities": ORDER,
        "distance_km": round(route["distance"] / 1000, 1),
        "points": thin,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"{len(points)} points -> {len(thin)} kept, {route['distance'] / 1000:.1f} km -> {OUT}")


if __name__ == "__main__":
    main()
