#!/usr/bin/env python3
"""
morgonmail — daily morning briefing
Fetches geopolitical news, calendar events, and personal tasks, then emails a digest.
"""

import os
import sys
import base64
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import pytz
import anthropic
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import (
    RECIPIENT_EMAIL, NEWS_SOURCES, BLOG_SOURCES, MAX_ARTICLES_PER_SOURCE,
    CREDENTIALS_FILE, TOKEN_FILE, TASKS_FILE, LOG_FILE,
    TIMEZONE, GOOGLE_SCOPES, WEATHER_LAT, WEATHER_LON,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

WMO_CODES = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "icy fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    80: "showers", 81: "heavy showers", 82: "violent showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}

def fetch_weather():
    import urllib.request, json as _json
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
            f"&daily=weathercode,sunrise,sunset,temperature_2m_max,temperature_2m_min"
            f"&timezone={TIMEZONE}"
            f"&forecast_days=1"
        )
        with urllib.request.urlopen(url, timeout=10) as r:
            data = _json.loads(r.read())
        daily   = data["daily"]
        sunrise = datetime.fromisoformat(daily["sunrise"][0]).strftime("%H:%M")
        sunset  = datetime.fromisoformat(daily["sunset"][0]).strftime("%H:%M")
        desc    = WMO_CODES.get(daily["weathercode"][0], "unknown")
        t_max   = round(daily["temperature_2m_max"][0])
        t_min   = round(daily["temperature_2m_min"][0])
        return {"desc": desc, "sunrise": sunrise, "sunset": sunset, "max": t_max, "min": t_min}
    except Exception as e:
        log.warning(f"Weather fetch failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Google auth
# ---------------------------------------------------------------------------

def get_google_creds():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), GOOGLE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                log.error(
                    "credentials.json not found. Follow SETUP.md to create it."
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def get_my_email(creds):
    if RECIPIENT_EMAIL:
        return RECIPIENT_EMAIL
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

def fetch_news():
    articles = []
    for source in NEWS_SOURCES:
        try:
            feed = feedparser.parse(source["rss"])
            for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
                articles.append({
                    "source":    source["name"],
                    "title":     entry.get("title", "").strip(),
                    "summary":   entry.get("summary", entry.get("description", "")).strip(),
                    "link":      entry.get("link", ""),
                })
            log.info(f"  {source['name']}: {len(feed.entries[:MAX_ARTICLES_PER_SOURCE])} articles")
        except Exception as e:
            log.warning(f"  Failed to fetch {source['name']}: {e}")
    return articles


SOURCE_CAPS = {"Reuters": 2, "Svenska Dagbladet": 2, "Aftonbladet": 1}

def _apply_source_caps(articles):
    from collections import defaultdict
    counts = defaultdict(int)
    result = []
    for a in articles:
        cap = SOURCE_CAPS.get(a["source"], 99)
        if counts[a["source"]] < cap:
            result.append(a)
            counts[a["source"]] += 1
    return result


def filter_news(articles):
    """Use Claude Haiku to keep only major geopolitical/political events."""
    if not articles:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping Claude filter, returning all articles.")
        return articles

    numbered = "\n\n".join(
        f"[{i+1}] {a['source'].upper()}: {a['title']}"
        + (f"\n{a['summary'][:250]}" if a["summary"] else "")
        for i, a in enumerate(articles)
    )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": (
                    "You are an extremely selective news filter. Return ONLY the numbers of articles to KEEP.\n\n"
                    "SELECTION RULES:\n\n"
                    "1. GEOPOLITICS — keep only events genuinely major on a global scale:\n"
                    "   - Active military strikes, invasions, or significant escalations between states\n"
                    "   - A country's government falling, coup, or major political crisis\n"
                    "   - Nuclear developments\n"
                    "   - Major international agreements or total breakdown of diplomacy\n"
                    "   - Declarations of war or peace\n"
                    "   - Massive sanctions or blockades with global economic impact\n"
                    "   Exclude: talks/meetings, threats, speculation, human interest, anything merely 'developing'\n"
                    "   Source limits: at most 2 from Reuters, at most 2 from Svenska Dagbladet, at most 1 from Aftonbladet.\n\n"
                    "2. TOP STORY — exactly 1 additional article: the single most important or widely discussed "
                    "headline today, any topic. Skip if it would duplicate a geopolitics pick.\n\n"
                    "Respond with only comma-separated numbers. Example: 2,5,11\n\n"
                    f"Articles:\n{numbered}\n\nNumbers to keep:"
                ),
            }],
        )
        raw = resp.content[0].text.strip()
        if raw.lower() == "none":
            return []
        indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
        kept = [articles[i] for i in indices if 0 <= i < len(articles)]
        kept = _apply_source_caps(kept)
        log.info(f"  Claude kept {len(kept)} / {len(articles)} articles")
        return kept
    except Exception as e:
        log.warning(f"  Claude filter failed ({e}), returning all articles unfiltered.")
        return articles


# ---------------------------------------------------------------------------
# Blogs
# ---------------------------------------------------------------------------

def fetch_new_blog_posts():
    """Return blog posts published in the last 24 hours."""
    import time
    cutoff = time.time() - 24 * 3600
    new_posts = []
    for source in BLOG_SOURCES:
        try:
            feed = feedparser.parse(source["rss"])
            for entry in feed.entries:
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published and time.mktime(published) >= cutoff:
                    new_posts.append({
                        "source": source["name"],
                        "title":  entry.get("title", "Untitled").strip(),
                        "link":   entry.get("link", ""),
                    })
        except Exception as e:
            log.warning(f"  Failed to fetch {source['name']}: {e}")
    log.info(f"  {len(new_posts)} new blog post(s) in the last 24h")
    return new_posts


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def get_today_events(creds):
    try:
        service = build("calendar", "v3", credentials=creds)
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        day_start = now.replace(hour=0,  minute=0,  second=0,  microsecond=0)
        day_end   = now.replace(hour=23, minute=59, second=59, microsecond=0)
        result = service.events().list(
            calendarId="primary",
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return result.get("items", [])
    except Exception as e:
        log.warning(f"Calendar fetch failed: {e}")
        return []


def format_event_time(event):
    start = event["start"].get("dateTime", event["start"].get("date", ""))
    end   = event["end"].get("dateTime",   event["end"].get("date", ""))
    if "T" in start:
        tz = pytz.timezone(TIMEZONE)
        s = datetime.fromisoformat(start).astimezone(tz)
        e = datetime.fromisoformat(end).astimezone(tz)
        return f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')}"
    return "All day"


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def get_tasks():
    if not TASKS_FILE.exists():
        return ""
    return TASKS_FILE.read_text(encoding="utf-8").strip()


def render_tasks_html(md):
    if not md:
        return '<p>no tasks</p>'
    lines = md.splitlines()
    parts = []
    for line in lines:
        if line.startswith("# "):
            parts.append(f'<h3 style="margin:10px 0 4px;">{line[2:]}</h3>')
        elif line.startswith("## "):
            parts.append(f'<h4 style="margin:8px 0 3px;">{line[3:]}</h4>')
        elif line.startswith("- [x] ") or line.startswith("- [X] "):
            parts.append(f'<div style="margin:3px 0;text-decoration:line-through;">☑ {line[6:]}</div>')
        elif line.startswith("- [ ] "):
            parts.append(f'<div style="margin:3px 0;">☐ {line[6:]}</div>')
        elif line.startswith("- "):
            parts.append(f'<div style="margin:3px 0;">• {line[2:]}</div>')
        elif line.strip():
            parts.append(f'<div style="margin:3px 0;">{line}</div>')
        else:
            parts.append("<br>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Email composition
# ---------------------------------------------------------------------------

FONT  = "'Söhne Mono', 'SohneMono', ui-monospace, 'Cascadia Mono', 'SF Mono', monospace"
BLACK = "#000"

SECTION = f"""
<h2 style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;
           color:{BLACK};margin:32px 0 12px;padding-bottom:6px;
           border-bottom:1px solid {BLACK};font-family:{FONT};">{{title}}</h2>
"""

def build_html(articles, blog_posts, events, tasks_md, date_str, weather):
    # --- Weather ---
    if weather:
        weather_html = (
            f'<p style="margin:0;color:{BLACK};">'
            f'sunrise: {weather["sunrise"]} &nbsp;·&nbsp; sunset: {weather["sunset"]}<br>'
            f'{weather["desc"]} &nbsp;·&nbsp; {weather["min"]}–{weather["max"]}°C'
            f'</p>'
        )
    else:
        weather_html = f'<p style="color:{BLACK};">unavailable</p>'

    # --- News ---
    if articles:
        news_items = []
        for a in articles:
            news_items.append(
                f'<div style="margin-bottom:10px;">'
                f'<span style="font-size:10px;color:{BLACK};text-transform:uppercase;">{a["source"]}</span><br>'
                f'<a href="{a["link"]}" style="color:{BLACK};text-decoration:none;">'
                f'{a["title"]}</a>'
                f'</div>'
            )
        news_html = "\n".join(news_items)
    else:
        news_html = f'<p style="color:{BLACK};">no major news today</p>'

    # --- Calendar ---
    if events:
        cal_items = []
        for ev in events:
            time_str = format_event_time(ev)
            title    = ev.get("summary", "Untitled")
            location = ev.get("location", "")
            loc_str  = f" @ {location}" if location else ""
            cal_items.append(
                f'<div style="margin-bottom:6px;color:{BLACK};">'
                f'{time_str} &nbsp; {title}{loc_str}'
                f'</div>'
            )
        cal_html = "\n".join(cal_items)
    else:
        cal_html = f'<p style="color:{BLACK};">nothing scheduled</p>'

    # --- Blogs ---
    if blog_posts:
        blog_items = []
        for p in blog_posts:
            blog_items.append(
                f'<div style="margin-bottom:6px;">'
                f'<span style="font-size:10px;color:{BLACK};text-transform:uppercase;">{p["source"]}</span><br>'
                f'<a href="{p["link"]}" style="color:{BLACK};text-decoration:none;">{p["title"]}</a>'
                f'</div>'
            )
        blogs_html = "\n".join(blog_items)
    else:
        blogs_html = f'<p style="color:{BLACK};">no new posts</p>'

    tasks_html = render_tasks_html(tasks_md)

    return f"""<html><body style="font-family:{FONT};max-width:600px;margin:0 auto;padding:28px 24px;color:{BLACK};">
  <h1 style="font-size:18px;margin:0 0 2px;font-weight:normal;font-family:{FONT};">morgonmail</h1>
  <p style="font-size:12px;margin:0 0 0;color:{BLACK};">{date_str}</p>

  {SECTION.format(title="weather")}
  {weather_html}

  {SECTION.format(title="news")}
  {news_html}

  {SECTION.format(title="blogs")}
  {blogs_html}

  {SECTION.format(title="today")}
  {cal_html}

  {SECTION.format(title="tasks")}
  {tasks_html}

</body></html>"""


def send_email(creds, recipient, subject, html_body):
    service = build("gmail", "v1", credentials=creds)
    msg = MIMEMultipart("alternative")
    msg["to"]      = recipient
    msg["subject"] = subject
    msg.attach(MIMEText(html_body, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("=== morgonmail starting ===")

    creds = get_google_creds()
    recipient = get_my_email(creds)
    log.info(f"Sending to: {recipient}")

    log.info("Fetching news...")
    articles = fetch_news()
    log.info(f"Filtering {len(articles)} articles with Claude...")
    filtered = filter_news(articles)

    log.info("Fetching weather...")
    weather = fetch_weather()

    log.info("Fetching blog posts...")
    blog_posts = fetch_new_blog_posts()

    log.info("Reading calendar...")
    events = get_today_events(creds)
    log.info(f"  {len(events)} event(s) today")

    log.info("Reading tasks...")
    tasks = get_tasks()

    tz       = pytz.timezone(TIMEZONE)
    now      = datetime.now(tz)
    date_str = now.strftime("%A, %-d %B %Y")
    subject  = f"Morgonmail – {now.strftime('%-d %b')}"

    html = build_html(filtered, blog_posts, events, tasks, date_str, weather)

    log.info("Sending email...")
    send_email(creds, recipient, subject, html)
    log.info("Done.")


if __name__ == "__main__":
    main()
