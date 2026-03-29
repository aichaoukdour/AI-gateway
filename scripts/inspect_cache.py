import subprocess
import json
import sqlite3

def redis_cmd(cmd):
    """Run a redis-cli command inside the container"""
    full_cmd = f'docker exec bifrost-redis redis-cli -a redispass {cmd}'
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()

print("="*80)
print("  BIFROST CACHE DATA — Complete Inspection")
print("="*80)

# ── 1. Semantic Cache Entries (Redis) ─────────────────────────────────────────
print("\n\n1. SEMANTIC CACHE IN REDIS")
print("-" * 80)
print("   These are cached embeddings and responses\n")

# Get all keys
keys_output = redis_cmd('KEYS "*BifrostSemanticCachePlugin*"')
if keys_output:
    keys = keys_output.split('\n') if keys_output else []
    print(f"   Found {len(keys)} cached entries:\n")
    for i, key in enumerate(keys[:5], 1):
        if key:
            print(f"   Entry {i}: {key}")
            ttl = redis_cmd(f'TTL {key}')
            key_type = redis_cmd(f'TYPE {key}')
            size = redis_cmd(f'STRLEN {key}' if key_type == 'string' else f'HLEN {key}')
            print(f"      Type: {key_type}, TTL: {ttl}s, Size: {size}")
            print()
else:
    print("   No semantic cache entries found\n")

# ── 2. All Redis Keys ────────────────────────────────────────────────────────
print("\n2. ALL REDIS KEYS (Cache Inventory)")
print("-" * 80)

all_keys = redis_cmd('KEYS "*"')
keys_list = [k for k in all_keys.split('\n') if k]
print(f"\n   Total keys in Redis: {len(keys_list)}\n")

for key in keys_list[:15]:
    ttl = redis_cmd(f'TTL {key}')
    key_type = redis_cmd(f'TYPE {key}')
    print(f"   {key:50} Type: {key_type:6} TTL: {ttl:6}s")

# ── 3. Redis Memory Stats ────────────────────────────────────────────────────
print("\n\n3. REDIS MEMORY STATISTICS")
print("-" * 80)

info = redis_cmd('INFO memory')
lines = info.split('\n')
for line in lines:
    if 'used_memory' in line or 'fragmentation' in line:
        print(f"   {line}")

# ── 4. Request Logs with Cache Status ────────────────────────────────────────
print("\n\n4. REQUEST LOGS — Cache Hit/Miss Status (logs.db)")
print("-" * 80)

conn = sqlite3.connect("logs.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Query recent logs
cur.execute("""
    SELECT id, provider, model, status,
           prompt_tokens, completion_tokens, total_tokens,
           latency, cost, cache_debug, created_at
    FROM logs
    ORDER BY created_at DESC
    LIMIT 10
""")
logs = cur.fetchall()

print(f"\n   Recent {len(logs)} requests:\n")
for log in logs:
    print(f"   ID: {log['id'][:8]}...")
    print(f"      Provider: {log['provider']:15} Model: {log['model']}")
    print(f"      Status: {log['status']:8} Cache: {log['cache_debug']}")
    print(f"      Tokens: {log['prompt_tokens']}+{log['completion_tokens']}={log['total_tokens']}  Latency: {log['latency']}ms  Cost: ${log['cost']}")
    print(f"      Time: {log['created_at']}\n")

conn.close()

# ── 5. Cache Effectiveness ──────────────────────────────────────────────────
print("\n5. CACHE EFFECTIVENESS METRICS")
print("-" * 80)

conn = sqlite3.connect("logs.db")
cur = conn.cursor()

cur.execute("""
    SELECT
        COUNT(*) as total_requests,
        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
        SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
        AVG(latency) as avg_latency,
        MIN(latency) as min_latency,
        MAX(latency) as max_latency,
        SUM(cost) as total_cost,
        SUM(CASE WHEN total_tokens > 0 THEN total_tokens ELSE 0 END) as total_tokens
    FROM logs
""")
stats = dict(cur.fetchone())
conn.close()

print(f"\n   Total Requests: {stats['total_requests']}")
print(f"   Successful: {stats['successful']}")
print(f"   Errors: {stats['errors']}")
if stats['avg_latency']:
    print(f"   Avg Latency: {stats['avg_latency']:.0f}ms (min: {stats['min_latency']}ms, max: {stats['max_latency']}ms)")
    if stats['min_latency'] and stats['avg_latency']:
        ratio = stats['max_latency'] / stats['min_latency']
        print(f"   Latency Ratio: {ratio:.1f}x (slower:faster = slowest request vs cached request)")
print(f"   Total Cost: ${stats['total_cost'] or 0:.6f}")
print(f"   Total Tokens: {int(stats['total_tokens'] or 0)}")

print("\n" + "="*80)
