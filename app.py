"""
CivicAI — Flask Backend
-----------------------
Serves the HTML frontend and exposes a /scrape route that
pulls real civic complaints from Reddit, Google News, and
public BBMP/Twitter search pages.

Run:
    pip install flask requests beautifulsoup4 flask-cors
    python app.py
Then open:  http://localhost:5000
"""

import random
from datetime import datetime
import requests
import pandas as pd
from flask import Flask, jsonify
from flask_cors import CORS
import xml.etree.ElementTree as ET

app = Flask(__name__)
CORS(app)

# DATA SOURCES
POTHOLE_CSV = "https://data.opencity.in/dataset/3a1a98f8-f924-4257-a2a1-3b957b55b9f5/resource/22be8fdc-532d-4ec8-8e31-2e6d26d5ce85/download/e03fbadf-ff1a-4fe1-9aad-a2a38a2bd81d.csv"

POTHOLE_KML = "https://data.opencity.in/dataset/3a1a98f8-f924-4257-a2a1-3b957b55b9f5/resource/d1d4a437-95ee-4327-9154-f9a8933b2110/download/63b30ddf-5919-43d0-a6cf-17d5cc90a35c.kml"

# HELPERS
def gen_id():
    return ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))

def score_severity(text):
    text = text.lower()
    if "accident" in text or "danger" in text:
        return "high"
    if "flood" in text:
        return "high"
    if "pothole" in text:
        return "medium"
    return "low"

def build_issue(text, source, lat=None, lon=None, ward="Unknown"):
    return {
        "id": gen_id(),
        "description": text,
        "source": source,
        "latitude": lat,
        "longitude": lon,
        "severity": score_severity(text),
        "ward": ward,
        "timestamp": datetime.utcnow().isoformat()
    }

# FETCH CSV DATA
def fetch_csv():
    results = []
    try:
        df = pd.read_csv(POTHOLE_CSV)

        for _, row in df.head(100).iterrows():
            ward = row.get("Ward Name", "Unknown")

            results.append(build_issue(
                text=f"Pothole reported in {ward}",
                source="OpenCity CSV",
                lat=row.get("Latitude"),
                lon=row.get("Longitude"),
                ward=ward
            ))
    except Exception as e:
        print("CSV error:", e)

    return results

# FETCH KML DATA
def fetch_kml():
    results = []
    try:
        resp = requests.get(POTHOLE_KML, timeout=10)
        root = ET.fromstring(resp.content)

        for p in root.findall(".//{http://www.opengis.net/kml/2.2}Placemark")[:100]:
            coords = p.find(".//{http://www.opengis.net/kml/2.2}coordinates")

            if coords is not None:
                lon, lat, _ = coords.text.split(",")

                results.append(build_issue(
                    text="Pothole reported",
                    source="OpenCity KML",
                    lat=float(lat),
                    lon=float(lon)
                ))
    except Exception as e:
        print("KML error:", e)

    return results

# ANALYTICS
def build_leaderboard(issues):
    counts = {}
    for i in issues:
        counts[i["ward"]] = counts.get(i["ward"], 0) + 1

    return sorted(
        [{"ward": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"],
        reverse=True
    )[:10]

def cluster_issues(issues):
    clusters = {}
    for i in issues:
        key = i["description"][:30]

        if key not in clusters:
            clusters[key] = []

        clusters[key].append(i)

    return [{"cluster": k, "items": v} for k, v in clusters.items()][:10]

# PIPELINE
def run_pipeline():
    data = fetch_csv() + fetch_kml()

    # Deduplicate by lat/lon
    seen = set()
    unique = []
    for i in data:
        key = (i["latitude"], i["longitude"])
        if key not in seen:
            seen.add(key)
            unique.append(i)

    return unique, build_leaderboard(unique), cluster_issues(unique)

# ROUTES
@app.route("/")
def index():
    with open("CivicAI.html", "r", encoding="utf-8") as f:
        return f.read()

@app.route("/scrape")
def scrape():
    issues, leaderboard, clusters = run_pipeline()

    return jsonify({
        "status": "success",
        "timestamp": datetime.utcnow().isoformat(),
        "issues": issues[:100],
        "leaderboard": leaderboard,
        "clusters": clusters
    })

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# RUN
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
