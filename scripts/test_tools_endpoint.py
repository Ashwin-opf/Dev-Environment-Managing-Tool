import sqlite3
import re

conn = sqlite3.connect('backend/knowledge_static.db')
c = conn.cursor()
rows = c.execute("SELECT issue, category, command, risk, explanation FROM static_recipes WHERE os IN ('Windows', 'Any') ORDER BY category, issue").fetchall()
tools = []
seen = set()

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
    'rust / cargo': 'rust',
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

for issue, cat, cmd, risk, expl in rows:
    # We want tool-oriented categories
    if cat not in ('IDEs', 'Runtimes', 'Package Managers', 'Containers', 'Databases', 'Version Control', 'CLI Tools', 'Browsers', 'AI Tools'):
        continue
    name = re.sub(r'\s*(missing|missing or stopped|missing or disabled|broken or outdated|corrupted.*|reset.*)$', '', issue, flags=re.I).strip()
    name_clean = name.lower()
    if name_clean in seen:
        continue
    seen.add(name_clean)
    site = 'https://google.com'
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
        'name': name,
        'category': cat,
        'command': cmd,
        'risk': risk,
        'explanation': expl,
        'website': site,
        'statusKey': status_key
    })

print(f"Extracted {len(tools)} registered tools from static DB:")
for t in tools:
    print(f" - [{t['category']}] {t['name']} | key={t['statusKey']} | site={t['website']}")
