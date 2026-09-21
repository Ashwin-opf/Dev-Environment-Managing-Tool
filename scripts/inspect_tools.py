import sqlite3

conn = sqlite3.connect('backend/knowledge_static.db')
print("Categories:")
for r in conn.execute('SELECT category, count(*) FROM static_recipes GROUP BY category').fetchall():
    print(" ", r)

print("\nRegistered Tools in Static DB:")
for r in conn.execute("SELECT id, issue, category, command, risk, explanation FROM static_recipes WHERE category IN ('IDEs', 'Runtimes', 'Package Managers', 'Containers', 'Databases', 'Version Control', 'CLI Tools', 'Browsers') ORDER BY category, issue").fetchall():
    print(f"[{r[2]}] {r[1]} -> {r[3]}")
