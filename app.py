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
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from flask_cors import CORS
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
CORS(app)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────

KEYWORDS = [
    "pothole", "garbage", "drain", "flood",
    "waterlogging", "bbmp", "road damage",
    "sewage", "streetlight", "civic issue"
]

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def gen_id():
    return ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))

def is_relevant(text):
    return any(k in text.lower() for k in KEYWORDS)

def score_issue(text):
    score = 0
    text = text.lower()

    for k in KEYWORDS:
        if k in text:
            score += 1

    if "bangalore" in text or "bengaluru" in text:
        score += 2

    if len(text) > 50:
        score += 1

    return score

def build_issue(text, source, url=None):
    return {
        "id": gen_id(),
        "description": text[:200],
        "source": source,
        "source_url": url,
        "confidence": score_issue(text),
        "timestamp": datetime.utcnow().isoformat()
    }

def safe_request(url):
    try:
        return requests.get(url, headers=HEADERS, timeout=10, verify=False)
    except:
        return None

# ─────────────────────────────────────────
# SOURCES (HIGH QUALITY ONLY)
# ─────────────────────────────────────────

def scrape_reddit():
    results = []
    url = "https://www.reddit.com/search.json?q=bangalore pothole&limit=20"

    resp = safe_request(url)
    if not resp or resp.status_code != 200:
        return results

    try:
        data = resp.json()
        posts = data["data"]["children"]

        for p in posts:
            text = p["data"]["title"]
            link = "https://reddit.com" + p["data"]["permalink"]

            if is_relevant(text):
                results.append(build_issue(text, "reddit", link))
    except:
        pass

    return results


def scrape_google_news():
    results = []
    url = "https://news.google.com/rss/search?q=bangalore civic issue"

    resp = safe_request(url)
    if not resp:
        return results

    soup = BeautifulSoup(resp.content, "xml")

    for item in soup.find_all("item")[:10]:
        text = item.title.text
        link = item.link.text

        if is_relevant(text):
            results.append(build_issue(text, "google_news", link))

    return results


def scrape_bing_news():
    results = []
    url = "https://www.bing.com/news/search?q=bangalore civic issue&format=rss"

    resp = safe_request(url)
    if not resp:
        return results

    soup = BeautifulSoup(resp.content, "xml")

    for item in soup.find_all("item")[:10]:
        text = item.title.text
        link = item.link.text

        if is_relevant(text):
            results.append(build_issue(text, "bing_news", link))

    return results


# ─────────────────────────────────────────
# MASTER PIPELINE
# ─────────────────────────────────────────

def run_pipeline():
    sources = [
        scrape_reddit,
        scrape_google_news,
        scrape_bing_news,
    ]

    all_data = []

    for src in sources:
        try:
            data = src()
            all_data.extend(data)
        except Exception as e:
            print("Error in", src.__name__, e)

    # Deduplicate
    seen = set()
    unique = []

    for item in all_data:
        key = item["description"][:80].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # Filter high confidence
    filtered = [x for x in unique if x["confidence"] >= 2]

    return filtered


# ─────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────

@app.route("/")
def index():
    try:
        with open("CivicAI.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"<h2>Error loading UI:</h2><pre>{str(e)}</pre>"


@app.route("/scrape")
def scrape():
    data = run_pipeline()

    if len(data) == 0:
        return jsonify({
            "status": "error",
            "message": "No verified civic issues found",
            "data": []
        }), 500

    return jsonify({
        "status": "success",
        "count": len(data),
        "timestamp": datetime.utcnow().isoformat(),
        "data": data[:20]
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
