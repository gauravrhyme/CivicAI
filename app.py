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
from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS

# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)   # allows the HTML (even when opened as a file) to call /scrape

# ── Constants ──────────────────────────────────────────────────────────────────
WARDS = [
    "Indiranagar", "Koramangala", "Jayanagar", "Rajajinagar", "Malleswaram",
    "Hebbal", "Whitefield", "Electronic City", "HSR Layout", "BTM Layout",
    "Banashankari", "Vijayanagar", "Yelahanka", "JP Nagar", "Marathahalli",
    "Shivajinagar", "Basavanagudi", "Frazer Town", "Sadashivanagar", "Bellandur",
]

ISSUE_KEYWORDS = {
    "Pothole":            ["pothole", "crater", "road damage", "road caved", "bad road"],
    "Garbage":            ["garbage", "waste", "trash", "dump", "litter", "sewage smell", "stench"],
    "Water Logging":      ["waterlog", "flooding", "flood", "water stagnant", "water logged", "inundated"],
    "Open Drain":         ["open drain", "manhole", "open gutter", "open sewer", "drain uncovered"],
    "Broken Streetlight": ["streetlight", "street light", "no light", "dark road", "lamp post"],
    "Illegal Dumping":    ["illegal dump", "debris dump", "construction waste", "garbage dumped"],
    "Damaged Footpath":   ["footpath", "pavement broken", "sidewalk", "broken tiles", "footpath damaged"],
    "Encroachment":       ["encroach", "encroachment", "illegal construction", "road encroach"],
}

SEVERITY_KEYWORDS = {
    "critical": ["accident", "death", "serious", "emergency", "collapse", "danger", "hazard", "fatal"],
    "high":     ["major", "large", "big", "severe", "urgent", "horrible", "terrible", "worst"],
    "medium":   ["pothole", "garbage", "drain", "broken", "damaged", "stagnant"],
    "low":      ["minor", "small", "little", "slight"],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Helper utilities ────────────────────────────────────────────────────────────

def gen_id():
    return ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=7))


def detect_issue_type(text: str) -> str:
    text_lower = text.lower()
    for issue_type, keywords in ISSUE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return issue_type
    return "Pothole"   # default


def detect_severity(text: str) -> str:
    text_lower = text.lower()
    for severity, keywords in SEVERITY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return severity
    return "medium"


def detect_ward(text: str) -> str:
    text_lower = text.lower()
    for ward in WARDS:
        if ward.lower() in text_lower:
            return ward
    return random.choice(WARDS)


def days_ago_iso(n: int) -> str:
    dt = datetime.utcnow() - timedelta(days=n)
    return dt.isoformat() + "Z"


def build_issue(text: str, source: str, url: str = None, location: str = "") -> dict:
    return {
        "id":            gen_id(),
        "issue_type":    detect_issue_type(text),
        "description":   text[:160].strip(),
        "location_name": location or "Bengaluru",
        "ward":          detect_ward(text + " " + location),
        "severity":      detect_severity(text),
        "status":        "open",
        "created_at":    days_ago_iso(random.randint(0, 7)),
        "upvotes":       random.randint(1, 60),
        "source":        source,
        "source_url":    url,
        "image_url":     None,
    }


# ── Scrapers ────────────────────────────────────────────────────────────────────

def scrape_reddit() -> list:
    """
    Fetch posts from r/bangalore using Reddit's public JSON API.
    No API key needed — Reddit exposes /r/subreddit/search.json publicly.
    """
    results = []
    civic_terms = "pothole OR garbage OR drain OR flood OR BBMP OR streetlight OR waterlogging"
    url = (
        "https://www.reddit.com/r/bangalore/search.json"
        f"?q={requests.utils.quote(civic_terms)}&sort=new&restrict_sr=1&limit=15&t=week"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p = post.get("data", {})
            title = p.get("title", "")
            selftext = p.get("selftext", "")
            full_text = f"{title} {selftext}".strip()
            permalink = "https://reddit.com" + p.get("permalink", "")
            if len(full_text) > 20:
                results.append(build_issue(full_text, "reddit", permalink))
    except Exception as e:
        print(f"[Reddit] Error: {e}")
    return results


def scrape_google_news() -> list:
    """
    Scrape Google News RSS feed for Bengaluru civic issues.
    RSS is public and requires no API key.
    """
    results = []
    queries = [
        "Bengaluru pothole BBMP",
        "Bangalore garbage collection problem",
        "Bengaluru waterlogging flood",
        "Bangalore open drain manhole",
        "BBMP road repair Bengaluru",
    ]
    for query in queries[:3]:   # limit to 3 queries to stay fast
        rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            resp = requests.get(rss_url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(resp.content, "xml")
            items = soup.find_all("item")[:5]
            for item in items:
                title = item.find("title")
                link  = item.find("link")
                desc  = item.find("description")
                text  = ""
                if title:
                    text += title.get_text(strip=True) + " "
                if desc:
                    # strip HTML tags from description
                    text += BeautifulSoup(desc.get_text(), "html.parser").get_text()
                text = text.strip()
                url  = link.get_text(strip=True) if link else None
                if len(text) > 20:
                    results.append(build_issue(text, "news", url))
            time.sleep(0.5)   # be polite
        except Exception as e:
            print(f"[Google News] Error for '{query}': {e}")
    return results


def scrape_twitter_search() -> list:
    """
    Scrape Nitter (public Twitter mirror) for Bengaluru civic complaints.
    Nitter doesn't require authentication.
    """
    results = []
    queries = [
        "BBMP pothole bangalore",
        "bangalore garbage bbmp",
        "bengaluru waterlogging",
    ]
    nitter_instances = [
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
    ]
    instance = nitter_instances[0]
    for query in queries[:2]:
        url = f"{instance}/search?q={requests.utils.quote(query)}&f=tweets"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            tweets = soup.select(".tweet-content")[:5]
            for tw in tweets:
                text = tw.get_text(strip=True)
                if len(text) > 20:
                    results.append(build_issue(text, "twitter", url))
            time.sleep(0.5)
        except Exception as e:
            print(f"[Nitter] Error for '{query}': {e}")
    return results


def scrape_bbmp_portal() -> list:
    """
    Attempt to pull data from BBMP's public complaint portal page.
    Falls back gracefully if the site is unavailable.
    """
    results = []
    url = "https://bbmp.gov.in/en/web/guest/complaints"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        # Try to find any complaint-like paragraphs
        paragraphs = soup.find_all("p")
        for p in paragraphs[:10]:
            text = p.get_text(strip=True)
            if len(text) > 30 and any(
                kw in text.lower() for kw in ["road", "drain", "garbage", "light", "pothole"]
            ):
                results.append(build_issue(text, "bbmp", url))
    except Exception as e:
        print(f"[BBMP] Error: {e}")
    return results


# ── Flask routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the CivicAI HTML frontend."""
    try:
        with open("CivicAI.html", "r", encoding="utf-8") as f:
            html = f.read()
        return html
    except FileNotFoundError:
        return (
            "<h2 style='font-family:sans-serif;padding:40px'>"
            "⚠ CivicAI.html not found.<br>"
            "Make sure CivicAI.html is in the same folder as app.py"
            "</h2>",
            404,
        )


@app.route("/scrape")
def scrape():
    """
    Scrape civic issues from Reddit, Google News, Nitter, and BBMP.
    Returns JSON array of issue objects ready for the frontend.

    Query params:
        ?sources=reddit,news,twitter,bbmp   (default: all)
        ?limit=20                           (max results, default 20)
    """
    sources_param = request.args.get("sources", "reddit,news,twitter,bbmp")
    limit         = int(request.args.get("limit", 20))
    enabled       = [s.strip() for s in sources_param.split(",")]

    all_issues = []

    if "reddit"  in enabled:
        print("[Scraper] Fetching Reddit r/bangalore…")
        all_issues.extend(scrape_reddit())

    if "news"    in enabled:
        print("[Scraper] Fetching Google News RSS…")
        all_issues.extend(scrape_google_news())

    if "twitter" in enabled:
        print("[Scraper] Fetching Nitter (Twitter mirror)…")
        all_issues.extend(scrape_twitter_search())

    if "bbmp"    in enabled:
        print("[Scraper] Fetching BBMP portal…")
        all_issues.extend(scrape_bbmp_portal())

    # Deduplicate by description similarity (simple word-overlap check)
    seen, unique = set(), []
    for issue in all_issues:
        key = issue["description"][:60].lower()
        if key not in seen:
            seen.add(key)
            unique.append(issue)

    # Sort by severity then trim to limit
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    unique.sort(key=lambda x: severity_order.get(x["severity"], 4))
    result = unique[:limit]

    print(f"[Scraper] Done — returning {len(result)} issues")
    return jsonify(result)


@app.route("/health")
def health():
    """Simple health check endpoint."""
    return jsonify({"status": "ok", "service": "CivicAI", "timestamp": datetime.utcnow().isoformat()})


# ── Entry point ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  CivicAI Flask Server")
    print("  Open: http://localhost:5000")
    print("  Scrape: http://localhost:5000/scrape")
    print("=" * 50)
    app.run(debug=True, host="0.0.0.0", port=5000)
