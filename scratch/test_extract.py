import sys
sys.path.append("/home/rooster/Desktop/PC Doc/backend")

from routes_system import extract_dynamic_app_command

queries = ["m", "my", "mys", "mysql", "c", "node js", "oracle sql", "somethingrandom"]
for q in queries:
    try:
        res = extract_dynamic_app_command(q, False)
        print(f"Query '{q}': SUCCESS -> {res[0][:50]}...")
    except Exception as e:
        print(f"Query '{q}': FAILED -> {e}")
