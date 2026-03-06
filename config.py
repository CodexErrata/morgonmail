from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# Your email address — leave as "" to auto-detect from your Gmail account
RECIPIENT_EMAIL = ""

NEWS_SOURCES = [
    {"name": "Reuters",             "rss": "https://news.google.com/rss/search?q=when:24h+allinurl:reuters.com&ceid=US:en&hl=en-US&gl=US"},
    {"name": "Svenska Dagbladet",   "rss": "https://www.svd.se/feed/articles.rss"},
    {"name": "Aftonbladet",         "rss": "https://rss.aftonbladet.se/rss2/small/pages/sections/senastenytt/"},
]

# Max articles to fetch per source before Claude filters them
MAX_ARTICLES_PER_SOURCE = 25

CREDENTIALS_FILE = SCRIPT_DIR / "credentials.json"
TOKEN_FILE       = SCRIPT_DIR / "token.json"
TASKS_FILE       = SCRIPT_DIR / "tasks.md"
LOG_FILE         = SCRIPT_DIR / "morgonmail.log"

TIMEZONE = "Asia/Ho_Chi_Minh"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
