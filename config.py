from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# Your email address — leave as "" to auto-detect from your Gmail account
RECIPIENT_EMAIL = ""

NEWS_SOURCES = [
    {"name": "Reuters",             "rss": "https://news.google.com/rss/search?q=when:24h+allinurl:reuters.com&ceid=US:en&hl=en-US&gl=US"},
    {"name": "Svenska Dagbladet",   "rss": "https://www.svd.se/feed/articles.rss"},
    {"name": "Aftonbladet",         "rss": "https://rss.aftonbladet.se/rss2/small/pages/sections/senastenytt/"},
]

BLOG_SOURCES = [
    {"name": "Gwern",            "rss": "https://www.gwern.net/atom.xml"},
    {"name": "Astral Codex Ten", "rss": "https://astralcodexten.substack.com/feed"},
    {"name": "Richard Hanania",  "rss": "https://www.richardhanania.com/feed"},
]

# Max articles to fetch per source before Claude filters them
MAX_ARTICLES_PER_SOURCE = 25

# Notion page IDs — get these from the page URLs (last part after the title)
NOTION_PRESSING_PAGE_ID  = "31b99631355d807683bdc656c177818b"
NOTION_LONGTERM_PAGE_ID  = "31b99631355d8015a8fae26743b4bf60"

CREDENTIALS_FILE = SCRIPT_DIR / "credentials.json"
TOKEN_FILE       = SCRIPT_DIR / "token.json"
LOG_FILE         = SCRIPT_DIR / "morgonmail.log"

TIMEZONE = "Asia/Ho_Chi_Minh"

# Location for weather — update when you travel (decimal degrees)
WEATHER_LAT = 10.8231   # Ho Chi Minh City
WEATHER_LON = 106.6297

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
