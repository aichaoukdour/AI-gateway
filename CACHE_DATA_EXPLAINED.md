# BIFROST CACHE DATA — What Gets Stored

## 1. SEMANTIC CACHE DATA (in Redis)

When a request goes through Bifrost, the semantic cache stores:

```json
{
  "BifrostSemanticCachePlugin:hash:embedding_hash_abc123": {
    "embedding": {
      "model": "text-embedding-3-small",
      "provider": "openai",
      "dimensions": 1536,
      "vector": [0.123, -0.456, 0.789, ..., 0.234],  // 1536 float values
      "similarity_threshold": 0.8
    },

    "request": {
      "prompt": "What is machine learning?",
      "model": "mistralai/mistral-large",
      "provider": "openrouter",
      "max_tokens": 100,
      "temperature": 0.7,
      "messages": [{"role": "user", "content": "What is machine learning?"}]
    },

    "response": {
      "content": "Machine learning is a subset of artificial intelligence...",
      "model": "mistralai/mistral-large",
      "tokens": {
        "prompt": 7,
        "completion": 54,
        "total": 61
      },
      "cost": {
        "usd": 0.000338,
        "currency": "USD"
      },
      "generated_at": "2026-03-29T19:29:32.966ZX"
    },

    "cache_metadata": {
      "inserted_at": "2026-03-29T19:29:33Z",
      "ttl_seconds": 300,
      "expires_at": "2026-03-29T19:34:33Z",
      "cache_key": {
        "by_model": true,
        "by_provider": true
      },
      "hit_count": 2,
      "last_hit": "2026-03-29T19:29:34Z"
    }
  },

  // Another cache entry with similar prompt:
  "BifrostSemanticCachePlugin:hash:embedding_hash_xyz789": {
    "embedding": [...],
    "request": {
      "prompt": "Explain machine learning in 2 sentences",
      "model": "mistralai/mistral-large",
      "..."
    },
    "..."
  }
}
```

---

## 2. REQUEST LOG DATA (in logs.db → logs table)

```json
{
  "logs": [
    {
      "id": "54df2362-c2d2-4ad5-b2c0-db6e5cd0c405",
      "parent_request_id": null,
      "timestamp": "2026-03-29T19:29:32.966ZX",

      // What was requested
      "object_type": "chat_completion",
      "provider": "openrouter",
      "model": "mistralai/mistral-large",

      // Routing info
      "routing_rule_id": null,
      "routing_rule_name": null,
      "routing_engines_used": null,
      "selected_key_id": "2",
      "selected_key_name": "openrouter-key",
      "virtual_key_id": "vk-default",
      "virtual_key_name": "Default API Key",

      // User input
      "input_history": [
        {
          "role": "user",
          "content": "What is machine learning?"
        }
      ],

      // Cache status
      "cache_debug": "miss",  // or "hit" or "semantic_match"
      "latency": 1561,  // milliseconds

      // Output
      "output_message": {
        "role": "assistant",
        "content": "Machine learning is a subset of artificial intelligence..."
      },
      "responses_output": [...],

      // Tokens & cost
      "prompt_tokens": 7,
      "completion_tokens": 51,
      "total_tokens": 58,
      "cached_read_tokens": 0,
      "cost": 0.00032,

      // Status
      "status": "success",
      "error_details": null,

      // Metadata
      "created_at": "2026-03-29T19:29:32.966ZX",
      "request_type": "chat_completion"
    }
  ]
}
```

---

## 3. CACHE STORAGE BREAKDOWN

### Redis Memory (Semantic Cache)
```
┌─ Bifrost Redis (bifrost-redis:6379)
│
├─ BifrostSemanticCachePlugin:
│  ├─ hash:abc123... (10-20KB per entry)
│  ├─ hash:xyz789... (10-20KB per entry)
│  └─ ... (1000s of entries possible)
│
└─ Metadata:
   ├─ Expiration: 5 minutes (TTL)
   ├─ Memory: ~1.5MB base + 10KB per cached response
   └─ Search: Vector similarity matching via RediSearch
```

### SQLite logs.db (Request History)
```
┌─ logs.db
│
└─ logs table (indexed on: created_at, provider, model, status)
   ├─ Total rows: grows with every request
   ├─ Retention: 365 days (auto-cleanup)
   ├─ Size: ~5KB per request
   └─ Storage: 1000 requests = ~5MB
```

---

## 4. WHAT BIFROST CACHES vs DOESN'T CACHE

### ✅ CACHED (stored in Redis)
- Response content
- Error responses (401, 403, rate limit, etc.)
- Token counts
- Cost per request
- Embeddings (vector representation of prompt)
- Metadata (timestamp, TTL, hit count)

### ❌ NOT CACHED
- API keys (stored encrypted in config.db)
- User identities
- Authentication tokens
- Raw request body (unless configured)
- System prompts (unless configured)

---

## 5. CACHE KEY COMPOSITION

Bifrost generates cache keys from:

```python
cache_key = hash(
    provider +           # "openrouter"
    model +              # "mistralai/mistral-large"
    prompt_embedding +   # vector from OpenAI embedding model
    (model if cache_by_model else "") +
    (provider if cache_by_provider else "") +
    (system_prompt if include_system else "")
)
```

**Same prompt** → Same embedding → Same cache key → Cache HIT
**Similar prompt** → Similar embedding (threshold match) → Cache HIT
**Different prompt** → Different embedding → Cache MISS

---

## 6. EXAMPLE: TWO REQUESTS AND THEIR CACHE BEHAVIOR

### Request 1: Initial request (CACHE MISS)
```
Timeline:
0ms     → Request received: "What is ML?"
0ms     → Check Redis cache: MISS (no similar embedding found)
0ms     → Call OpenRouter API
1500ms  → Receive response (54 tokens)
1501ms  → Convert prompt to embedding (OpenAI)
1502ms  → Store in Redis with TTL=5min
1503ms  → Log to logs.db with latency=1503ms, cost=$0.00032

Stored in Redis:
{
  "prompt": "What is ML?",
  "embedding": [vector with 1536 dimensions],
  "response": "Machine learning is...",
  "tokens": 54,
  "cost": 0.00032,
  "expires": 2026-03-29T20:01:22Z
}

Logged to logs.db:
{
  "provider": "openrouter",
  "model": "mistralai/mistral-large",
  "latency": 1503,
  "cost": 0.00032,
  "cache_debug": "miss",
  "status": "success"
}
```

### Request 2: Identical request (CACHE HIT)
```
Timeline:
0ms     → Request received: "What is ML?"
0ms     → Convert prompt to embedding (same embedding)
1ms     → Check Redis cache: HIT found (similarity = 1.0, threshold = 0.8)
2ms     → Return cached response instantly
3ms     → Log to logs.db with latency=3ms, cost=$0

Stored in Redis:
(same embedding hash, hits cached entry)

Logged to logs.db:
{
  "provider": "openrouter",
  "model": "mistralai/mistral-large",
  "latency": 3,
  "cost": 0,
  "cache_debug": "hit",
  "cached_read_tokens": 54,
  "status": "success"
}

SAVINGS: 1500ms latency + $0.00032 cost
```

---

## 7. CACHE STATISTICS FROM YOUR RECENT REQUESTS

```
Total Requests: 10
Successful: 3
Errors: 7

Latency Range:
  - Slowest: 2126ms (initial call to OpenRouter)
  - Fastest: 3-70ms (cache hits)
  - Speedup: 27x faster for cache hits!

Cost:
  - Total cost: $0.00107
  - Cost per successful request: $0.00032-0.00035
  - Cost per error: $0 (errors don't consume tokens)

Cache Status:
  - Current active: 0 entries (expired or cleared)
  - Memory used: 1.54MB (base Redis)
  - Fragmentation: 15.62x (normal for empty instance)
```

---

## 8. HOW TO VIEW LIVE CACHE

```bash
# SSH into the Redis container
docker exec -it bifrost-redis redis-cli -a redispass

# See all cache keys
KEYS "*BifrostSemanticCachePlugin*"

# See a specific cache entry
GET BifrostSemanticCachePlugin:hash:abc123

# See cache stats
INFO memory

# Monitor in real-time
MONITOR

# Clear cache (if needed)
FLUSHDB
```

---

## 9. CACHE CONFIGURATION (from config.json)

```json
{
  "plugins": [
    {
      "name": "semantic_cache",
      "config": {
        "provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "dimension": 1536,
        "ttl": "5m",  // ← How long to keep cached responses
        "threshold": 0.8,  // ← Similarity score to match (0-1)
        "cache_by_model": true,  // ← Different cache per model
        "cache_by_provider": true,  // ← Different cache per provider
        "cleanup_on_shutdown": true,
        "conversation_history_threshold": 3  // ← Don't cache if >3 messages
      }
    }
  ],
  "vector_store": {
    "enabled": true,
    "type": "redis",
    "config": {
      "addr": "bifrost-redis:6379",
      "password": "env.REDIS_PASSWORD"
    }
  }
}
```

TTL expiration removes old entries automatically after 5 minutes.

---

## SUMMARY

| Component | Stores | Duration | Size | Access |
|---|---|---|---|---|
| **Redis (Cache)** | Prompt embeddings + responses | 5 minutes (TTL) | ~20KB per entry | Vector search |
| **logs.db (History)** | Every request metadata + cost | 365 days | ~5KB per entry | SQL queries |
| **config.db (Config)** | Providers, keys, governance | Forever | Varies | SQL queries |

All three work together:
- **Redis** = fast lookup (hit cache in 3-70ms)
- **logs.db** = audit trail (when was this run, how much did it cost)
- **config.db** = access control (who can use what)
