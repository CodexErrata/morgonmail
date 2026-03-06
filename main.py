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
    TIMEZONE, GOOGLE_SCOPES,
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
                    "You are an extremely selective news filter for someone who only wants the most significant world events. "
                    "Return ONLY the numbers of articles to KEEP. Return at most 6 articles — fewer if the news is quiet.\n\n"
                    "KEEP only events that are genuinely major on a global scale:\n"
                    "- Active military strikes, invasions, or significant escalations between states\n"
                    "- A country's government falling, coup, or major political crisis\n"
                    "- Nuclear developments\n"
                    "- Major international agreements or total breakdown of diplomacy\n"
                    "- Declarations of war or peace\n"
                    "- Massive sanctions or blockades with global economic impact\n\n"
                    "REMOVE everything else, including:\n"
                    "- Diplomatic meetings, talks, negotiations, or statements (unless a deal is actually signed)\n"
                    "- Elections unless a result has been decided and is significant\n"
                    "- Threats, warnings, or speculation about future events\n"
                    "- Human interest, personal stories, casualties/survivor stories\n"
                    "- Business, markets, sports, entertainment, crime, opinion\n"
                    "- Anything that is merely 'developing' without a concrete event having occurred\n\n"
                    "Respond with only comma-separated numbers. If nothing qualifies, respond with: none\n\n"
                    f"Articles:\n{numbered}\n\nNumbers to keep:"
                ),
            }],
        )
        raw = resp.content[0].text.strip()
        if raw.lower() == "none":
            return []
        indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
        kept = [articles[i] for i in indices if 0 <= i < len(articles)]
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
        return '<p style="color:#999;">No tasks.</p>'
    lines = md.splitlines()
    parts = []
    for line in lines:
        if line.startswith("# "):
            parts.append(f'<h3 style="margin:10px 0 4px;">{line[2:]}</h3>')
        elif line.startswith("## "):
            parts.append(f'<h4 style="margin:8px 0 3px;">{line[3:]}</h4>')
        elif line.startswith("- [x] ") or line.startswith("- [X] "):
            parts.append(
                f'<div style="margin:3px 0;color:#aaa;text-decoration:line-through;">☑ {line[6:]}</div>'
            )
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

SECTION = """
<h2 style="font-size:11px;text-transform:uppercase;letter-spacing:1.5px;
           color:#999;margin:32px 0 14px;padding-bottom:8px;
           border-bottom:2px solid #f0f0f0;">{title}</h2>
"""

def build_html(articles, blog_posts, events, tasks_md, date_str):
    # --- News ---
    if articles:
        news_items = []
        for a in articles:
            summary_html = (
                f'<p style="font-size:13px;color:#666;margin:4px 0 0;">'
                f'{a["summary"][:220]}…</p>'
                if a["summary"] else ""
            )
            news_items.append(
                f'<div style="margin-bottom:18px;padding-bottom:18px;border-bottom:1px solid #f0f0f0;">'
                f'<span style="font-size:10px;color:#aaa;text-transform:uppercase;">{a["source"]}</span><br>'
                f'<a href="{a["link"]}" style="font-size:15px;font-weight:600;color:#111;text-decoration:none;">'
                f'{a["title"]}</a>'
                f'{summary_html}'
                f'</div>'
            )
        news_html = "\n".join(news_items)
    else:
        news_html = '<p style="color:#999;">No major geopolitical news today.</p>'

    # --- Calendar ---
    if events:
        cal_items = []
        for ev in events:
            time_str  = format_event_time(ev)
            title     = ev.get("summary", "Untitled")
            location  = ev.get("location", "")
            loc_html  = (
                f' <span style="font-size:12px;color:#aaa;">@ {location}</span>'
                if location else ""
            )
            cal_items.append(
                f'<div style="margin-bottom:8px;">'
                f'<span style="font-weight:600;color:#333;min-width:100px;display:inline-block;">{time_str}</span>'
                f'<span style="color:#111;">{title}</span>{loc_html}'
                f'</div>'
            )
        cal_html = "\n".join(cal_items)
    else:
        cal_html = '<p style="color:#999;">Nothing on the calendar today.</p>'

    # --- Blogs ---
    if blog_posts:
        blog_items = []
        for p in blog_posts:
            blog_items.append(
                f'<div style="margin-bottom:8px;">'
                f'<span style="font-size:10px;color:#aaa;text-transform:uppercase;">{p["source"]}</span> '
                f'<a href="{p["link"]}" style="color:#111;text-decoration:none;">{p["title"]}</a>'
                f'</div>'
            )
        blogs_html = "\n".join(blog_items)
    else:
        blogs_html = '<p style="color:#999;">No new posts.</p>'

    tasks_html = render_tasks_html(tasks_md)

    return f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                      max-width:620px;margin:0 auto;padding:28px 24px;color:#111;">
  <h1 style="font-size:24px;margin:0 0 2px;font-weight:700;">Morgonmail</h1>
  <p style="color:#aaa;font-size:13px;margin:0 0 0;">{date_str}</p>

  {SECTION.format(title="News")}
  {news_html}

  {SECTION.format(title="Blogs")}
  {blogs_html}

  {SECTION.format(title="Today")}
  {cal_html}

  {SECTION.format(title="Tasks")}
  {tasks_html}

  <p style="margin-top:40px;font-size:11px;color:#ccc;">morgonmail</p>
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

    html = build_html(filtered, blog_posts, events, tasks, date_str)

    log.info("Sending email...")
    send_email(creds, recipient, subject, html)
    log.info("Done.")


if __name__ == "__main__":
    main()
