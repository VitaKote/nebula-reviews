import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import json
import re
from google_play_scraper import reviews, Sort

TRUSTPILOT_URL = "https://www.trustpilot.com/review/asknebula.com"
GOOGLE_PLAY_APP_ID = "genesis.nebula"
OUTPUT_CSV = "reviews.csv"
OUTPUT_HTML = "index.html"
DAYS_BACK = 730

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

SUPPORT_KEYWORDS = [
    "support","help","chat","bot","response","reply","refund","payment",
    "cancel","subscription","waiting","slow","agent","contact","email",
    "ticket","issue","problem","complaint","payout","billing","charged","customer service"
]

CATEGORIES = {
    "Slow / no response":    ["slow","waiting","wait","days","hours","no reply","no response","never responded","ignored"],
    "Refund issues":         ["refund","money back","charged","charge","overcharged","stole","scam","fraud"],
    "Chatbot not working":   ["bot","chatbot","automated","useless bot","robot"],
    "Subscription / cancel": ["cancel","subscription","unsubscribe","auto-renew","renewal","recurring"],
    "Payment & billing":     ["payment","billing","invoice","payout","transaction","credit card"],
    "App bug / crash":       ["crash","bug","error","freeze","not working","broken","glitch"],
    "Support praised":       ["great support","helpful","amazing support","quick response","fast reply","resolved","excellent service"],
    "General complaint":     []
}

def categorize(text):
    t = text.lower()
    for cat, kws in CATEGORIES.items():
        if any(k in t for k in kws):
            return cat
    return "General complaint"

def get_sentiment(rating):
    if rating >= 4: return "Positive"
    if rating == 3: return "Neutral"
    return "Negative"

def is_support_related(text):
    return any(k in text.lower() for k in SUPPORT_KEYWORDS)

def days_ago(n):
    return datetime.now() - timedelta(days=n)

def scrape_trustpilot():
    print("Scraping Trustpilot...")
    results = []
    session = requests.Session()
    try:
        session.get("https://www.trustpilot.com", headers=HEADERS, timeout=15)
        time.sleep(2)
    except Exception:
        pass

    page = 1
    cutoff = days_ago(DAYS_BACK)

    while page <= 30:
        url = f"{TRUSTPILOT_URL}?page={page}&sort=recency"
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            print(f"  Page {page}: status {resp.status_code}")

            if resp.status_code == 403:
                print("  Blocked by Trustpilot. Trying JSON API...")
                api_url = f"https://www.trustpilot.com/api/categoriespages/get-business-unit/asknebula.com/reviews?page={page}&perPage=20&sortBy=recency&language=all"
                api_resp = session.get(api_url, headers={**HEADERS, "Accept": "application/json"}, timeout=20)
                if api_resp.status_code == 200:
                    data = api_resp.json()
                    review_list = data.get("reviews", [])
                    if not review_list:
                        break
                    for r in review_list:
                        try:
                            raw = r.get("dates", {}).get("publishedDate", "")[:10]
                            rdate = datetime.strptime(raw, "%Y-%m-%d") if raw else datetime.now()
                            if rdate < cutoff:
                                continue
                            rating = r.get("rating", {}).get("stars", 3)
                            text = r.get("text", "")
                            title = r.get("title", "")
                            link = "https://www.trustpilot.com/reviews/" + r.get("id", "")
                            if not text:
                                continue
                            results.append({
                                "date": rdate.strftime("%Y-%m-%d"),
                                "source": "Trustpilot",
                                "title": title, "text": text,
                                "rating": rating,
                                "sentiment": get_sentiment(rating),
                                "category": categorize(title + " " + text),
                                "support_related": is_support_related(title + " " + text),
                                "link": link
                            })
                        except Exception as e:
                            print(f"  Error: {e}")
                    page += 1
                    time.sleep(1.5)
                    continue
                else:
                    print(f"  API blocked ({api_resp.status_code}). Skipping Trustpilot.")
                    break

            if resp.status_code != 200:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            next_data = soup.find("script", id="__NEXT_DATA__")
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    review_list = data.get("props", {}).get("pageProps", {}).get("reviews", [])
                    if not review_list:
                        break
                    found_old = False
                    for r in review_list:
                        try:
                            raw = r.get("dates", {}).get("publishedDate", "")[:10]
                            rdate = datetime.strptime(raw, "%Y-%m-%d") if raw else datetime.now()
                            if rdate < cutoff:
                                found_old = True
                                continue
                            rating = r.get("rating", {}).get("stars", 3)
                            text = r.get("text", "")
                            title = r.get("title", "")
                            rid = r.get("id", "")
                            link = f"https://www.trustpilot.com/reviews/{rid}" if rid else TRUSTPILOT_URL
                            if not text:
                                continue
                            results.append({
                                "date": rdate.strftime("%Y-%m-%d"),
                                "source": "Trustpilot",
                                "title": title, "text": text,
                                "rating": rating,
                                "sentiment": get_sentiment(rating),
                                "category": categorize(title + " " + text),
                                "support_related": is_support_related(title + " " + text),
                                "link": link
                            })
                        except Exception as e:
                            print(f"  Error: {e}")
                    if found_old and DAYS_BACK <= 30:
                        break
                    page += 1
                    time.sleep(1.5)
                    continue
                except Exception as e:
                    print(f"  JSON error: {e}")

            break

        except Exception as e:
            print(f"  Request error: {e}")
            break

    print(f"  Found {len(results)} Trustpilot reviews.")
    return results

def scrape_google_play():
    print("Scraping Google Play...")
    results = []
    cutoff = days_ago(DAYS_BACK)

    try:
        all_rev = []
        token = None
        for batch in range(10):
            if token:
                result, token = reviews(GOOGLE_PLAY_APP_ID, lang="en", country="us", sort=Sort.NEWEST, count=200, continuation_token=token)
            else:
                result, token = reviews(GOOGLE_PLAY_APP_ID, lang="en", country="us", sort=Sort.NEWEST, count=200)
            if not result:
                break
            all_rev.extend(result)
            oldest = min((r["at"] for r in result if r.get("at")), default=datetime.now())
            if isinstance(oldest, str):
                oldest = datetime.strptime(oldest[:10], "%Y-%m-%d")
            if oldest < cutoff:
                break
            if not token:
                break
            time.sleep(1)

        print(f"  Fetched {len(all_rev)} Google Play reviews, filtering...")
        for r in all_rev:
            try:
                rdate = r["at"]
                if isinstance(rdate, str):
                    rdate = datetime.strptime(rdate[:10], "%Y-%m-%d")
                if rdate < cutoff:
                    continue
                text = r.get("content", "")
                if not text:
                    continue
                rating = r.get("score", 3)
                rid = r.get("reviewId", "")
                link = f"https://play.google.com/store/apps/details?id={GOOGLE_PLAY_APP_ID}&reviewId={rid}"
                results.append({
                    "date": rdate.strftime("%Y-%m-%d"),
                    "source": "Google Play",
                    "title": r.get("userName", ""),
                    "text": text, "rating": rating,
                    "sentiment": get_sentiment(rating),
                    "category": categorize(text),
                    "support_related": is_support_related(text),
                    "link": link
                })
            except Exception as e:
                print(f"  Error: {e}")
    except Exception as e:
        print(f"  Google Play error: {e}")

    print(f"  Found {len(results)} Google Play reviews.")
    return results

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

def generate_html(df):
    print("Generating HTML dashboard...")

    total = len(df)
    neg = len(df[df["sentiment"] == "Negative"])
    pos = len(df[df["sentiment"] == "Positive"])
    avg_rating = round(df["rating"].mean(), 1) if total > 0 else 0
    support_count = len(df[df["support_related"] == True])

    category_counts = df["category"].value_counts().head(8).to_dict()
    df["date"] = pd.to_datetime(df["date"])
    df_monthly = df.groupby([df["date"].dt.to_period("M"), "sentiment"]).size().unstack(fill_value=0)
    months = [str(p) for p in df_monthly.index]
    neg_trend = df_monthly.get("Negative", pd.Series([0]*len(months))).tolist()
    pos_trend = df_monthly.get("Positive", pd.Series([0]*len(months))).tolist()
    rating_dist = df["rating"].value_counts().sort_index().to_dict()
    rating_labels = [f"{i} star" for i in range(1, 6)]
    rating_values = [rating_dist.get(i, 0) for i in range(1, 6)]

    reviews_copy = df[["date","source","title","text","rating","sentiment","category","support_related","link"]].copy()
    reviews_copy["date"] = reviews_copy["date"].astype(str)
    reviews_data = reviews_copy.to_dict(orient="records")

    # Build chart JS strings separately to avoid f-string brace conflicts
    cat_labels_js = json.dumps(list(category_counts.keys()))
    cat_values_js = json.dumps(list(category_counts.values()))
    rating_labels_js = json.dumps(rating_labels)
    rating_values_js = json.dumps(rating_values)
    months_js = json.dumps(months)
    neg_trend_js = json.dumps(neg_trend)
    pos_trend_js = json.dumps(pos_trend)
    reviews_js = json.dumps(reviews_data, ensure_ascii=False)
    updated = datetime.now().strftime("%d %b %Y")

    html_parts = [
        """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nebula Support Reviews</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#ffffff;--bg2:#f5f5f4;--bg3:#efede8;--text:#1a1a18;--text2:#5f5e5a;--text3:#888780;--border:rgba(26,26,24,0.15);--border2:rgba(26,26,24,0.3);--blue:#185FA5;--blue-l:#E6F1FB;--green:#3B6D11;--green-l:#EAF3DE;--red:#A32D2D;--red-l:#FCEBEB;--amber:#633806;--amber-l:#FAEEDA;--r:8px;--rl:12px}
@media(prefers-color-scheme:dark){:root{--bg:#1a1a18;--bg2:#242422;--bg3:#2c2c2a;--text:#f0ede8;--text2:#b4b2a9;--text3:#888780;--border:rgba(240,237,232,0.15);--border2:rgba(240,237,232,0.3);--blue-l:#0C447C;--green-l:#27500A;--red-l:#791F1F;--amber-l:#412402}}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg3);color:var(--text);font-size:14px;line-height:1.6}
header{background:var(--bg);border-bottom:0.5px solid var(--border);padding:0 24px;height:52px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}
.logo{font-size:14px;font-weight:500;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--blue)}
main{max-width:900px;margin:0 auto;padding:24px 20px}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
.stat{background:var(--bg2);border-radius:var(--r);padding:1rem;flex:1;min-width:100px;text-align:center}
.sv{font-size:22px;font-weight:500;margin:4px 0 2px}
.sl{font-size:12px;color:var(--text2)}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-bottom:12px}
.card{background:var(--bg);border:0.5px solid var(--border);border-radius:var(--rl);padding:1rem 1.25rem;margin-bottom:12px}
.ct{font-size:13px;font-weight:500;margin-bottom:3px}
.cs{font-size:12px;color:var(--text3);margin-bottom:12px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center}
.fb{font-size:12px;padding:4px 10px;border-radius:6px;cursor:pointer;border:0.5px solid var(--border2);background:var(--bg);color:var(--text);font-family:inherit}
.fb.active{background:var(--bg2);font-weight:500}
.fl{font-size:12px;color:var(--text3)}
#count{font-size:12px;color:var(--text3);margin-bottom:10px}
.review{background:var(--bg);border:0.5px solid var(--border);border-radius:var(--rl);padding:1rem 1.25rem;margin-bottom:10px}
.rh{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:8px;flex-wrap:wrap}
.badges{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.badge{font-size:11px;padding:2px 8px;border-radius:6px;font-weight:500}
.btp{background:var(--blue-l);color:var(--blue)}
.bgp{background:var(--green-l);color:var(--green)}
.bneg{background:var(--red-l);color:var(--red)}
.bpos{background:var(--green-l);color:var(--green)}
.bneu{background:var(--amber-l);color:var(--amber)}
.bcat{background:var(--bg2);color:var(--text2);border:0.5px solid var(--border)}
.rd{font-size:12px;color:var(--text3);white-space:nowrap}
.rt{font-weight:500;font-size:14px;margin-bottom:4px}
.rx{font-size:13px;color:var(--text2);line-height:1.6}
.rl{display:inline-block;margin-top:8px;font-size:12px;color:var(--blue);text-decoration:none}
.rl:hover{text-decoration:underline}
.stars{color:#BA7517;font-size:13px;letter-spacing:1px}
.empty{text-align:center;padding:2rem;color:var(--text3);font-size:13px}
footer{text-align:center;font-size:12px;color:var(--text3);padding:24px;border-top:0.5px solid var(--border);margin-top:24px}
</style>
</head>
<body>
<header>
  <div class="logo"><div class="dot"></div>Nebula — support reviews</div>
  <span style="font-size:12px;color:var(--text3)">Updated: """,
        updated,
        """</span>
</header>
<main>
  <div class="stats">
    <div class="stat"><div class="sv">""", str(total), """</div><div class="sl">Total reviews</div></div>
    <div class="stat"><div class="sv" style="color:var(--red)">""", str(neg), """</div><div class="sl">Negative</div></div>
    <div class="stat"><div class="sv" style="color:var(--green)">""", str(pos), """</div><div class="sl">Positive</div></div>
    <div class="stat"><div class="sv">""", str(avg_rating), """</div><div class="sl">Avg rating</div></div>
    <div class="stat"><div class="sv">""", str(support_count), """</div><div class="sl">Support related</div></div>
  </div>
  <div class="charts">
    <div class="card"><div class="ct">Category breakdown</div><div class="cs">Most common support issues</div><canvas id="catChart" height="220"></canvas></div>
    <div class="card"><div class="ct">Rating distribution</div><div class="cs">Star ratings 1-5</div><canvas id="ratingChart" height="220"></canvas></div>
  </div>
  <div class="card"><div class="ct">Sentiment over time</div><div class="cs">Monthly positive vs negative</div><canvas id="trendChart" height="140"></canvas></div>
  <div class="filters">
    <span class="fl">Source:</span>
    <button class="fb active" onclick="setFilter('source','all',this)">All</button>
    <button class="fb" onclick="setFilter('source','Trustpilot',this)">Trustpilot</button>
    <button class="fb" onclick="setFilter('source','Google Play',this)">Google Play</button>
    <span class="fl" style="margin-left:8px">Sentiment:</span>
    <button class="fb active" onclick="setFilter('sentiment','all',this)">All</button>
    <button class="fb" onclick="setFilter('sentiment','Negative',this)">Negative</button>
    <button class="fb" onclick="setFilter('sentiment','Positive',this)">Positive</button>
    <button class="fb" onclick="setFilter('sentiment','Neutral',this)">Neutral</button>
    <span class="fl" style="margin-left:8px">Support:</span>
    <button class="fb active" onclick="setFilter('support','all',this)">All</button>
    <button class="fb" onclick="setFilter('support','true',this)">Support only</button>
  </div>
  <div id="count"></div>
  <div id="list"></div>
</main>
<footer>Nebula support review tracker — Trustpilot &amp; Google Play</footer>
<script>
const DATA=""",
        reviews_js,
        """;
const F={source:'all',sentiment:'all',support:'all'};
function stars(n){return'\u2605'.repeat(n)+'\u2606'.repeat(5-n)}
function render(rs){
  document.getElementById('count').textContent=rs.length+' reviews';
  document.getElementById('list').innerHTML=rs.length?rs.map(r=>`
    <div class="review">
      <div class="rh">
        <div class="badges">
          <span class="badge ${r.source==='Trustpilot'?'btp':'bgp'}">${r.source}</span>
          <span class="badge ${r.sentiment==='Negative'?'bneg':r.sentiment==='Positive'?'bpos':'bneu'}">${r.sentiment}</span>
          <span class="badge bcat">${r.category}</span>
          <span class="stars">${stars(r.rating)}</span>
        </div>
        <span class="rd">${r.date}</span>
      </div>
      ${r.title?`<div class="rt">${r.title}</div>`:''}
      <div class="rx">${r.text}</div>
      <a class="rl" href="${r.link}" target="_blank" rel="noopener">View original \u2192</a>
    </div>`).join(''):'<div class="empty">No reviews match this filter.</div>';
}
function setFilter(k,v,btn){
  F[k]=v;
  document.querySelectorAll('.filters .fb').forEach(b=>{
    try{if(b.getAttribute('onclick').includes("'"+k+"'"))b.classList.remove('active')}catch(e){}
  });
  btn.classList.add('active');
  apply();
}
function apply(){
  let r=DATA;
  if(F.source!=='all')r=r.filter(x=>x.source===F.source);
  if(F.sentiment!=='all')r=r.filter(x=>x.sentiment===F.sentiment);
  if(F.support==='true')r=r.filter(x=>x.support_related===true);
  render(r);
}
apply();
new Chart(document.getElementById('catChart'),{type:'bar',data:{labels:""",
        cat_labels_js,
        """,datasets:[{data:""",
        cat_values_js,
        """,backgroundColor:'#185FA5'}]},options:{indexAxis:'y',responsive:true,plugins:{legend:{display:false}},scales:{x:{ticks:{font:{size:11},color:'#888780'},grid:{color:'rgba(136,135,128,0.15)'}},y:{ticks:{font:{size:11},color:'#888780'},grid:{display:false}}}}});
new Chart(document.getElementById('ratingChart'),{type:'bar',data:{labels:""",
        rating_labels_js,
        """,datasets:[{data:""",
        rating_values_js,
        """,backgroundColor:['#E24B4A','#E24B4A','#EF9F27','#639922','#185FA5']}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{x:{ticks:{font:{size:11},color:'#888780'},grid:{display:false}},y:{ticks:{font:{size:11},color:'#888780'},grid:{color:'rgba(136,135,128,0.15)'}}}}});
new Chart(document.getElementById('trendChart'),{type:'line',data:{labels:""",
        months_js,
        """,datasets:[{label:'Negative',data:""",
        neg_trend_js,
        """,borderColor:'#E24B4A',borderWidth:2,pointRadius:2,tension:0.3,backgroundColor:'transparent'},{label:'Positive',data:""",
        pos_trend_js,
        """,borderColor:'#639922',borderWidth:2,pointRadius:2,tension:0.3,backgroundColor:'transparent'}]},options:{responsive:true,plugins:{legend:{position:'bottom',labels:{font:{size:11},color:'#888780',boxWidth:12}}},scales:{x:{ticks:{font:{size:11},color:'#888780',maxTicksLimit:8},grid:{display:false}},y:{ticks:{font:{size:11},color:'#888780'},grid:{color:'rgba(136,135,128,0.15)'}}}}});
</script>
</body>
</html>"""
    ]

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write("".join(html_parts))
    print(f"Dashboard saved to {OUTPUT_HTML}")

def main():
    print(f"\n{'='*50}")
    print(f"Nebula review collector — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    all_reviews = []
    all_reviews.extend(scrape_trustpilot())
    all_reviews.extend(scrape_google_play())

    if all_reviews:
        df = save_to_csv(all_reviews)
        generate_html(df)
        print(f"\nDone! Open {OUTPUT_HTML} in your browser.")
    else:
        print("\nNo new reviews found.")
        if os.path.exists(OUTPUT_CSV):
            df = pd.read_csv(OUTPUT_CSV)
            generate_html(df)
            print("Dashboard regenerated from existing data.")
        else:
            print("No existing data. Check scraper logs above.")

if __name__ == "__main__":
    main()
