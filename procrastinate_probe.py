"""Can a Procrastinate worker talk to Supabase from here? Read-only: creates no tables.

Run on the Render web service's Shell:
    pip install --user "psycopg[binary]" && SUPABASE_DB_URL='<session pooler string>' python procrastinate_probe.py
"""
import os, select, socket, sys, time
from urllib.parse import urlparse

import psycopg

url = os.environ.get("SUPABASE_DB_URL")
if not url:
    sys.exit("Set SUPABASE_DB_URL to the Session pooler string (Supabase -> Connect -> Session pooler, port 5432)")
u = urlparse(url)
ok = True

def check(name, passed, detail=""):
    global ok
    ok &= passed
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")

# 1. Host has an IPv4 address (Render has no IPv6 out; the direct db.* host is IPv6-only)
v4 = {a[4][0] for a in socket.getaddrinfo(u.hostname, u.port or 5432, socket.AF_INET)}
check("pooler host has IPv4", bool(v4), ",".join(sorted(v4)))
check("session mode port 5432 (not 6543)", (u.port or 5432) == 5432, f"port={u.port}")

# 2. Connect
t = time.perf_counter()
a = psycopg.connect(url, autocommit=True, connect_timeout=10)
b = psycopg.connect(url, autocommit=True, connect_timeout=10)
check("connect x2", True, f"{(time.perf_counter() - t) * 1000:.0f} ms, server {a.info.server_version}")

# 3. LISTEN on one connection, NOTIFY from the other (how a new job wakes the worker)
a.execute("LISTEN anril_probe")
t = time.perf_counter()
b.execute("SELECT pg_notify('anril_probe', 'hello')")
got = None
if select.select([a.fileno()], [], [], 5)[0]:
    for n in a.notifies(timeout=1, stop_after=1):
        got = n.payload
check("LISTEN/NOTIFY round trip", got == "hello", f"{(time.perf_counter() - t) * 1000:.0f} ms")

# 4. A lock taken by one connection stays held across statements and is refused to the
# other (only true in session mode; transaction mode hands connections around)
a.execute("SELECT pg_advisory_lock(424242)")
held = b.execute("SELECT pg_try_advisory_lock(424242)").fetchone()[0]
check("lock held by one session is refused to the other", held is False)
a.execute("SELECT pg_advisory_unlock(424242)")

a.close(); b.close()
print("\nALL PASS: Procrastinate can run from here." if ok else "\nSOMETHING FAILED: see above.")
