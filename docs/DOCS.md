# Bifrost AI Gateway — Project Documentation

---

## 1. What We Built

A **self-hosted AI Gateway** running in Docker that:

- Routes requests to multiple LLM providers (OpenRouter, OpenAI, Google Gemini) through a single endpoint
- Persists all configuration (providers, keys, routing rules, governance) across container restarts
- Applies semantic caching to avoid duplicate LLM calls
- Enforces budget limits and rate limits via virtual keys
- Logs every request with cost, latency, and token usage

---

## 2. What We Learned

### Why config was disappearing on restart
Docker containers have an **ephemeral filesystem**. Anything written inside the container is destroyed when it stops.
The fix is a **bind mount** — mapping a folder on your host machine directly into the container:

```yaml
volumes:
  - .:/app/data   # host folder -> /app/data inside container
```

Now `config.db` and `logs.db` live on your machine and survive every restart.

---

### How Bifrost config format works (v1.4.17)

| Wrong (old format) | Correct (v1.4.17) |
|--------------------|-------------------|
| `"providers": [...]` array | `"providers": { "openai": {...} }` object |
| `"models": [...]` top-level | Does not exist — models go inside `keys[].models` |
| `"value": "${VAR}"` for env vars | `"value": "env.VAR_NAME"` |
| `"google"` as provider name | `"gemini"` |
| Plain `redis:7-alpine` | `redis/redis-stack-server` (needs RediSearch for semantic cache) |

---

### How the request flows through Bifrost

```
Your App
   |
   | POST /v1/chat/completions
   |   Authorization: Bearer <master_key or virtual_key>
   v
Bifrost Gateway (port 8080)
   |
   |-- Governance plugin: check virtual key, budget, rate limit
   |-- Semantic cache plugin: check Redis for similar past request
   |        if HIT  -> return cached response instantly
   |        if MISS -> continue
   |
   |-- Route to provider (openrouter / openai / gemini)
   |
   v
LLM Provider API
   |
   v
Bifrost logs response to logs.db (async)
   |
   v
Your App receives response
```

---

## 3. Project File Structure

```
bifrost_data/
├── docker-compose.yml   — spins up Bifrost + Redis Stack
├── config.json          — providers, keys, plugins, governance rules
├── .env                 — secrets (API keys, passwords) — never commit this
├── config.db            — SQLite: all configuration state (auto-managed by Bifrost)
├── logs.db              — SQLite: request/response logs (auto-managed by Bifrost)
└── test.py              — end-to-end test + DB inspection script
```

---

## 4. How Bifrost Handles Databases

### You never create tables manually

Bifrost runs its own **migration system** on every startup.
It reads a built-in schema, compares it to the current DB state, and applies any missing migrations automatically.

```
Container starts
   -> Bifrost reads /app/data/config.db
   -> Runs pending migrations (creates/alters tables)
   -> Seeds data from config.json if tables are empty
   -> Ready
```

If you delete `config.db`, Bifrost recreates it from scratch on next start, seeding from `config.json`.
If you upgrade Bifrost to a new version, it migrates the existing DB automatically.

---

### SQLite layout (default)

**`config.db`** — configuration and governance

| Table | Purpose |
|-------|---------|
| `config_providers` | Registered providers (openai, openrouter, gemini…) |
| `config_keys` | API keys per provider, with status |
| `config_models` | Custom model definitions |
| `config_plugins` | Enabled plugins (semantic_cache, governance, telemetry…) |
| `config_vector_store` | Vector store config (Redis address, TTL, etc.) |
| `governance_virtual_keys` | Virtual API keys exposed to your consumers |
| `governance_virtual_key_provider_configs` | Per-virtual-key provider routing weights and allowed models |
| `governance_budgets` | Spending caps with reset intervals |
| `governance_rate_limits` | Token/request rate limits |
| `governance_customers` | Customer-level access records |
| `governance_teams` | Team-level access records |
| `routing_rules` | Advanced routing rules |
| `routing_targets` | Targets for each routing rule |
| `prompts` / `prompt_versions` | Prompt management |
| `sessions` | Active gateway sessions |
| `migrations` | Internal migration history — do not touch |

**`logs.db`** — request history

| Table | Purpose |
|-------|---------|
| `logs` | One row per request: provider, model, status, latency, cost, tokens, input/output |
| `mcp_tool_logs` | MCP tool call logs |
| `async_jobs` | Background job queue |

---

## 5. Switching to Postgres

### Why use Postgres instead of SQLite

| | SQLite | Postgres |
|--|--------|----------|
| Setup | Zero — built in | Requires extra container |
| Concurrent writers | No | Yes |
| Production scale | Small / single instance | Multi-instance, high traffic |
| Inspect data | Any SQLite tool | Any Postgres client |
| Backups | Copy the `.db` file | `pg_dump` |

### How to enable Postgres

Add the `DATABASE_URL` environment variable to Bifrost. Bifrost detects it and uses Postgres instead of SQLite automatically — **no schema changes, no manual table creation**.

**`docker-compose.yml`** addition:

```yaml
services:
  bifrost:
    environment:
      DATABASE_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}?sslmode=disable

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      retries: 10

volumes:
  postgres_data:
```

**`.env`** additions:

```env
POSTGRES_USER=bifrost
POSTGRES_PASSWORD=change-me
POSTGRES_DB=bifrost
```

Bifrost runs the same migrations on Postgres. All the same tables are created automatically.
The `logs.db` / `config.db` files are no longer used — everything goes into Postgres.

---

## 6. Adding Extra Tables (Your Own Data)

Bifrost does not touch tables it doesn't own. You can add your own tables to the same database freely.

### Option A — Add to the same SQLite files

```python
import sqlite3

conn = sqlite3.connect("config.db")
conn.execute("""
    CREATE TABLE IF NOT EXISTS my_app_requests (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT,
        user_id     TEXT,
        prompt      TEXT,
        model_used  TEXT,
        cost_usd    REAL,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()
conn.close()
```

Bifrost will never alter or drop a table it doesn't recognise.

### Option B — Use a separate DB file

```python
conn = sqlite3.connect("myapp.db")  # lives in the same bifrost_data/ folder
```

### Option C — Add to Postgres (when using Postgres)

```sql
CREATE TABLE IF NOT EXISTS my_app_requests (
    id         SERIAL PRIMARY KEY,
    session_id TEXT,
    user_id    TEXT,
    cost_usd   NUMERIC(10,6),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Connect from your app with the same `DATABASE_URL` — Bifrost and your app share the same Postgres instance, each managing their own tables.

---

## 7. Integration into Your Project

### Calling Bifrost from any application

Replace your direct OpenAI/OpenRouter calls with:

```
Base URL : http://localhost:8080/v1
Auth     : Bearer <your_virtual_key>   (from governance_virtual_keys table)
```

The API is **OpenAI-compatible** — any SDK that speaks OpenAI works with zero code changes:

```python
# Python — using openai SDK
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="sk-bf-f0aa64f5-1814-48e0-974d-b48b4b848976"  # your virtual key
)

response = client.chat.completions.create(
    model="openrouter/mistralai/mistral-large",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

```javascript
// Node.js — using openai SDK
import OpenAI from "openai"

const client = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  apiKey: "sk-bf-f0aa64f5-1814-48e0-974d-b48b4b848976"
})
```

### Master key vs Virtual key

| Key | Use for | Logs requests? |
|-----|---------|----------------|
| `my_secret_key` (master) | Admin / testing only | No — bypasses governance |
| `sk-bf-f0aa64f5...` (virtual) | All application traffic | Yes — full logs with cost and latency |

Always use the **virtual key** in your application so requests are logged, budgeted, and rate-limited.

---

## 8. Quick Reference

```bash
# Start everything
cd C:\Users\USER\bifrost_data
docker compose up -d

# Stop (data is safe)
docker compose down

# Restart gateway only (after config.json change)
docker compose restart bifrost

# View live logs
docker compose logs -f bifrost

# Run test + inspect all tables
python test.py

# Wipe and reinitialize DB from config.json
docker compose down
del config.db logs.db
docker compose up -d
```
