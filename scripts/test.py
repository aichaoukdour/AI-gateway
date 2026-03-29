import requests
import sqlite3
import json
import time

URL     = "http://localhost:8080/v1/chat/completions"
HEADERS = {"Authorization": "Bearer my_secret_key", "Content-Type": "application/json"}
PAYLOAD = {
    "model": "openrouter/mistralai/mistral-large",
    "messages": [{"role": "user", "content": "Hello OpenRouter!"}],
    "max_tokens": 200
}

def db_table(path, sql):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def do_request(n):
    t0 = time.time()
    resp = requests.post(URL, headers=HEADERS, json=PAYLOAD)
    ms   = int((time.time() - t0) * 1000)
    raw  = resp.json()
    ef   = raw.get("extra_fields", {})
    ok   = not raw.get("is_bifrost_error") and raw.get("choices")
    return {
        "request": {
            "number"  : n,
            "url"     : URL,
            "model"   : PAYLOAD["model"],
            "message" : PAYLOAD["messages"][0]["content"]
        },
        "response": {
            "status"    : "ok" if ok else "error",
            "http_code" : resp.status_code,
            "model"     : raw.get("model"),
            "content"   : raw["choices"][0]["message"]["content"] if ok else None,
            "error"     : raw.get("error") if not ok else None,
            "usage": {
                "prompt_tokens"     : raw.get("usage", {}).get("prompt_tokens"),
                "completion_tokens" : raw.get("usage", {}).get("completion_tokens"),
                "total_tokens"      : raw.get("usage", {}).get("total_tokens"),
                "cost_usd"          : raw.get("usage", {}).get("cost", {}).get("total_cost")
            }
        },
        "routing": {
            "provider"        : ef.get("provider"),
            "model_requested" : ef.get("model_requested"),
            "request_type"    : ef.get("request_type"),
            "latency_ms"      : ms
        },
        "cache": {
            "hit"   : ef.get("cache_debug") not in (None, "miss", ""),
            "debug" : ef.get("cache_debug", "miss")
        }
    }

# ── Run 2 identical requests (2nd should cache-hit if OpenAI key is valid) ────
run1 = do_request(1)
time.sleep(1)
run2 = do_request(2)
time.sleep(3)   # let Bifrost flush async log writes

# ── Snapshot every relevant table ─────────────────────────────────────────────
storage = {
    "logs.db": {
        "logs": db_table("logs.db", """
            SELECT id, provider, model, status,
                   latency, cost, prompt_tokens, completion_tokens,
                   total_tokens, created_at
            FROM   logs
            ORDER  BY created_at DESC LIMIT 10
        """)
    },
    "config.db": {
        "config_providers": db_table("config.db",
            "SELECT name, status, created_at, updated_at FROM config_providers"
        ),
        "config_keys": db_table("config.db",
            "SELECT id, name, provider_id, status FROM config_keys"
        ),
        "config_models": db_table("config.db",
            "SELECT * FROM config_models LIMIT 20"
        ),
        "config_plugins": db_table("config.db",
            "SELECT id, name, enabled, created_at FROM config_plugins"
        ),
        "config_vector_store": db_table("config.db",
            "SELECT * FROM config_vector_store LIMIT 5"
        ),
        "governance_virtual_keys": db_table("config.db",
            "SELECT id, name, value, is_active, budget_id, rate_limit_id FROM governance_virtual_keys"
        ),
        "governance_virtual_key_provider_configs": db_table("config.db",
            "SELECT * FROM governance_virtual_key_provider_configs"
        ),
        "governance_budgets": db_table("config.db",
            "SELECT id, max_limit, reset_duration, current_usage FROM governance_budgets"
        ),
        "governance_rate_limits": db_table("config.db",
            """SELECT id, token_max_limit, token_reset_duration, token_current_usage,
                      request_max_limit, request_reset_duration, request_current_usage
               FROM governance_rate_limits"""
        )
    }
}

out = {
    "flow": [run1, run2],
    "storage": storage
}

print(json.dumps(out, indent=2, default=str))
