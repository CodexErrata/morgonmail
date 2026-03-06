# Morgonmail Setup

Runs automatically at 10:00 AM Vietnam time every day via GitHub Actions.
Your Mac can be off. You just need a private GitHub repo.

---

## Step 1 — Create a private GitHub repo

1. Go to https://github.com/new
2. Name it `morgonmail`, set to **Private**, click Create
3. Push this folder to it:

```bash
cd ~/Desktop/morgonmail
git init
git add .
git commit -m "init"
git remote add origin https://github.com/YOUR_USERNAME/morgonmail.git
git push -u origin main
```

---

## Step 2 — Google Cloud project (free, one-time)

1. Go to https://console.cloud.google.com → **New Project** → name it `morgonmail`
2. **APIs & Services → Library** → enable **Gmail API** and **Google Calendar API**
3. **APIs & Services → OAuth consent screen**
   - User type: **External** → Create
   - Fill in App name (`morgonmail`) and your email → Save through all steps
4. **APIs & Services → Credentials → + Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Desktop app** → Create
5. Download the JSON → rename it `credentials.json` → place in `~/Desktop/morgonmail/`

---

## Step 3 — Run locally once to authenticate

This opens a browser window to approve Google access and generates `token.json`.

```bash
cd ~/Desktop/morgonmail
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
ANTHROPIC_API_KEY=your_key_here python3 main.py
```

> Google will warn "This app isn't verified" — click **Advanced → Go to morgonmail (unsafe)**.
> This is your own personal app, it's fine.

After it runs successfully, you'll have `token.json` in the folder.

---

## Step 4 — Add secrets to GitHub

Go to your repo on GitHub → **Settings → Secrets and variables → Actions → New repository secret**

Add these three secrets:

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your key from https://console.anthropic.com/settings/keys |
| `GOOGLE_CREDENTIALS_JSON` | Paste the full contents of `credentials.json` |
| `GOOGLE_TOKEN_JSON` | Paste the full contents of `token.json` |

To get the file contents quickly:
```bash
cat ~/Desktop/morgonmail/credentials.json
cat ~/Desktop/morgonmail/token.json
```

---

## Step 5 — Test it

Push to GitHub, then go to your repo → **Actions → morgonmail → Run workflow**.
You should get an email within a minute.

---

## Daily use — editing tasks

`tasks.md` in the repo is your task list. Edit it, commit, push:

```bash
# edit tasks.md in any editor, then:
git add tasks.md
git commit -m "update tasks"
git push
```

Next morning's email will include the updated tasks.

Supported markdown:
- `- [ ] task` → checkbox
- `- [x] task` → done (greyed out)
- `- item` → bullet
- `# Heading` / `## Subheading`

---

## If Google auth ever breaks

The token refreshes itself automatically on every run. It stays valid as long as the
script runs at least once every 6 months (which it will, daily).

If it ever stops working (e.g. you revoke access), just re-run Step 3 locally,
then update the `GOOGLE_TOKEN_JSON` secret with the new `token.json` contents.

---

## Changing news sources or email

Edit `config.py`, commit, push. Changes take effect the next morning.
