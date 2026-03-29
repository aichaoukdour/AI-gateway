# Bifrost AI Gateway — Project Structure

## Folder Organization

```
bifrost_data/
│
├── 🔧 PRODUCTION (Essential — Commit to git)
│   ├── docker-compose.yml       • Container orchestration
│   ├── config.json              • Bifrost config (providers, plugins, governance)
│   ├── .env                     • Secrets (DO NOT COMMIT) — use .env.example instead
│   ├── .gitignore               • Git exclusion rules
│   └── README.md                • This file
│
├── 📚 docs/                      • Documentation (Commit to git)
│   ├── DOCS.md                  • Complete setup & DB guide
│   ├── CACHE_GUIDE.md           • Semantic caching explained
│   └── CACHE_DATA_EXPLAINED.md  • Cache data structures
│
├── 🔬 scripts/                   • Test & inspection utilities (Optional)
│   ├── test.py                  • Full flow test with JSON output
│   ├── test_cache.py            • Cache performance test
│   └── inspect_cache.py         • Redis + DB inspection script
│
├── 💾 data/                      • Bifrost databases (Auto-managed, DO NOT COMMIT)
│   ├── config.db                • Configuration & governance state
│   ├── config.db-shm            • SQLite write-ahead log helper
│   ├── config.db-wal            • SQLite write-ahead log
│   └── logs.db                  • Request/response logs
│
├── 🗂️ archive/                   • Temporary cache files (Keep clean)
│   ├── output.json              • Old test outputs
│   ├── Cache-Data-Structure.json• Schema reference
│   └── history.log              • Test history
│
└── .git/                        • Git repository
```

---

## Quick Start

```bash
# Enter the folder
cd C:\Users\USER\bifrost_data

# Start Bifrost + Redis
docker compose up -d

# Run full flow test
python scripts/test.py

# Inspect cache data
python scripts/inspect_cache.py

# Stop
docker compose down
```

---

## What to Commit to Git

✅ **Commit:**
- `docker-compose.yml`
- `config.json`
- `.gitignore`
- `/docs/*`
- `README.md`

❌ **Never Commit:**
- `.env` (has API keys)
- `/data/*` (auto-generated DBs)
- `/scripts/*` (test files, use .env.example instead)
- `/archive/*` (temp files)

---

## Environment Variables

Create `.env.example` for your team:

```bash
# .env.example (commit this, not .env)
LITELLM_MASTER_KEY=your-secret-key-here
OPENAI_API_KEY=sk-proj-your-key-here
GOOGLE_API_KEY=your-gemini-key-here
OPENROUTER_API_KEY=sk-or-your-key-here
REDIS_PASSWORD=redispass
```

Then users copy:
```bash
cp .env.example .env
# and fill in real values
```

---

## Database Files

Bifrost auto-manages these — never manually edit:

| File | Purpose |
|------|---------|
| `config.db` | Providers, keys, governance, budgets, rate limits |
| `logs.db` | Request history, latency, cost, tokens |

To reset everything:
```bash
docker compose down
rm data/config.db data/logs.db
docker compose up -d
```

---

## Scripts

Run from `bifrost_data/`:

```bash
# Test full request flow + see storage
python scripts/test.py

# Cache performance test (3 sequential requests)
python scripts/test_cache.py

# Inspect Redis + DB cache data
python scripts/inspect_cache.py
```

---

## Troubleshooting

**Bifrost won't start?**
```bash
docker compose logs bifrost
```

**Cache not working?**
```bash
python scripts/inspect_cache.py
# Check Redis connection, OpenAI embedding key
```

**Databases corrupted?**
```bash
# Stop and reset
docker compose down
rm -rf data/
docker compose up -d
# Bifrost recreates from config.json
```

---

## Documentation

- **DOCS.md** — Full setup, how Bifrost works, SQLite vs Postgres, custom tables
- **CACHE_GUIDE.md** — Semantic caching, embeddings, cost analysis, integration
- **CACHE_DATA_EXPLAINED.md** — What's stored in Redis, DB schema reference
