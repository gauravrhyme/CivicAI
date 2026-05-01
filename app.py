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
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from flask_cors import CORS
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
CORS(app)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}

# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def gen_id():
    return ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))

def build_issue(text, source, url=None):
    return {
        "id": gen_id(),
        "description": text[:200],
        "source": source,
        "source_url": url,
        "timestamp": datetime.utcnow().isoformat()
    }

def safe_request(url):
    try:
        return requests.get(url, headers=HEADERS, timeout=10, verify=False)
    except:
        return None

# ─────────────────────────────────────────
# SCRAPERS
# ─────────────────────────────────────────

def scrape_reddit():
    results = []
    url = "https://www.reddit.com/r/bangalore/search.json?q=pothole&limit=10"

    resp = safe_request(url)
    if not resp or resp.status_code != 200:
        return results

    try:
        data = resp.json()
        posts = data["data"]["children"]

        for p in posts:
            text = p["data"]["title"]
            link = "https://reddit.com" + p["data"]["permalink"]

            if len(text) > 20:
                results.append(build_issue(text, "reddit", link))
    except:
        pass

    return results


def scrape_google_news():
    results = []
    url = "https://news.google.com/rss/search?q=bangalore pothole"

    resp = safe_request(url)
    if not resp:
        return results

    soup = BeautifulSoup(resp.content, "xml")

    for item in soup.find_all("item")[:5]:
        results.append(build_issue(item.title.text, "google_news", item.link.text))

    return results


def scrape_bing_news():
    results = []
    url = "https://www.bing.com/news/search?q=bangalore pothole&format=rss"

    resp = safe_request(url)
    if not resp:
        return results

    soup = BeautifulSoup(resp.content, "xml")

    for item in soup.find_all("item")[:5]:
        results.append(build_issue(item.title.text, "bing_news", item.link.text))

    return results


def scrape_indian_news():
    sources = [
        "https://www.thehindu.com/news/cities/bangalore/feeder/default.rss",
        "https://timesofindia.indiatimes.com/rssfeeds/-2128838597.cms",
        "https://feeds.feedburner.com/ndtvnews-top-stories"
    ]

    results = []

    for src in sources:
        resp = safe_request(src)
        if not resp:
            continue

        soup = BeautifulSoup(resp.content, "xml")

        for item in soup.find_all("item")[:3]:
            results.append(build_issue(item.title.text, "indian_news", item.link.text))

    return results


def scrape_change_org():
    results = []
    url = "https://www.change.org/search?q=bangalore roads"

    resp = safe_request(url)
    if not resp:
        return results

    soup = BeautifulSoup(resp.text, "html.parser")

    for p in soup.select("a")[:5]:
        text = p.get_text(strip=True)
        if len(text) > 30:
            results.append(build_issue(text, "change_org", url))

    return results


def scrape_hackernews():
    results = []
    url = "https://hn.algolia.com/api/v1/search?query=bangalore pothole"

    resp = safe_request(url)
    if not resp:
        return results

    try:
        data = resp.json()
        for hit in data["hits"][:5]:
            results.append(build_issue(hit["title"], "hackernews", hit["url"]))
    except:
        pass

    return results


# ─────────────────────────────────────────
# MASTER SCRAPER
# ─────────────────────────────────────────

SCRAPERS = [
    scrape_reddit,
    scrape_google_news,
    scrape_bing_news,
    scrape_indian_news,
    scrape_change_org,
    scrape_hackernews,
]

def run_all_scrapers():
    all_data = []

    for scraper in SCRAPERS:
        try:
            data = scraper()
            all_data.extend(data)
            time.sleep(0.5)
        except Exception as e:
            print("Scraper failed:", scraper.__name__, e)

    # Deduplicate
    seen = set()
    unique = []

    for item in all_data:
        key = item["description"][:80].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


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
    data = run_all_scrapers()

    if len(data) == 0:
        return jsonify({
            "status": "error",
            "message": "No real data available",
            "data": []
        }), 500

    return jsonify({
        "status": "success",
        "count": len(data),
        "timestamp": datetime.utcnow().isoformat(),
        "data": data[:25]
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
