import sqlite3
import json

for dbname in ['backend/knowledge_static.db', 'backend/knowledge_dynamic.db', 'backend/knowledge.db', 'backend/resolution_cache.db']:
    try:
        conn = sqlite3.connect(dbname)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(dbname, 'tables:', tables)
        for t in tables:
            cnt = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {cnt} rows")
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
            print(f"    cols: {cols}")
    except Exception as e:
        print(dbname, 'error:', e)
