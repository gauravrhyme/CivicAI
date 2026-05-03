"""
CivicAI — Flask Backend v3
--------------------------
Serves CivicAI.html and exposes /scrape which returns:
  { issues, leaderboard, clusters, timestamp }
 
Sources:
  1. OpenCity CSV  — real Bengaluru pothole dataset
  2. OpenCity KML  — geo-coordinates for same dataset
  3. Reddit JSON   — r/bangalore civic complaints (no auth needed)
  4. Google News RSS — Bengaluru civic news
 
Deploy on Render:
  Build Command : pip install -r requirements.txt
  Start Command : python app.py
"""
 
import csv
import os
import random
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from io import StringIO
 
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
 
# ── App ────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)
 
# ── Config ─────────────────────────────────────────────────────
OPENCITY_CSV = (
    "https://data.opencity.in/dataset/"
    "3a1a98f8-f924-4257-a2a1-3b957b55b9f5/resource/"
    "22be8fdc-532d-4ec8-8e31-2e6d26d5ce85/download/"
    "e03fbadf-ff1a-4fe1-9aad-a2a38a2bd81d.csv"
)
OPENCITY_KML = (
    "https://data.opencity.in/dataset/"
    "3a1a98f8-f924-4257-a2a1-3b957b55b9f5/resource/"
    "d1d4a437-95ee-4327-9154-f9a8933b2110/download/"
    "63b30ddf-5919-43d0-a6cf-17d5cc90a35c.kml"
)
 
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
 
WARDS = [
    "Indiranagar", "Koramangala", "Jayanagar", "Rajajinagar", "Malleswaram",
    "Hebbal", "Whitefield", "Electronic City", "HSR Layout", "BTM Layout",
    "Banashankari", "Vijayanagar", "Yelahanka", "JP Nagar", "Marathahalli",
    "Shivajinagar", "Basavanagudi", "Frazer Town", "Sadashivanagar", "Bellandur",
]
 
ISSUE_KEYWORDS = {
    "Pothole":            ["pothole", "crater", "road damage", "road caved", "bad road", "road condition"],
    "Garbage":            ["garbage", "waste", "trash", "dump", "litter", "sewage", "stench", "sanitation"],
    "Water Logging":      ["waterlog", "flooding", "flood", "water stagnant", "inundated", "water clog"],
    "Open Drain":         ["open drain", "manhole", "open gutter", "sewer uncovered", "drain"],
    "Broken Streetlight": ["streetlight", "street light", "no light", "dark road", "lamp post"],
    "Illegal Dumping":    ["illegal dump", "debris dump", "construction waste", "garbage dump"],
    "Damaged Footpath":   ["footpath", "pavement broken", "sidewalk", "broken tiles"],
    "Encroachment":       ["encroach", "illegal construction", "road encroach"],
}
 
 
# ── Helpers ────────────────────────────────────────────────────
 
def gen_id():
    return "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=7))
 
 
def detect_issue_type(text: str) -> str:
    t = text.lower()
    for issue_type, keywords in ISSUE_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return issue_type
    return "Pothole"
 
 
def score_severity(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["accident", "death", "danger", "fatal", "collapse", "emergency", "hazard"]):
        return "critical"
    if any(w in t for w in ["flood", "major", "severe", "horrible", "terrible", "urgent", "danger"]):
        return "high"
    if any(w in t for w in ["minor", "small", "slight", "little"]):
        return "low"
    return "medium"
 
 
def detect_ward(text: str) -> str:
    t = text.lower()
    for w in WARDS:
        if w.lower() in t:
            return w
    return random.choice(WARDS)
 
 
def days_ago_iso(n: int) -> str:
    return (datetime.utcnow() - timedelta(days=n)).isoformat() + "Z"
 
 
def make_issue(description, source, lat=None, lon=None, ward=None, issue_type=None):
    return {
        "id":            gen_id(),
        "issue_type":    issue_type or detect_issue_type(description),
        "description":   description[:220].strip(),
        "location_name": ward or "",
        "ward":          ward or detect_ward(description),
        "severity":      score_severity(description),
        "status":        "open",
        "source":        source,
        "source_url":    None,
        "latitude":      round(lat, 6) if lat else None,
        "longitude":     round(lon, 6) if lon else None,
        "timestamp":     datetime.utcnow().isoformat() + "Z",
        "upvotes":       random.randint(1, 45),
        "image_url":     None,
    }
 
 
# ── Data Sources ───────────────────────────────────────────────
 
def fetch_opencity_csv():
    """Fetch real pothole data from OpenCity Bengaluru dataset."""
    results = []
    try:
        resp = requests.get(OPENCITY_CSV, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        reader = csv.DictReader(StringIO(resp.text))
 
        for i, row in enumerate(reader):
            if i >= 120:
                break
 
            # Flexible column detection — OpenCity CSV columns vary
            ward = (
                row.get("Ward Name") or
                row.get("ward_name") or
                row.get("Ward") or
                row.get("ward") or
                "Unknown"
            ).strip()
 
            lat_raw = (row.get("Latitude") or row.get("latitude") or row.get("lat") or "").strip()
            lon_raw = (row.get("Longitude") or row.get("longitude") or row.get("lon") or "").strip()
            desc    = (row.get("Description") or row.get("description") or row.get("Complaint") or "").strip()
 
            if not desc:
                desc = f"Pothole reported in {ward}"
 
            try:
                lat = float(lat_raw) if lat_raw else None
                lon = float(lon_raw) if lon_raw else None
            except ValueError:
                lat = lon = None
 
            # Validate Bengaluru lat/lon range
            if lat and not (12.7 < lat < 13.2):
                lat = None
            if lon and not (77.3 < lon < 77.9):
                lon = None
 
            if ward and ward != "Unknown":
                results.append(make_issue(
                    description=desc,
                    source="OpenCity CSV",
                    lat=lat,
                    lon=lon,
                    ward=ward if ward in WARDS else detect_ward(ward),
                    issue_type="Pothole",
                ))
 
    except Exception as e:
        print(f"[CSV] Error: {e}")
 
    print(f"[CSV] Fetched {len(results)} issues")
    return results
 
 
def fetch_opencity_kml():
    """Fetch geo-coordinates from OpenCity KML file."""
    results = []
    try:
        resp = requests.get(OPENCITY_KML, headers=HEADERS, timeout=15)
        resp.raise_for_status()
 
        # Strip namespaces for easier parsing
        content = resp.content.decode("utf-8", errors="replace")
        content = content.replace(' xmlns="http://www.opengis.net/kml/2.2"', "")
        content = content.replace("kml:", "")
 
        root = ET.fromstring(content.encode("utf-8"))
        placemarks = root.findall(".//Placemark")[:80]
 
        for p in placemarks:
            name_el  = p.find(".//name")
            desc_el  = p.find(".//description")
            coord_el = p.find(".//coordinates")
 
            name  = name_el.text.strip()  if name_el  and name_el.text  else "Pothole"
            desc  = desc_el.text.strip()  if desc_el  and desc_el.text  else name
            coord = coord_el.text.strip() if coord_el and coord_el.text else None
 
            lat = lon = None
            if coord:
                try:
                    parts = coord.split(",")
                    lon = float(parts[0])
                    lat = float(parts[1])
                    if not (12.7 < lat < 13.2) or not (77.3 < lon < 77.9):
                        lat = lon = None
                except Exception:
                    pass
 
            if lat and lon:
                results.append(make_issue(
                    description=desc[:200] or f"Pothole reported near {name}",
                    source="OpenCity KML",
                    lat=lat,
                    lon=lon,
                    issue_type="Pothole",
                ))
 
    except Exception as e:
        print(f"[KML] Error: {e}")
 
    print(f"[KML] Fetched {len(results)} issues")
    return results
 
 
def fetch_reddit():
    """Fetch r/bangalore posts using Reddit's public JSON API (no auth)."""
    results = []
    query = "pothole OR garbage OR drain OR flood OR BBMP OR streetlight OR waterlogging OR encroach"
    url   = (
        f"https://www.reddit.com/r/bangalore/search.json"
        f"?q={requests.utils.quote(query)}&sort=new&restrict_sr=1&limit=20&t=week"
    )
    try:
        resp  = requests.get(url, headers=HEADERS, timeout=12)
        data  = resp.json()
        posts = data.get("data", {}).get("children", [])
 
        for post in posts:
            p     = post.get("data", {})
            title = (p.get("title") or "").strip()
            body  = (p.get("selftext") or "").strip()
            text  = f"{title}. {body}"[:220]
            link  = "https://reddit.com" + (p.get("permalink") or "")
 
            if len(text) < 20:
                continue
 
            issue = make_issue(description=text, source="reddit")
            issue["source_url"] = link
            results.append(issue)
 
    except Exception as e:
        print(f"[Reddit] Error: {e}")
 
    print(f"[Reddit] Fetched {len(results)} issues")
    return results
 
 
def fetch_google_news():
    """Fetch Bengaluru civic news via Google News RSS (no auth)."""
    results = []
    queries = [
        "Bengaluru pothole BBMP road",
        "Bangalore garbage collection problem",
        "Bengaluru waterlogging flood 2025",
        "BBMP drain manhole Bengaluru",
    ]
    for query in queries[:3]:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:5]
 
            for item in items:
                title = getattr(item.find("title"), "text", "") or ""
                desc  = getattr(item.find("description"), "text", "") or ""
                link  = getattr(item.find("link"), "text", "") or ""
 
                # Strip HTML from description
                import re
                desc = re.sub(r"<[^>]+>", " ", desc).strip()
                text = f"{title}. {desc}"[:220]
 
                if len(text) < 20:
                    continue
 
                issue = make_issue(description=text, source="news")
                issue["source_url"] = link
                results.append(issue)
 
            time.sleep(0.4)
 
        except Exception as e:
            print(f"[News] Error for '{query}': {e}")
 
    print(f"[News] Fetched {len(results)} issues")
    return results
 
 
# ── Analytics ──────────────────────────────────────────────────
 
def build_leaderboard(issues):
    counts = {}
    for i in issues:
        w = i.get("ward", "Unknown")
        counts[w] = counts.get(w, 0) + 1
    ranked = sorted(
        [{"ward": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )
    return ranked[:15]
 
 
def cluster_issues(issues):
    """Group issues by first 40 chars of description (simple similarity)."""
    clusters = {}
    for i in issues:
        key = i["description"][:40].strip()
        clusters.setdefault(key, []).append(i)
 
    result = []
    for k, items in clusters.items():
        if len(items) >= 2:          # only show real clusters
            result.append({"cluster": k, "items": items})
    result.sort(key=lambda x: len(x["items"]), reverse=True)
    return result[:10]
 
 
def deduplicate(issues):
    """Remove duplicates by lat/lon, then by description."""
    seen_coords = set()
    seen_desc   = set()
    unique      = []
 
    for i in issues:
        lat = i.get("latitude")
        lon = i.get("longitude")
        desc_key = i["description"][:60].lower()
 
        if lat and lon:
            coord_key = (round(lat, 4), round(lon, 4))
            if coord_key in seen_coords:
                continue
            seen_coords.add(coord_key)
 
        if desc_key in seen_desc:
            continue
        seen_desc.add(desc_key)
        unique.append(i)
 
    return unique
 
 
# ── Pipeline ───────────────────────────────────────────────────
 
def run_pipeline(sources="csv,kml,reddit,news"):
    all_issues = []
    src_list   = [s.strip() for s in sources.split(",")]
 
    if "csv"    in src_list:
        all_issues.extend(fetch_opencity_csv())
    if "kml"    in src_list:
        all_issues.extend(fetch_opencity_kml())
    if "reddit" in src_list:
        all_issues.extend(fetch_reddit())
    if "news"   in src_list:
        all_issues.extend(fetch_google_news())
 
    unique      = deduplicate(all_issues)
    leaderboard = build_leaderboard(unique)
    clusters    = cluster_issues(unique)
 
    # Sort: critical first
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    unique.sort(key=lambda x: sev_order.get(x["severity"], 4))
 
    print(f"[Pipeline] Total unique issues: {len(unique)}")
    return unique, leaderboard, clusters
 
 
# ── Routes ─────────────────────────────────────────────────────
 
@app.route("/")
def index():
    try:
        with open("CivicAI.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return (
            "<h2 style='font-family:sans-serif;padding:40px;color:#333'>"
            "⚠ CivicAI.html not found.<br>"
            "Make sure CivicAI.html is in the same folder as app.py</h2>"
        ), 404
 
 
@app.route("/scrape")
def scrape():
    """
    Main data endpoint.
    Query params:
      ?sources=csv,kml,reddit,news   (default: all)
      ?limit=100                     (default: 100)
    Returns:
      { status, timestamp, issues, leaderboard, clusters }
    """
    sources = request.args.get("sources", "csv,kml,reddit,news")
    limit   = min(int(request.args.get("limit", 100)), 200)
 
    try:
        issues, leaderboard, clusters = run_pipeline(sources)
        return jsonify({
            "status":      "success",
            "timestamp":   datetime.utcnow().isoformat() + "Z",
            "count":       len(issues[:limit]),
            "issues":      issues[:limit],
            "leaderboard": leaderboard,
            "clusters":    clusters,
        })
 
    except Exception as e:
        print(f"[Scrape] Fatal error: {e}")
        return jsonify({
            "status":  "error",
            "message": str(e),
        }), 500
 
 
@app.route("/health")
def health():
    return jsonify({
        "status":    "ok",
        "service":   "CivicAI",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })
 
 
# ── Run ────────────────────────────────────────────────────────
 
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"""
╔══════════════════════════════════════╗
║   CivicAI Flask Backend v3           ║
║   http://localhost:{port}               ║
║   /scrape  — live data endpoint      ║
║   /health  — health check            ║
╚══════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=port, debug=False)
