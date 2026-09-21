import sqlite3
import re
from pathlib import Path

def get_registered_devtools():
    db_path = Path("backend/knowledge_static.db")
    if not db_path.exists():
        return []

    WEBSITES = {
        'git': 'https://git-scm.com',
        'github cli': 'https://cli.github.com',
        'python': 'https://www.python.org',
        'node.js': 'https://nodejs.org',
        'yarn': 'https://yarnpkg.com',
        'pnpm': 'https://pnpm.io',
        'poetry': 'https://python-poetry.org',
        'visual studio code': 'https://code.visualstudio.com',
        'android studio': 'https://developer.android.com/studio',
        'pycharm': 'https://www.jetbrains.com/pycharm',
        'sublime text': 'https://www.sublimetext.com',
        'neovim': 'https://neovim.io',
        'cursor': 'https://cursor.sh',
        'docker desktop': 'https://www.docker.com',
        'postgresql': 'https://www.postgresql.org',
        'mysql': 'https://www.mysql.com',
        'sqlite': 'https://www.sqlite.org',
        'dbeaver': 'https://dbeaver.io',
        'redis': 'https://redis.io',
        'rust': 'https://www.rust-lang.org',
        'go language': 'https://go.dev',
        'java jdk': 'https://www.oracle.com/java',
        '.net sdk': 'https://dotnet.microsoft.com',
        'cmake': 'https://cmake.org',
        'apache maven': 'https://maven.apache.org',
        'gradle': 'https://gradle.org',
        'google chrome': 'https://www.google.com/chrome',
        'brave browser': 'https://brave.com',
        'mozilla firefox': 'https://www.mozilla.org/firefox',
        'fzf': 'https://github.com/junegunn/fzf',
        'jq': 'https://jqlang.github.io/jq',
        'postman': 'https://www.postman.com',
        'ollama': 'https://ollama.ai'
    }

    STATUS_KEYS = {
        'git': 'git',
        'github cli': 'gh',
        'python': 'python',
        'node.js': 'node',
        'yarn': 'yarn',
        'pnpm': 'pnpm',
        'poetry': 'poetry',
        'visual studio code': 'code',
        'android studio': 'android_studio',
        'pycharm': 'pycharm',
        'sublime text': 'sublime',
        'neovim': 'neovim',
        'docker desktop': 'docker',
        'postgresql': 'postgresql',
        'mysql': 'mysql',
        'sqlite': 'sqlite',
        'dbeaver': 'dbeaver',
        'rust': 'rust',
        'go language': 'go',
        'java jdk': 'java',
        'google chrome': 'chrome',
        'brave browser': 'brave',
        'mozilla firefox': 'firefox',
        'fzf fuzzy finder': 'fzf',
        'jq json processor': 'jq',
        'postman': 'postman',
        'ollama': 'ollama',
    }

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    rows = c.execute("SELECT issue, category, command, risk, explanation FROM static_recipes WHERE os IN ('Windows', 'Any') ORDER BY category, issue").fetchall()
    conn.close()

    tools = []
    seen = set()
    for issue, cat, cmd, risk, expl in rows:
        if cat not in ('IDEs', 'Runtimes', 'Package Managers', 'Containers', 'Databases', 'Version Control', 'CLI Tools', 'Browsers', 'AI Tools'):
            continue
        # Only include installation/tool entries, not generic cache cleans
        if not any(k in cmd.lower() for k in ('winget install', 'npm install', 'curl', 'powershell', 'brew install', 'apt')):
            continue
        if any(bad in issue.lower() for bad in ('corrupt', 'reset', 'prune', 'stopped', 'path missing', 'variable missing')):
            continue
        name = re.sub(r'\s*(missing|missing or stopped|missing or disabled|broken or outdated)$', '', issue, flags=re.I).strip()
        name_clean = name.lower()
        if name_clean in seen:
            continue
        seen.add(name_clean)

        site = "https://google.com"
        for k, v in WEBSITES.items():
            if k in name_clean:
                site = v
                break

        status_key = name_clean.replace(' ', '').replace('-', '').replace('.', '')
        for k, v in STATUS_KEYS.items():
            if k in name_clean:
                status_key = v
                break

        tools.append({
            "name": name,
            "category": cat,
            "command": cmd,
            "risk": risk or "Low",
            "explanation": expl or f"{name} developer package",
            "website": site,
            "statusKey": status_key
        })
    return tools

res = get_registered_devtools()
print(f"Total curated registered dev tools: {len(res)}")
for t in res:
    print(f"[{t['category']}] {t['name']} (Key: {t['statusKey']})")
