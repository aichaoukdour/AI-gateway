import requests
import sqlite3
import json
import time
import redis

URL     = "http://localhost:8080/v1/chat/completions"
HEADERS = {"Authorization": "Bearer my_secret_key", "Content-Type": "application/json"}

# Test variations of the same request (should cache on 2nd call if cache was working)
REQUESTS = [
    {
        "model": "openrouter/mistralai/mistral-large",
        "messages": [{"role": "user", "content": "What is machine learning?"}],
        "max_tokens": 100
    },
    {
        "model": "openrouter/mistralai/mistral-large",
        "messages": [{"role": "user", "content": "What is machine learning?"}],  # SAME — should cache hit
        "max_tokens": 100
    },
    {
        "model": "openrouter/mistralai/mistral-large",
        "messages": [{"role": "user", "content": "Explain machine learning in 2 sentences"}],  # SIMILAR — embeddings should find it
        "max_tokens": 100
    },
]

def db_query(path, sql):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def redis_info():
    """Get cache keys from Redis"""
    try:
        r = redis.Redis(host="localhost", port=6379, password="redispass", decode_responses=True)
        # Scan for semantic cache keys
        keys = []
        for key in r.scan_iter("*BifrostSemanticCachePlugin*"):
            keys.append({"key": key, "ttl": r.ttl(key)})
        return keys[:10]  # limit to 10
    except:
        return []

output = {
    "test_configuration": {
        "gateway": "http://localhost:8080/v1",
        "requests_count": len(REQUESTS),
        "vector_store": "Redis (bifrost-redis:6379)",
        "cache_provider": "openai (text-embedding-3-small, dimension=1536)",
        "note": "Cache hits require VALID OpenAI API key. If using placeholder, all requests miss cache."
    },
    "requests": []
}

print(f"\n{'='*70}")
print(f"  BIFROST SEMANTIC CACHE TEST — Multiple Requests")
print(f"{'='*70}\n")

# Send 3 requests with latency tracking
for i, payload in enumerate(REQUESTS, 1):
    print(f"  Request {i}: {payload['messages'][0]['content'][:50]}...")
    t0 = time.time()
    resp = requests.post(URL, headers=HEADERS, json=payload)
    ms = int((time.time() - t0) * 1000)
    data = resp.json()

    ok = not data.get("is_bifrost_error") and data.get("choices")
    ef = data.get("extra_fields", {})

    req_record = {
        "number": i,
        "prompt": payload["messages"][0]["content"],
        "model": payload["model"],
        "client_latency_ms": ms,
        "provider_latency_ms": ef.get("latency"),
        "status": "ok" if ok else "error",
        "cache_debug": ef.get("cache_debug", "miss"),
        "tokens_total": data.get("usage", {}).get("total_tokens"),
        "cost_usd": data.get("usage", {}).get("cost", {}).get("total_cost"),
        "response_preview": data["choices"][0]["message"]["content"][:80] if ok else data.get("error")
    }
    output["requests"].append(req_record)
    print(f"    -> {ms}ms  cache: {ef.get('cache_debug', 'miss')}  tokens: {data.get('usage', {}).get('total_tokens')}  cost: ${data.get('usage', {}).get('cost', {}).get('total_cost')}\n")
    time.sleep(1)

time.sleep(3)  # flush async logs

# ── Storage snapshot ─────────────────────────────────────────────────────────
print(f"  Capturing storage...\n")

output["storage"] = {
    "logs.db": {
        "logs_recent": db_query("logs.db", """
            SELECT id, provider, model,
                   prompt_tokens, completion_tokens, total_tokens,
                   latency, cost, status, created_at
            FROM   logs
            ORDER  BY created_at DESC LIMIT 10
        """),
        "stats": db_query("logs.db", """
            SELECT COUNT(*) as total_requests,
                   SUM(cost) as total_cost,
                   AVG(latency) as avg_latency_ms
            FROM logs
        """)[0]
    },
    "config.db": {
        "config_plugins": db_query("config.db",
            "SELECT id, name, enabled FROM config_plugins"
        ),
        "config_vector_store": db_query("config.db",
            "SELECT type, ttl_seconds, cache_by_model, cache_by_provider FROM config_vector_store"
        ),
        "governance_virtual_keys": db_query("config.db",
            "SELECT id, name, is_active FROM governance_virtual_keys"
        ),
    },
    "redis_cache": {
        "semantic_cache_keys": redis_info(),
        "note": "Shows keys in Redis storage for semantic embeddings"
    }
}

# Print JSON
print(json.dumps(output, indent=2, default=str))

# ── Summary ──────────────────────────────────────────────────────────────────
print(f"\n\n{'='*70}")
print(f"  CACHE ANALYSIS")
print(f"{'='*70}\n")

lats = [r["client_latency_ms"] for r in output["requests"]]
print(f"  Request 1 latency: {lats[0]}ms  (initial request)")
print(f"  Request 2 latency: {lats[1]}ms  (identical prompt — {'CACHE HIT' if lats[1] < lats[0]*0.3 else 'CACHE MISS'})")
print(f"  Request 3 latency: {lats[2]}ms  (similar prompt — should have higher hit chance)")
print(f"\n  Cache performance: {'Good' if lats[1] < lats[0]*0.5 else 'Not active (missing OpenAI key?)'}")
print(f"\n  Total cost: ${sum(r['cost_usd'] or 0 for r in output['requests']):.6f}")
print(f"  Total tokens used: {sum(r['tokens_total'] or 0 for r in output['requests'])} tokens")
print(f"  Saved by cache: {(lats[0] - lats[1]) if lats[1] < lats[0]*0.5 else 0}ms")
