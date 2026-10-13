# SocialHub PR — Multi-Platform Social Media Command Center

A local, zero-dependency (stdlib HTTP server) dashboard that turns your machine
into a full PR company: multi-account posting, AI SEO, humanized comment
automation, reel research, live analytics, monitoring with sentiment, crisis
response plans, and a CEO + co-workers agent company — all driven by typing a
task in plain language.

Part of the **DailyVideoBot** project — lives in the project root
(any OS; paths are relative, only Windows needs `.venv\Scripts\python.exe`,
macOS/Linux use `.venv/bin/python`)..

---

## Quick Start

```
.venv\Scripts\python.exe social_hub.py
```

Then open **http://localhost:8090** (localhost-only — credentials never touch the LAN).

---

## Features

### 1. Accounts — multi-account per platform
| Platform | Accounts | Credential types |
|----------|----------|------------------|
| Instagram | unlimited (each with its own name/label) | Graph API token, or username+password (browser) |
| YouTube | unlimited | OAuth token file (API), or Google email+password (browser) |
| Facebook | unlimited | Page token (API), or email+password (browser) |
| X (Twitter) | unlimited | username+password (**free** via twikit), or bearer token (paid API) |
| Bluesky | unlimited | handle + app password (**free** official atproto API) |
| Telegram | unlimited | bot token (**free** official bot API) |
| LinkedIn | unlimited | access token + org URN (needs Marketing API approval) |
| TikTok / Threads / Pinterest | unlimited | browser (official APIs approval-gated) |

Each account has a **local label + description + profile link** (e.g.
"Celebrity Gossip — This account for celebrity gossips") so you always know
which account posts. Labels never touch the real platform name.

- **Add / Edit / Remove** accounts from the UI (Edit is a JSON prompt: name,
  description, link)
- **Open** button → launches the profile in your default browser
- **Import**: bulk-import from an Excel/CSV file (see `import` note below)

### 2. Create Post — pick a video, everything else is automatic
1. **File picker** (no path typing): pick a video → it uploads to the
   dashboard → **auto-analyzed with ffprobe** (duration, resolution, codec,
   vertical/horizontal) → **type auto-set** (Instagram: reels ≤90s vertical;
   YouTube: shorts ≤180s vertical) → **AI SEO auto-runs** if the title is empty
2. **✨ AI SEO** button — rewrites the raw title/description at any time
3. **📤 Post (API)** — Graph API (Instagram), OAuth (YouTube), Page API (Facebook)
4. **🌐 Post (Browser)** — visible Chromium for accounts without API access

### 3. Multi-Post — different title/description per account
- **Checkboxes**: tick which accounts post
- Each account gets its OWN unique title + description (seeded per account —
  different power word + CTA, always video-related, never identical)
- One browser at a time, human-supervised each step

### 4. AI SEO Optimizer
- **Content-aware**: detects the real category from your raw text (comedy,
  AI, story, food, gaming, fitness, travel, ... 14 categories) — hashtags
  match the content, never a blanket `#ai`
- **2026 best practice**: 3–8 focused hashtags, best tags first
- **Live trending layer**: top universal tags right now
  (`#viral #reels #trending #explore #fyp`) + tags **learned from real viral
  reels** + per-category 2026 tags
- **Genre trends (SCrawler-style)**: type `gaming` → genre hashtags +
  what's trending NOW (live news keywords) + current headlines

### 5. Humanized Comment Automation
- Give a raw idea → generates **varied, natural comments** (different tones,
  emojis, filler words — never identical text)
- **Multi-account**: each account gets a DIFFERENT comment
- **Comment via browser** (one account): visible Chromium → you handle
  login/2FA → it types + posts the comment
- Works on Instagram, YouTube, Facebook
- **Natural browsing first**: every browser action scrolls the platform feed
  briefly before hitting the target — a real session, not a bot

### 6. Watch from accounts (research, not botting)
- Select accounts → each opens the linked video **one browser at a time**,
  logged in as that account, browsing naturally first
- You watch from each account, press Enter when done

### 7. Learn from reels
- Paste a reel URL → **analyzes**: which hashtags it uses, views/likes/
  comments counts, and **insights** ("High like-rate — strong hook",
  "Uses only 5 focused hashtags (2026 best practice)")
- **Check one box** → its hashtags are saved into `trending_tags.json` →
  future AI SEO automatically learns from what's actually working

### 8. 🎯 PR Team — fully agentic
| Role | What it does |
|------|-------------|
| 📊 **Analyst** | REAL analytics: IG insights, YT subscribers/views, FB followers |
| 🔍 **Research** | Live mentions + sentiment scoring (positive/negative/neutral) |
| ✍️ **Content Writer** | 4-day content calendar + IG/YT sample posts |
| 🚨 **Media Handler** | 5-phase crisis plan + press release + sample response posts |
| 🤝 **Community Manager** | Finds which communities/outlets discuss your topic |
| 📝 **Strategy doc** | Full markdown PR strategy: assets, channels, 2-week plan, KPIs |
| ⚡ **FULL package** | All of the above for one topic, one click |

Buttons: Analytics · Monitor mentions · Communities · Crisis plan ·
Strategy doc · FULL PR package · 🔑 Refresh IG token

### 9. 🏢 Company — CEO + co-workers
Give the CEO a goal → it **delegates like a real company**:
- Breaks the goal into work items, assigns each co-worker
- Every co-worker does real work (live data + generators)
- CEO synthesizes the final call + action items
- **Auto-prioritization**: if sentiment is NEGATIVE, the crisis plan runs
  BEFORE promo content

### 10. 🤖 Chat Tasks — just type a task
- **Quick-action buttons**: ⚡ Full campaign · 🔍 Scout opportunities ·
  📈 Grow account · 🚨 Crisis plan · 📊 Analytics · 🌐 Open account
- Or type ANYTHING (`bigboss win scout op`, `grow the_talk_tommorow`) →
  the agents do all the work
- Understands: `comment <text> on <url> with <accounts>`, `open <account>`,
  `post <title> to <account>`, campaign/grow/scout phrasing — anything else
  runs the full company
- Enter runs the task (no button needed)

### 11. Real analytics with token-expired fallback
- Graph API tried first (real insights: reach, impressions)
- **Token expired? → automatic browser fallback**: headlessly scrapes the
  public profile (followers/following/posts) — never dead-ends
- Results show `mode: browser` + why

### 12. 💻 Fleet — every agent on its own laptop
- A pane per agent (CEO, Analyst, Research, Writer, Media Handler,
  Community Mgr, Reviewer) styled like a mini laptop screen: live status
  dot, runs count, last run, **explicit permissions** per role
- **Live event feed**: the full observability timeline (job starts/ends,
  canary results, cron runs) from the events table
- **🩺 Canary run**: dry-run selector health checks (no logins) —
  failures land in the event feed so you see when a platform changed
  its DOM (like IG's 2026 login form)

### 13. 📅 Calendar — drag-drop rescheduling
- Lists every scheduled post; drag a date = **updates one row's
  scheduled_at** (thin — the scheduler stays the single source of truth)

### 14. 🥊 Competitor tracking
- Handles → **snapshot through the same job queue** (never blocks)
- Public profile scrape (no login): followers + posts → **time-series
  metrics** (every snapshot INSERTs; growth curves come free)
- Per-run cap = rate limit; cron-ready

### 15. SQLite (replaces scattered JSON)
- `hub.db` (stdlib sqlite3, WAL): accounts, posts, jobs, metrics
  (variant_id/experiment_id/post_id for **A/B testing**), events,
  agent_runs, trends_history, competitors
- Job runner, observability, A/B time-series all queryable from one DB

### 16. Compliance + Reviewer (trust boundaries)
- Every post/comment passes the **Reviewer gate** before the queue:
  banned words/topics, disclosure labels (#ad for sponsored), music flags
- Per-account `banned_topics` + voice guide + content pillars
- Role guardrails: Analyst read-only, Media Handler draft-only,
  publishing stays human-approved
- Error taxonomy routes failures: expired token / checkpoint / rate
  limit / selector changed / bad credentials → each to its fix
- **--dry_run** on Multi-Post: shows the plan, posts nothing

### 17. LLM resilience
- Two tiers: **fast** model (SEO, classification, comments) +
  **strong** model (CEO decisions, strategy) — `LLM_MODEL_FAST` /
  `LLM_MODEL_STRONG` in `.env`
- **Groq fallback**: when NVIDIA fails, the free Groq LLM
  (gpt-oss-120b) answers automatically — nothing dead-ends
- **Whisper transcription (Groq)**: any video → spoken content
  (any language) → keywords feed the Learn insights. Competitor
  VIDEO transcripts unlock what they actually SAY.
- Reasoning-model JSON extraction (balanced-brace scan, rejects
  `...` placeholders), 240s timeout, template fallback — nothing dead-ends

### 18. 📥 Unified Inbox + Reply agent
- **Fetch via browser** (frontend path — no token needed): visible
  Chromium → scrapes the account's notifications (comments, mentions,
  follows) → stored in the `inbox` table, deduped
- One place: comments/DMs/mentions across accounts, filter by status
- **Reply agent**: writes replies in the account's voice guide (LLM
  strong tier), Reviewer gates them, posts via visible browser
  (human-supervised) — highest-ROI growth, fully legitimate

### 19. ♻️ Growth loop
- **Content repurposing**: ONE long video → auto-cut vertical shorts
  (ffmpeg, ~40s windows) + per-cut captions + thread + carousel plan +
  quote card → cuts auto-posted to accounts via the job queue (rate-
  capped). Multiplies output with no extra shooting.
- **Trend-to-content ideas**: trends_history + competitor data + live
  news → "here are 5 hooks" (real, timely hooks from headlines)
- **Weekly CEO report**: one page — growth, best/worst posts, what the
  agents learned, next week's plan → send to Telegram (bot token)
- **Feedback loop (the learning piece)**: after 24h/7d, each post is
  scored vs the account's baseline; winning hooks/topics/hashtags are
  written to the lessons table + trending — **SEO and the CEO read
  them automatically**. This is what makes the system improve over time.

---

## How It Works

### Architecture
```
social_hub.py          ← stdlib HTTP server + embedded professional UI
                          (ThreadingHTTPServer, :8090, localhost only)
   ├── social_platforms.py   ← one poster function per platform (API paths)
   ├── browser_poster.py     ← visible-Chromium posting (IG/YT/Facebook)
   │                            + multi-account posting jobs
   ├── browser_commenter.py  ← visible-Chromium commenting/watching
   │                            (multi-account, natural browsing first)
   ├── ai_engine.py          ← content-aware SEO + humanized comments
   │                            (LLM first, template fallback)
   ├── llm.py                ← ONE shared LLM client (NVIDIA NIM)
   ├── tasks.py              ← natural-language task parser
   ├── company.py            ← CEO + co-workers orchestration
   ├── pr_team.py            ← analytics / monitoring / crisis / strategy
   └── reel_learner.py       ← reel analysis + hashtag learning
```

### The LLM (one place, every feature)
- `llm.py` — NVIDIA NIM, OpenAI-compatible, model **z-ai/glm-5.3-flash**
- Handles reasoning models: extracts the last valid JSON from reasoning text
  (models echo the prompt's template JSON — balanced-brace scan + rejects
  `...` placeholders), 240s timeout, `reasoning_content` fallback
- SEO, comments, CEO decisions, task parsing all read this one client
- Template fallback means nothing dead-ends when the LLM is slow/offline

### Browser automation (2026 login form)
Instagram's login changed: username field is `name='email'`, password is
`name='pass'`, and the real submit input is hidden — **Enter submits**.
All login flows use the combined selector + Enter method.

### Data sources (free, real)
- **Google News RSS** — live mentions (works everywhere; Reddit's JSON API
  is IP-blocked)
- **Reddit** — public JSON API when the IP allows; OpenCLI (login state)
  path installed
- **ffprobe** — video analysis
- **Graph API / YouTube Data API** — real stats when tokens are valid

---

## Configuration

### `.env` (local secrets — never commit)
```
INSTAGRAM_GRAPH_TOKEN=...     # long-lived IG token (60 days — expires!)
INSTAGRAM_IG_ID=...           # IG Business user id
INSTAGRAM_APP_ID=...          # for token refresh (must be valid)
INSTAGRAM_APP_SECRET=...
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_API_KEY=nvapi-...
LLM_MODEL=z-ai/glm-5.3-flash
```

### State files
| File | What |
|------|------|
| `social_accounts.json` | all accounts + credentials (plaintext — local only) |
| `trending_tags.json` | live trending + learned hashtags (SEO reads this) |
| `account_test_results.json` | last login test for every account |
| `uploads/` | videos you picked in the dashboard |

### Import accounts from a file
Accounts were bulk-imported from `Downloads\Book1.xlsx` (columns: No,
Platform, Mail id, username, password) via openpyxl — 10 PR accounts, all
login-tested **OK**.

---

## API Reference (all POST unless noted)

| Endpoint | What |
|----------|------|
| `GET /api/health` | server status |
| `GET /api/accounts` | all accounts |
| `GET /api/llm-status` | LLM live check (model + ok) |
| `/api/accounts`, `/api/accounts/delete`, `/api/accounts/edit` | account CRUD |
| `/api/open-account` | open profile in default browser |
| `/api/upload` | multipart video upload → ffprobe analysis |
| `/api/seo` | AI SEO (accepts `seed` for per-account uniqueness) |
| `/api/genre-trends` | genre hashtags + live trending keywords |
| `/api/comments` | generate humanized comments |
| `/api/comments/post` | queue generated comments |
| `/api/comment-browser` | comment from ONE account (visible browser) |
| `/api/watch-multi` | watch a video from each account (research) |
| `/api/comment-multi` | unique comment per account (human-supervised) |
| `/api/post-multi` | post to many accounts, unique title/desc each |
| `/api/post`, `/api/post-browser` | single post (API / browser) |
| `/api/learn-reel` | analyze a reel + optionally save its hashtags |
| `/api/pr/analytics`, `/api/pr/monitor`, `/api/pr/crisis`, `/api/pr/strategy`, `/api/pr/full` | PR team |
| `/api/company` | CEO + co-workers run |
| `/api/task` | natural-language task → agents do everything |
| `/api/refresh-token` | exchange IG token for a fresh 60-day one |
| `/api/jobs`, `/api/jobs/cancel` | job queue status + cancel |
| `/api/fleet` | agent laptops + event feed |
| `/api/calendar`, `/api/reschedule` | scheduled posts + drag-drop move |
| `/api/canary` | selector health checks (dry-run) |
| `/api/competitors`, `/api/competitor-cron` | competitor snapshots (job queue) |
| `/api/migrate` | migrate accounts JSON → SQLite |

---

## Known Limitations (honest)

| Blocker | Status / fix |
|---------|--------------|
| IG Graph token expires every ~60 days | Browser fallback covers analytics; paste a fresh token via Edit, or 🔑 Refresh IG token (needs valid app creds) |
| Stored app credentials invalid | Refresher is built but Facebook rejects the app — fix/regenerate the app secret |
| Reddit JSON API IP-blocked | Google News RSS fallback works; install the OpenCLI browser extension (Chrome) for login-state Reddit |
| X/LinkedIn official posting APIs | Paid/approval-gated — X works free via twikit (username+password) |
| Discord scanning | Needs `DISCORD_BOT_TOKEN` |
| Posting to *others'* posts via API | Platforms don't allow it — the browser flows (human-supervised) are the way |
| View-botting | **Deliberately not built** — watch flows are research (you actually watch); comment flows are unique-per-account and human-supervised |

---

## Suggested daily flow

1. **Learn**: paste a viral competitor reel → save its hashtags
2. **SEO**: raw idea → AI SEO (LLM, content-matched tags)
3. **Create Post**: pick video → auto-analyzed → Post (API or Browser)
4. **Multi-Post**: tick accounts → unique title/desc each
5. **Comments AI**: idea → unique comments per account → comment via browser
6. **Company**: type your goal → CEO runs everything → follow the action items
7. **Analytics**: measure after 7 days
