import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import json
import re
from google_play_scraper import reviews, Sort

# ─── CONFIG ───────────────────────────────────────────────────────────────────

TRUSTPILOT_URL = "https://www.trustpilot.com/review/asknebula.com"
GOOGLE_PLAY_APP_ID = "genesis.nebula"
OUTPUT_CSV = "reviews.csv"
OUTPUT_HTML = "index.html"
DAYS_BACK = 1  # collect reviews from the last N days (set to 730 for full 2 years on first run)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

SUPPORT_KEYWORDS = [
    "support", "help", "chat", "bot", "response", "reply", "refund",
    "payment", "cancel", "subscription", "waiting", "slow", "agent",
    "contact", "email", "ticket", "issue", "problem", "complaint",
    "payout", "billing", "charged", "customer service"
]

CATEGORIES = {
    "Slow / no response":   ["slow", "waiting", "wait", "days", "hours", "no reply", "no response", "never responded"],
    "Refund issues":        ["refund", "money back", "charged", "charge", "overcharged"],
    "Chatbot not working":  ["bot", "chatbot", "ai", "automated", "useless bot"],
    "Subscription / cancel":["cancel", "subscription", "unsubscribe", "auto-renew", "renewal"],
    "Payment & billing":    ["payment", "billing", "invoice", "payout", "transaction"],
    "App bug / crash":      ["crash", "bug", "error", "freeze", "not working", "broken"],
    "Support praised":      ["great support", "helpful", "amazing support", "quick response", "fast reply", "resolved"],
    "General complaint":    []
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def categorize(text):
    text_lower = text.lower()
    for category, keywords in CATEGORIES.items():
        if any(kw in text_lower for kw in keywords):
            return category
    return "General complaint"

def sentiment(rating):
    if rating >= 4:
        return "Positive"
    elif rating == 3:
        return "Neutral"
    else:
        return "Negative"

def is_support_related(text):
    text_lower = text.lower()
    return any(kw in text_lower for kw in SUPPORT_KEYWORDS)

def days_ago(n):
    return datetime.now() - timedelta(days=n)

# ─── TRUSTPILOT SCRAPER ───────────────────────────────────────────────────────

def scrape_trustpilot():
    print("Scraping Trustpilot...")
    results = []
    page = 1

    while True:
        url = f"{TRUSTPILOT_URL}?page={page}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f"  Trustpilot page {page}: status {resp.status_code}, stopping.")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            review_cards = soup.find_all("div", attrs={"data-service-review-card-paper": True})

            if not review_cards:
                review_cards = soup.find_all("article", class_=re.compile("review"))

            if not review_cards:
                print(f"  No more reviews found on page {page}.")
                break

            found_old = False
            for card in review_cards:
                try:
                    # Rating
                    rating_img = card.find("img", alt=re.compile(r"Rated \d"))
                    if not rating_img:
                        star_div = card.find("div", attrs={"data-service-review-rating": True})
                        rating = int(star_div["data-service-review-rating"]) if star_div else 3
                    else:
                        rating = int(re.search(r"Rated (\d)", rating_img["alt"]).group(1))

                    # Text
                    text_el = card.find("p", attrs={"data-service-review-text-typography": True})
                    if not text_el:
                        text_el = card.find("p", class_=re.compile("review_text|reviewText"))
                    text = text_el.get_text(strip=True) if text_el else ""

                    # Title
                    title_el = card.find("h2", attrs={"data-service-review-title-typography": True})
                    title = title_el.get_text(strip=True) if title_el else ""

                    # Date
                    date_el = card.find("time")
                    if date_el and date_el.get("datetime"):
                        raw_date = date_el["datetime"][:10]
                        review_date = datetime.strptime(raw_date, "%Y-%m-%d")
                    else:
                        review_date = datetime.now()

                    # Check date range
                    if review_date < days_ago(DAYS_BACK):
                        found_old = True
                        continue

                    if not text:
                        continue

                    # Link
                    link_el = card.find("a", href=re.compile(r"/reviews/"))
                    link = f"https://www.trustpilot.com{link_el['href']}" if link_el else TRUSTPILOT_URL

                    results.append({
                        "date": review_date.strftime("%Y-%m-%d"),
                        "source": "Trustpilot",
                        "title": title,
                        "text": text,
                        "rating": rating,
                        "sentiment": sentiment(rating),
                        "category": categorize(title + " " + text),
                        "support_related": is_support_related(title + " " + text),
                        "link": link
                    })

                except Exception as e:
                    print(f"  Error parsing Trustpilot review: {e}")
                    continue

            if found_old and DAYS_BACK <= 30:
                break

            page += 1
            time.sleep(1.5)

            if page > 50:
                break

        except Exception as e:
            print(f"  Trustpilot request error: {e}")
            break

    print(f"  Found {len(results)} Trustpilot reviews.")
    return results

# ─── GOOGLE PLAY SCRAPER ──────────────────────────────────────────────────────

def scrape_google_play():
    print("Scraping Google Play...")
    results = []

    try:
        result, _ = reviews(
            GOOGLE_PLAY_APP_ID,
            lang="en",
            country="us",
            sort=Sort.NEWEST,
            count=200,
            filter_score_with=None
        )

        cutoff = days_ago(DAYS_BACK)

        for r in result:
            try:
                review_date = r["at"]
                if isinstance(review_date, str):
                    review_date = datetime.strptime(review_date[:10], "%Y-%m-%d")

                if review_date < cutoff:
                    continue

                text = r.get("content", "")
                if not text:
                    continue

                rating = r.get("score", 3)
                link = f"https://play.google.com/store/apps/details?id={GOOGLE_PLAY_APP_ID}&reviewId={r.get('reviewId', '')}"

                results.append({
                    "date": review_date.strftime("%Y-%m-%d"),
                    "source": "Google Play",
                    "title": r.get("userName", ""),
                    "text": text,
                    "rating": rating,
                    "sentiment": sentiment(rating),
                    "category": categorize(text),
                    "support_related": is_support_related(text),
                    "link": link
                })

            except Exception as e:
                print(f"  Error parsing Google Play review: {e}")
                continue

    except Exception as e:
        print(f"  Google Play error: {e}")

    print(f"  Found {len(results)} Google Play reviews.")
    return results

# ─── CSV MANAGER ──────────────────────────────────────────────────────────────

def save_to_csv(new_reviews):
    df_new = pd.DataFrame(new_reviews)

    if os.path.exists(OUTPUT_CSV):
        df_existing = pd.read_csv(OUTPUT_CSV)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined.drop_duplicates(subset=["source", "text"], keep="first", inplace=True)
    else:
        df_combined = df_new

    df_combined.sort_values("date", ascending=False, inplace=True)
    df_combined.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(df_combined)} total reviews to {OUTPUT_CSV}")
    return df_combined

# ─── HTML DASHBOARD ───────────────────────────────────────────────────────────

def generate_html(df):
    print("Generating HTML dashboard...")

    total = len(df)
    neg = len(df[df["sentiment"] == "Negative"])
    pos = len(df[df["sentiment"] == "Positive"])
    neu = len(df[df["sentiment"] == "Neutral"])
    avg_rating = round(df["rating"].mean(), 1) if total > 0 else 0
    support_count = len(df[df["support_related"] == True])

    # Chart data
    sentiment_counts = df["sentiment"].value_counts().to_dict()
    category_counts = df["category"].value_counts().head(8).to_dict()

    # Sentiment over time
    df["date"] = pd.to_datetime(df["date"])
    df_monthly = df.groupby([df["date"].dt.to_period("M"), "sentiment"]).size().unstack(fill_value=0)
    months = [str(p) for p in df_monthly.index]
    neg_trend = df_monthly.get("Negative", pd.Series([0]*len(months))).tolist()
    pos_trend = df_monthly.get("Positive", pd.Series([0]*len(months))).tolist()

    # Rating distribution
    rating_dist = df["rating"].value_counts().sort_index().to_dict()
    rating_labels = [f"{i} star" for i in range(1, 6)]
    rating_values = [rating_dist.get(i, 0) for i in range(1, 6)]

    # Reviews JSON for JS
    reviews_json = df[[
        "date", "source", "title", "text", "rating", "sentiment", "category", "support_related", "link"
    ]].copy()
    reviews_json["date"] = reviews_json["date"].astype(str)
    reviews_data = reviews_json.to_dict(orient="records")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nebula Support Reviews</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --bg: #ffffff; --bg2: #f5f5f4; --bg3: #efede8;
  --text: #1a1a18; --text2: #5f5e5a; --text3: #888780;
  --border: rgba(26,26,24,0.15); --border2: rgba(26,26,24,0.3);
  --blue: #185FA5; --blue-l: #E6F1FB;
  --green: #3B6D11; --green-l: #EAF3DE;
  --red: #A32D2D; --red-l: #FCEBEB;
  --amber: #633806; --amber-l: #FAEEDA;
  --radius: 8px; --radius-lg: 12px;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #1a1a18; --bg2: #242422; --bg3: #2c2c2a;
    --text: #f0ede8; --text2: #b4b2a9; --text3: #888780;
    --border: rgba(240,237,232,0.15); --border2: rgba(240,237,232,0.3);
    --blue-l: #0C447C; --green-l: #27500A; --red-l: #791F1F; --amber-l: #412402;
  }}
}}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg3); color: var(--text); font-size: 14px; line-height: 1.6; }}
header {{ background: var(--bg); border-bottom: 0.5px solid var(--border); padding: 0 24px; height: 52px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 10; }}
.logo {{ font-size: 14px; font-weight: 500; display: flex; align-items: center; gap: 8px; }}
.logo-dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--blue); }}
.meta {{ font-size: 12px; color: var(--text3); }}
main {{ max-width: 900px; margin: 0 auto; padding: 24px 20px; }}
.stats {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }}
.stat {{ background: var(--bg2); border-radius: var(--radius); padding: 1rem; flex: 1; min-width: 100px; text-align: center; }}
.stat-val {{ font-size: 22px; font-weight: 500; margin: 4px 0 2px; }}
.stat-lbl {{ font-size: 12px; color: var(--text2); }}
.charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-bottom: 16px; }}
.card {{ background: var(--bg); border: 0.5px solid var(--border); border-radius: var(--radius-lg); padding: 1rem 1.25rem; }}
.card-title {{ font-size: 13px; font-weight: 500; margin-bottom: 3px; }}
.card-sub {{ font-size: 12px; color: var(--text3); margin-bottom: 12px; }}
.chart-full {{ margin-bottom: 12px; }}
.filters {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; align-items: center; }}
.filter-btn {{ font-size: 12px; padding: 4px 10px; border-radius: 6px; cursor: pointer; border: 0.5px solid var(--border2); background: var(--bg); color: var(--text); font-family: inherit; }}
.filter-btn.active {{ background: var(--bg2); font-weight: 500; }}
.filter-label {{ font-size: 12px; color: var(--text3); }}
.review-count {{ font-size: 12px; color: var(--text3); margin-bottom: 10px; }}
.review {{ background: var(--bg); border: 0.5px solid var(--border); border-radius: var(--radius-lg); padding: 1rem 1.25rem; margin-bottom: 10px; }}
.review-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }}
.badges {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
.badge {{ font-size: 11px; padding: 2px 8px; border-radius: 6px; font-weight: 500; }}
.badge-tp {{ background: var(--blue-l); color: var(--blue); }}
.badge-gp {{ background: var(--green-l); color: var(--green); }}
.badge-neg {{ background: var(--red-l); color: var(--red); }}
.badge-pos {{ background: var(--green-l); color: var(--green); }}
.badge-neu {{ background: var(--amber-l); color: var(--amber); }}
.badge-cat {{ background: var(--bg2); color: var(--text2); border: 0.5px solid var(--border); }}
.review-date {{ font-size: 12px; color: var(--text3); white-space: nowrap; }}
.review-title {{ font-weight: 500; font-size: 14px; margin-bottom: 4px; }}
.review-text {{ font-size: 13px; color: var(--text2); line-height: 1.6; }}
.review-link {{ display: inline-block; margin-top: 8px; font-size: 12px; color: var(--blue); text-decoration: none; }}
.review-link:hover {{ text-decoration: underline; }}
.stars {{ color: #BA7517; font-size: 13px; letter-spacing: 1px; }}
.no-reviews {{ text-align: center; padding: 2rem; color: var(--text3); font-size: 13px; }}
footer {{ text-align: center; font-size: 12px; color: var(--text3); padding: 24px; border-top: 0.5px solid var(--border); margin-top: 24px; }}
</style>
</head>
<body>
<header>
  <div class="logo"><div class="logo-dot"></div>Nebula — support reviews</div>
  <div class="meta">Updated: {datetime.now().strftime("%d %b %Y")}</div>
</header>
<main>
  <div class="stats">
    <div class="stat"><div class="stat-val">{total}</div><div class="stat-lbl">Total reviews</div></div>
    <div class="stat"><div class="stat-val" style="color:var(--red)">{neg}</div><div class="stat-lbl">Negative</div></div>
    <div class="stat"><div class="stat-val" style="color:var(--green)">{pos}</div><div class="stat-lbl">Positive</div></div>
    <div class="stat"><div class="stat-val">{avg_rating}</div><div class="stat-lbl">Avg rating</div></div>
    <div class="stat"><div class="stat-val">{support_count}</div><div class="stat-lbl">Support related</div></div>
  </div>

  <div class="charts">
    <div class="card">
      <div class="card-title">Category breakdown</div>
      <div class="card-sub">Most common support issues</div>
      <canvas id="catChart" height="220"></canvas>
    </div>
    <div class="card">
      <div class="card-title">Rating distribution</div>
      <div class="card-sub">Star ratings across both sources</div>
      <canvas id="ratingChart" height="220"></canvas>
    </div>
  </div>

  <div class="card chart-full">
    <div class="card-title">Sentiment over time</div>
    <div class="card-sub">Monthly positive vs negative trend</div>
    <canvas id="trendChart" height="160"></canvas>
  </div>

  <div class="filters">
    <span class="filter-label">Source:</span>
    <button class="filter-btn active" onclick="filter('source','all',this)">All</button>
    <button class="filter-btn" onclick="filter('source','Trustpilot',this)">Trustpilot</button>
    <button class="filter-btn" onclick="filter('source','Google Play',this)">Google Play</button>
    <span class="filter-label" style="margin-left:8px">Sentiment:</span>
    <button class="filter-btn active" onclick="filter('sentiment','all',this)">All</button>
    <button class="filter-btn" onclick="filter('sentiment','Negative',this)">Negative</button>
    <button class="filter-btn" onclick="filter('sentiment','Positive',this)">Positive</button>
    <button class="filter-btn" onclick="filter('sentiment','Neutral',this)">Neutral</button>
    <span class="filter-label" style="margin-left:8px">Support only:</span>
    <button class="filter-btn active" onclick="filter('support','all',this)">All</button>
    <button class="filter-btn" onclick="filter('support','true',this)">Support related</button>
  </div>

  <div class="review-count" id="count">{total} reviews</div>
  <div id="reviews-list"></div>
</main>
<footer>Nebula support review tracker — data from Trustpilot &amp; Google Play</footer>

<script>
const ALL_REVIEWS = {json.dumps(reviews_data, ensure_ascii=False)};
let activeFilters = {{ source: 'all', sentiment: 'all', support: 'all' }};

function stars(n) {{
  return '★'.repeat(n) + '☆'.repeat(5 - n);
}}

function render(reviews) {{
  const container = document.getElementById('reviews-list');
  document.getElementById('count').textContent = reviews.length + ' reviews';
  if (reviews.length === 0) {{
    container.innerHTML = '<div class="no-reviews">No reviews match this filter.</div>';
    return;
  }}
  container.innerHTML = reviews.map(r => `
    <div class="review">
      <div class="review-header">
        <div class="badges">
          <span class="badge ${{r.source === 'Trustpilot' ? 'badge-tp' : 'badge-gp'}}">${{r.source}}</span>
          <span class="badge ${{r.sentiment === 'Negative' ? 'badge-neg' : r.sentiment === 'Positive' ? 'badge-pos' : 'badge-neu'}}">${{r.sentiment}}</span>
          <span class="badge badge-cat">${{r.category}}</span>
          <span class="stars">${{stars(r.rating)}}</span>
        </div>
        <span class="review-date">${{r.date}}</span>
      </div>
      ${{r.title ? `<div class="review-title">${{r.title}}</div>` : ''}}
      <div class="review-text">${{r.text}}</div>
      <a class="review-link" href="${{r.link}}" target="_blank" rel="noopener">View original →</a>
    </div>
  `).join('');
}}

function filter(type, value, btn) {{
  activeFilters[type] = value;
  btn.closest('.filters').querySelectorAll('.filter-btn').forEach(b => {{
    if (b.onclick.toString().includes(`'${{type}}'`)) b.classList.remove('active');
  }});
  btn.classList.add('active');
  applyFilters();
}}

function applyFilters() {{
  let filtered = ALL_REVIEWS;
  if (activeFilters.source !== 'all') filtered = filtered.filter(r => r.source === activeFilters.source);
  if (activeFilters.sentiment !== 'all') filtered = filtered.filter(r => r.sentiment === activeFilters.sentiment);
  if (activeFilters.support === 'true') filtered = filtered.filter(r => r.support_related === true);
  render(filtered);
}}

render(ALL_REVIEWS);

const catLabels = {json.dumps(list(category_counts.keys()))};
const catValues = {json.dumps(list(category_counts.values()))};
new Chart(document.getElementById('catChart'), {{
  type: 'bar',
  data: {{ labels: catLabels, datasets: [{{ data: catValues, backgroundColor: '#185FA5' }}] }},
  options: {{
    indexAxis: 'y', responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ font: {{ size: 11 }}, color: '#888780' }}, grid: {{ color: 'rgba(136,135,128,0.15)' }} }},
      y: {{ ticks: {{ font: {{ size: 11 }}, color: '#888780' }}, grid: {{ display: false }} }}
    }}
  }}
}});

new Chart(document.getElementById('ratingChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(rating_labels)},
    datasets: [{{ data: {json.dumps(rating_values)}, backgroundColor: ['#E24B4A','#E24B4A','#EF9F27','#639922','#185FA5'] }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ font: {{ size: 11 }}, color: '#888780' }}, grid: {{ display: false }} }},
      y: {{ ticks: {{ font: {{ size: 11 }}, color: '#888780' }}, grid: {{ color: 'rgba(136,135,128,0.15)' }} }}
    }}
  }}
}});

new Chart(document.getElementById('trendChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(months)},
    datasets: [
      {{ label: 'Negative', data: {json.dumps(neg_trend)}, borderColor: '#E24B4A', borderWidth: 2, pointRadius: 3, tension: 0.3, backgroundColor: 'transparent' }},
      {{ label: 'Positive', data: {json.dumps(pos_trend)}, borderColor: '#639922', borderWidth: 2, pointRadius: 3, tension: 0.3, backgroundColor: 'transparent' }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: 'bottom', labels: {{ font: {{ size: 11 }}, color: '#888780', boxWidth: 12 }} }} }},
    scales: {{
      x: {{ ticks: {{ font: {{ size: 11 }}, color: '#888780', maxTicksLimit: 8 }}, grid: {{ display: false }} }},
      y: {{ ticks: {{ font: {{ size: 11 }}, color: '#888780' }}, grid: {{ color: 'rgba(136,135,128,0.15)' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard saved to {OUTPUT_HTML}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"Nebula review collector — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    all_reviews = []

    tp_reviews = scrape_trustpilot()
    all_reviews.extend(tp_reviews)

    gp_reviews = scrape_google_play()
    all_reviews.extend(gp_reviews)

    if all_reviews:
        df = save_to_csv(all_reviews)
        generate_html(df)
        print(f"\nDone! Open {OUTPUT_HTML} in your browser to see the dashboard.")
    else:
        print("\nNo new reviews found today.")
        if os.path.exists(OUTPUT_CSV):
            df = pd.read_csv(OUTPUT_CSV)
            generate_html(df)
            print(f"Dashboard regenerated from existing data.")

if __name__ == "__main__":
    main()
