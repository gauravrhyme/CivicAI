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

import json
import re
import time
import random
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from flask_cors import CORS

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
CORS(app)

# ── Constants ─────────────────────────────────────────

WARDS = [
    "Indiranagar","Koramangala","Jayanagar","Rajajinagar","Malleswaram",
    "Hebbal","Whitefield","Electronic City","HSR Layout","BTM Layout",
    "Banashankari","Vijayanagar","Yelahanka","JP Nagar","Marathahalli",
    "Shivajinagar","Basavanagudi","Frazer Town","Sadashivanagar","Bellandur",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Helpers ───────────────────────────────────────────

def gen_id():
    return ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=7))

def build_issue(text, source, url=None):
    return {
        "id": gen_id(),
        "description": text[:140],
        "source": source,
        "source_url": url,
        "created_at": datetime.utcnow().isoformat()
    }

# ── SCRAPERS ──────────────────────────────────────────

def scrape_reddit():
    results = []
    url = "https://www.reddit.com/r/bangalore/search.json?q=pothole&limit=10"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)

        if resp.status_code != 200:
            print("Reddit blocked:", resp.status_code)
            return results

        try:
            data = resp.json()
        except:
            print("Reddit JSON failed")
            return results

        posts = data.get("data", {}).get("children", [])

        for post in posts:
            p = post["data"]
            text = p.get("title", "")
            link = "https://reddit.com" + p.get("permalink", "")

            if len(text) > 20:
                results.append(build_issue(text, "reddit", link))

    except Exception as e:
        print("Reddit error:", e)

    return results


def scrape_google_news():
    results = []
    url = "https://news.google.com/rss/search?q=bangalore pothole"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.content, "xml")

        for item in soup.find_all("item")[:5]:
            title = item.title.text
            link = item.link.text
            results.append(build_issue(title, "news", link))

    except Exception as e:
        print("News error:", e)

    return results


def scrape_bbmp():
    results = []
    url = "https://bbmp.gov.in/en/web/guest/complaints"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        soup = BeautifulSoup(resp.text, "html.parser")

        for p in soup.find_all("p")[:5]:
            text = p.get_text()
            if len(text) > 30:
                results.append(build_issue(text, "bbmp", url))

    except Exception as e:
        print("BBMP error:", e)

    return results


# ── ROUTES ────────────────────────────────────────────

@app.route("/")
def index():
    import os
    try:
        print("FILES IN ROOT:", os.listdir())  # Debug log

        with open("CivicAI.html", "r", encoding="utf-8") as f:
            return f.read()

    except Exception as e:
        return f"<h2>ERROR LOADING HTML:</h2><pre>{str(e)}</pre>"


@app.route("/scrape")
def scrape():
    issues = []
    issues += scrape_reddit()
    issues += scrape_google_news()
    issues += scrape_bbmp()

    return jsonify(issues[:20])


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ── RUN (FIXED FOR RENDER) ─────────────────────────────

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))   # IMPORTANT FIX
    app.run(host="0.0.0.0", port=port)
