# Upstash Redis caching (Render deployment)

This app uses **lazy-loaded, TTL-based Redis caching** so OpenAI is only called when cache entries are missing or expired. If nobody visits the app, **no OpenAI requests are made**.

## How it works

1. **First visitor** (or first visit after cache expiry) triggers OpenAI for:
   - Article sentiment and impact labels
   - Card summaries (per article URL + tone)
   - Signal Studio section briefs and multi-agent workflow
   - Optional research briefs (per article URL)
2. Results are stored in **Upstash Redis** with a **24-hour TTL** (`ex` expiration).
3. **Later visitors** within 24 hours reuse cached data — **no OpenAI calls**.
4. After TTL expires, the **next** visitor refreshes the cache for another 24 hours.
5. If the app is idle for days, Redis keys expire and **OpenAI usage stays at zero**.

Caching is **disabled automatically** when Upstash env vars are not set (local dev works unchanged).

## OpenAI call sites (cached)

| Module | What is cached |
|--------|----------------|
| `modules/ai_services.py` | Sentiment batches, card summaries |
| `modules/impact_classifier.py` | Impact classification batches |
| `agents/llm_client.py` | All agent LLM text/JSON/tool calls |
| `app.py` | Full Signal Studio pipeline bundle |
| `research_agent/brief_cache.py` | Per-article research briefs |

NYT article fetching is **not** cached in Redis (always live on refresh).

---

## 1. Create Upstash Redis

1. Sign in at [Upstash Console](https://console.upstash.com/).
2. Click **Create Database**.
3. Choose a region close to your Render service (e.g. `us-east-1`).
4. After creation, open the database → **REST API** tab.
5. Copy:
   - **UPSTASH_REDIS_REST_URL**
   - **UPSTASH_REDIS_REST_TOKEN**

Upstash free tier is sufficient for development and moderate traffic.

---

## 2. Render environment variables

In your Render web service → **Environment**:

| Variable | Required | Description |
|----------|----------|-------------|
| `NYT_API_KEY` | Yes | New York Times API key |
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `UPSTASH_REDIS_REST_URL` | For caching | From Upstash REST API tab |
| `UPSTASH_REDIS_REST_TOKEN` | For caching | From Upstash REST API tab |
| `REDIS_CACHE_TTL_SECONDS` | No | Default `86400` (24 hours) |
| `PORT` | Auto | Set by Render |
| `HOST` | No | Use `0.0.0.0` on Render |

Do **not** commit `.env` to git.

---

## 3. Render deployment settings

| Setting | Value |
|---------|--------|
| **Root Directory** | `AppV1` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn app:app --host 0.0.0.0 --port $PORT` |

The existing `Procfile` matches this start command.

---

## 4. Local development

Add Upstash vars to `.env` at the repo root or in `AppV1/`:

```bash
UPSTASH_REDIS_REST_URL=https://....upstash.io
UPSTASH_REDIS_REST_TOKEN=your_token
```

Run as usual:

```bash
cd AppV1
pip install -r requirements.txt
python app.py
```

Watch logs for:

- `Upstash Redis caching enabled` — Redis active
- `Redis cache HIT key=...` — served from cache (no OpenAI)
- `Redis cache MISS key=...` — OpenAI called, result stored

---

## 5. Cache key design

Keys are prefixed with `news:` and hashed from namespace + payload, for example:

- `news:sentiment_batch:<hash>`
- `news:summary:<hash>`
- `news:agent_pipeline:<hash>`
- `news:research_brief:<hash>`

TTL is applied on every `SET` via Upstash `ex=REDIS_CACHE_TTL_SECONDS`.

---

## 6. Operational notes

- **Refresh News** clears in-memory session caches but **does not** flush Redis. Shared cache remains until TTL expiry (by design — minimizes API cost).
- To force fresh AI output before TTL expires, delete keys in the Upstash console or wait for expiry.
- If Redis is unreachable, the app **falls back to OpenAI** and continues working (errors are logged, not shown to users).
- Research briefs and agent outputs may include market data; market snapshots are fetched live and are not fully frozen by cache.

---

## 7. Files added

```
AppV1/cache/
├── __init__.py
├── redis_client.py   # Upstash sync/async clients
└── helpers.py        # get/set, TTL, hit/miss logging
```

Configuration: `AppV1/config.py` (`UPSTASH_*`, `REDIS_CACHE_TTL_SECONDS`).
