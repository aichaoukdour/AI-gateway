# Bifrost — Package vs Service Integration

---

## 1. Side-by-Side Comparison

| | **Go Package** | **HTTP Service** |
|---|---|---|
| Language support | Go only | Any (Python, JS, Go, Rust…) |
| Network hop | None (in-process) | HTTP call to localhost / remote |
| Latency | Lowest | Small overhead (~1–5ms local) |
| Web UI | None | `http://localhost:8080` |
| REST API endpoint | None built-in | OpenAI-compatible `/v1/*` |
| Shared across multiple apps | No | Yes |
| Redis (semantic cache) | You manage the connection | Bifrost manages it internally |
| Logs (request history) | You implement manually | Auto-logged to `logs.db` / Postgres |
| Budget & rate limiting | You implement manually | Built-in via virtual keys |
| Governance (virtual keys) | None | Full — per key budgets, rate limits |
| Failover between providers | Built-in | Built-in |
| Config file (`config.json`) | Optional (code-based config) | Required |
| Infrastructure needed | None (just Go binary) | Docker + Redis |
| Production multi-instance | Complex (shared state problem) | Simple (all instances point to same service) |

---

## 2. What Bifrost Provides vs What You Implement Manually

### Package — What Bifrost provides
- Provider routing (OpenAI, Anthropic, Gemini, OpenRouter…)
- Automatic failover between providers
- Retry logic on failure
- Request/response schema normalization across providers

### Package — What YOU must implement manually
- **Logging** — store request, response, latency, cost, tokens in your own DB
- **Caching** — connect to Redis yourself, generate embeddings, store/retrieve cached responses
- **Rate limiting** — track token/request counts per user or key in your own middleware
- **Budget tracking** — accumulate cost per key/user and enforce spending limits
- **Monitoring** — no UI, you build your own dashboards or use external tools
- **Key management** — rotate, revoke, and scope provider API keys yourself
- **Config management** — all provider config lives in code, no UI to change at runtime

### Service — What Bifrost provides (everything)
- Provider routing + failover + retries
- Semantic caching via Redis (auto embedding + vector similarity search)
- Virtual keys with per-key budgets and rate limits
- Full request logs (latency, cost, tokens, provider, model) → `logs.db` or Postgres
- Web UI for managing providers, keys, budgets, and viewing logs
- OpenAI-compatible REST API (`/v1/chat/completions`, `/v1/embeddings`) — any SDK works
- DB migrations on every startup — zero manual schema work

### Service — What YOU must implement
- Point your `base_url` to Bifrost — that's it

---

## 3. Full Setup — Go Package

### Prerequisites
- Go 1.21+
- No Docker, no Redis required (unless you add caching yourself)

### Step 1 — Install the package

```bash
go get github.com/maximhq/bifrost/core
```

### Step 2 — Initialize Bifrost in your Go app

```go
package main

import (
    "context"
    "fmt"
    "os"

    "github.com/maximhq/bifrost/core"
    "github.com/maximhq/bifrost/core/schemas"
)

func main() {
    bf, err := core.InitBifrost(&schemas.BifrostConfig{
        Providers: []schemas.ProviderConfig{
            {
                Provider: schemas.OpenAI,
                Keys: []schemas.Key{
                    {Value: os.Getenv("OPENAI_API_KEY")},
                },
            },
            {
                Provider: schemas.Anthropic,
                Keys: []schemas.Key{
                    {Value: os.Getenv("ANTHROPIC_API_KEY")},
                },
            },
        },
    }, nil)
    if err != nil {
        panic(err)
    }
    defer bf.Cleanup()

    resp, bifrostErr := bf.TextCompletion(context.Background(), &schemas.BifrostRequest{
        Provider: schemas.OpenAI,
        Model:    "gpt-4o-mini",
        Input: schemas.BifrostInput{
            Messages: []schemas.Message{
                {Role: "user", Content: "Hello"},
            },
        },
    })
    if bifrostErr != nil {
        panic(bifrostErr.Error.Error())
    }

    fmt.Println(resp.Result.Choices[0].Message.Content)
}
```

### Step 3 — Environment variables

```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

No `.env` file loading — use your app's existing env mechanism (`os.Getenv`, `godotenv`, etc.).

### Step 4 — What you add yourself (manual work)

**Logging example** — write resp to your own DB after each call:
```go
// after bf.TextCompletion(...)
db.Exec(`INSERT INTO llm_logs (model, provider, tokens, latency_ms) VALUES (?, ?, ?, ?)`,
    resp.Model,
    resp.Provider,
    resp.Result.Usage.TotalTokens,
    resp.Latency,
)
```

**Caching example** — check Redis before calling Bifrost:
```go
cached, _ := redisClient.Get(ctx, cacheKey).Result()
if cached != "" {
    return cached // skip Bifrost entirely
}
resp, _ := bf.TextCompletion(ctx, req)
redisClient.Set(ctx, cacheKey, resp.Result.Choices[0].Message.Content, 5*time.Minute)
```

**Rate limiting example** — use a token bucket or middleware:
```go
if !rateLimiter.Allow(userID) {
    return errors.New("rate limit exceeded")
}
```

### Project link — Package approach
There is no project file to link to — everything lives in your Go source code. The `bifrost_data/` folder and `docker-compose.yml` in this repo are **not used**.

---

## 4. Full Setup — HTTP Service

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- API keys for your LLM providers

### This project's service setup lives in `bifrost_data/`

```
bifrost_data/
├── docker-compose.yml   ← spins up Bifrost + Redis Stack
├── config.json          ← all provider, cache, and governance config
├── .env                 ← your API keys and passwords (never commit)
├── config.db            ← auto-managed by Bifrost (SQLite config state)
└── logs.db              ← auto-managed by Bifrost (request history)
```

### Step 1 — Configure providers in `config.json`

The file at `bifrost_data/config.json` is already set up with OpenAI, Gemini, and OpenRouter.
To add or change providers, edit this file:

```json
{
  "providers": {
    "openai": {
      "keys": [{ "name": "openai-key", "value": "env.OPENAI_API_KEY", "weight": 1, "models": ["gpt-4o-mini"] }]
    },
    "anthropic": {
      "keys": [{ "name": "anthropic-key", "value": "env.ANTHROPIC_API_KEY", "weight": 1, "models": ["claude-sonnet-4-6"] }]
    },
    "gemini": {
      "keys": [{ "name": "gemini-key", "value": "env.GOOGLE_API_KEY", "weight": 1, "models": ["gemma-2-27b-it"] }]
    }
  }
}
```

- `value: "env.VAR_NAME"` — Bifrost reads the value from the environment variable at startup
- `weight` — load distribution between keys (all equal = round-robin)
- `models` — which models this key is allowed to serve

### Step 2 — Set your secrets in `.env`

File: `bifrost_data/.env`

```env
LITELLM_MASTER_KEY=your-master-key-here
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
OPENROUTER_API_KEY=sk-or-...
REDIS_PASSWORD=redispass
```

> Never commit `.env`. Use `.env.example` as a template for teammates.

### Step 3 — Start the service

```bash
cd bifrost_data
docker compose up -d
```

This starts two containers:
- `bifrost` — the gateway (port 8080)
- `bifrost-redis` — Redis Stack with RediSearch (required for semantic caching)

Verify it's running:
```bash
docker compose ps
docker compose logs bifrost
```

### Step 4 — Open the UI

```
http://localhost:8080
```

From here you can:
- View and manage providers and API keys
- Create and manage virtual keys
- Set budgets and rate limits
- Browse request logs (latency, cost, tokens per request)
- Monitor cache hit rates

### Step 5 — Link your app to Bifrost

**Python (openai SDK):**
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="vk-default-key"  # virtual key from config.json governance section
)

resp = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}]
)
```

**TypeScript / Node.js:**
```typescript
import OpenAI from "openai"

const client = new OpenAI({
    baseURL: "http://localhost:8080/v1",
    apiKey: "vk-default-key"
})

const resp = await client.chat.completions.create({
    model: "openai/gpt-4o-mini",
    messages: [{ role: "user", content: "Hello" }]
})
```

**Go (using openai SDK against Bifrost):**
```go
import "github.com/openai/openai-go"
import "github.com/openai/openai-go/option"

client := openai.NewClient(
    option.WithBaseURL("http://localhost:8080/v1"),
    option.WithAPIKey("vk-default-key"),
)
```

**Raw HTTP / curl:**
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer vk-default-key" \
  -d '{"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "Hello"}]}'
```

### Step 6 — Semantic caching (optional per request)

Add headers to enable caching on specific requests:

```python
resp = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}],
    extra_headers={
        "x-bf-cache-key": "session-123",    # cache namespace
        "x-bf-cache-ttl": "10m",             # cache TTL
        "x-bf-cache-threshold": "0.85"       # similarity threshold (0–1)
    }
)
```

### Step 7 — Virtual keys (master vs virtual)

| Key type | Purpose | Governed? |
|---|---|---|
| `LITELLM_MASTER_KEY` (from `.env`) | Admin access only, testing | No — bypasses all limits |
| `vk-default-key` (from `config.json`) | All application traffic | Yes — budgets, rate limits, logs apply |

Always use the **virtual key** in your application so requests are logged and governed.

### Common service commands

```bash
# Start
docker compose up -d

# Stop (data is preserved)
docker compose down

# Restart after config.json change
docker compose restart bifrost

# View live logs
docker compose logs -f bifrost

# Reset everything (wipes config.db and logs.db)
docker compose down
rm data/config.db data/logs.db
docker compose up -d
```

---

## 5. Decision Guide

**Choose Package if:**
- Your project is a single Go binary
- You want zero infrastructure (no Docker, no Redis, no separate process)
- You are comfortable building logging, caching, and rate limiting yourself
- You need the absolute lowest latency (in-process, no HTTP)

**Choose Service if:**
- Your project uses any language other than Go
- You have multiple apps or services that all use LLMs
- You want logging, caching, budgets, and rate limiting without writing any of it
- You want a UI to monitor usage and manage providers at runtime
- You want to swap or add providers without redeploying your app

---

## 6. Recommendation for This Project

**Use the Service.** The setup is already complete in `bifrost_data/`.

| What you get immediately | Where it is |
|---|---|
| Running gateway | `docker compose up -d` in `bifrost_data/` |
| Web UI | `http://localhost:8080` |
| OpenAI, Gemini, OpenRouter routing | `bifrost_data/config.json` |
| Semantic cache | Redis Stack in `docker-compose.yml` |
| Request logs | `bifrost_data/logs.db` |
| Budget + rate limits | `config.json` → `governance` section |

Any new app — regardless of language — just sets:
```
base_url = http://localhost:8080/v1
api_key  = vk-default-key
```

No other changes needed.
