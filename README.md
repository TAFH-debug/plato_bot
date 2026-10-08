# PLATO Telegram bot

Telegram bot for **PLATO** (`plato.pusan.ac.kr`), the Moodle LMS of Pusan National University.
Assignments, deadlines, grades and reminders — without opening the site.

## What it does

| Feature | Command |
|---|---|
| What is due, with countdowns and urgency colours | `/deadlines [days]` |
| Assignments split into open / submitted / graded | `/assignments` |
| Active courses → contents, assignments, grades | `/courses` |
| Course totals and item-level grades with feedback | `/grades` |
| Deadline reminders (default 1 day / 3 h / 1 h before) | `/settings` |
| Daily digest of the next 3 days at a chosen hour | `/settings` |
| PLATO notifications forwarded to Telegram | `/settings` |
| Drop the cache and refetch | `/sync` |
| Delete token + all stored data | `/logout` |

## How it talks to PLATO

PLATO keeps Moodle's mobile web service enabled, so the bot uses the **official REST API**
rather than scraping HTML:

- `POST /login/token.php` — exchanges ID + password once for a web-service token
- `POST /webservice/rest/server.php` — `core_calendar_get_action_events_by_timesort`,
  `mod_assign_get_assignments`, `mod_assign_get_submission_status`,
  `gradereport_user_get_grade_items`, `message_popup_get_popup_notifications`, …

**The password is never stored.** The login message is deleted from the chat immediately,
and only the resulting token is kept, encrypted with Fernet (`.secret.key` or `FERNET_KEY`).
`/logout` deletes the row entirely.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on Linux/macOS
pip install -r requirements.txt

cp .env.example .env            # put your @BotFather token in BOT_TOKEN
python run.py
```

Optional — generate a stable encryption key instead of the auto-created `.secret.key`:

```bash
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
```

### Configuration (`.env`)

| Key | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | — | Telegram bot token (required) |
| `PLATO_URL` | `https://plato.pusan.ac.kr` | any Moodle site works |
| `FERNET_KEY` | auto | token-encryption key (else `DATA_DIR/.secret.key`) |
| `DATA_DIR` | volume mount, else project root | holds the DB and `.secret.key` |
| `DB_PATH` | `plato_bot.sqlite3` | SQLite file, relative to `DATA_DIR` |
| `TIMEZONE` | `Asia/Seoul` | used for all displayed times |
| `DEFAULT_LEADS` | `1440,180,60` | reminder lead times, minutes |
| `CHECK_INTERVAL_MIN` | `10` | how often the deadline watcher runs |

## Railway

Attach a volume to the service (e.g. mounted at `/data`). Railway exports
`RAILWAY_VOLUME_MOUNT_PATH`, so the DB and `.secret.key` land there and survive redeploys.

Restore a backup into the volume (key and DB must be from the same install):

```bash
railway volume files upload ./.secret.key /.secret.key
railway volume files upload ./plato_bot.sqlite3 /plato_bot.sqlite3
railway redeploy
```

Download a backup the same way with `railway volume files download`.

## Tests

```bash
python selftest.py          # fake PLATO: client, storage, rendering, reminder logic
python selftest.py --live   # also checks the real token endpoint answers
```

## Layout

```
run.py               entry point
plato/config.py      env config
plato/moodle.py      async Moodle web-service client
plato/services.py    shared http client, storage, token vault, per-user clients
plato/db.py          SQLite: users, prefs, reminder bookkeeping
plato/views.py       fetch + render (shared by handlers and scheduler)
plato/formatting.py  escaping, dates, countdowns, icons
plato/keyboards.py   menus
plato/handlers/      auth, browse, prefs routers
plato/reminders.py   APScheduler jobs: deadlines, digest, notifications
```

## Notes and limits

- Reminders fire at most once per deadline per lead time; wider windows are suppressed
  once a nearer one has been sent, so re-linking never floods you.
- Assignment submission status costs one API call per assignment, capped at 30 per request.
- If a token stops working (password change, site maintenance), the bot pauses reminders
  and asks you to `/login` again.
- Each Telegram user links their own PLATO account; the bot holds no shared credentials.
- Korean course names are shown exactly as PLATO returns them; the UI itself is English.
