"""
populate_db.py — Knowledge DB – Full repair recipe set for Windows + Linux.
Run this script once to create/repopulate knowledge.db.
"""
import sys
import sqlite3
from pathlib import Path

# Force UTF-8 output on all platforms (Windows cmd/PowerShell default to cp1252)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DB_PATH = Path(__file__).parent / "knowledge.db"

RECIPES = [
    # ── Python ───────────────────────────────────────────────────────────
    {"issue": "Python PATH missing",      "os": "Windows",
     "command": r'setx PATH "%PATH%;C:\Python312\Scripts;C:\Python312"',
     "risk": "Low",
     "explanation": "Adds the Python 3.12 installation directory and Scripts folder to the user PATH environment variable."},
    {"issue": "Python PATH missing",      "os": "Linux",
     "command": "echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.bashrc && source ~/.bashrc",
     "risk": "Low",
     "explanation": "Appends the user-local Python bin directory to PATH and reloads the shell config."},
    {"issue": "Python missing",           "os": "Windows",
     "command": "winget install --id Python.Python.3 --exact --silent",
     "risk": "Low",
     "explanation": "Installs the latest Python 3 via Winget from the Microsoft Store."},
    {"issue": "Python missing",           "os": "Linux",
     "command": "sudo apt-get install -y python3 python3-pip",
     "risk": "Low",
     "explanation": "Installs Python 3 and pip via the apt package manager."},
    {"issue": "pip broken",               "os": "Linux",
     "command": "python3 -m ensurepip --upgrade && python3 -m pip install --upgrade pip",
     "risk": "Low",
     "explanation": "Re-bootstraps pip and upgrades it to the latest version."},

    # ── Node.js ──────────────────────────────────────────────────────────
    {"issue": "Node.js missing",          "os": "Windows",
     "command": "winget install --id OpenJS.NodeJS --exact --silent",
     "risk": "Low",
     "explanation": "Installs Node.js LTS via Winget."},
    {"issue": "Node.js missing",          "os": "Linux",
     "command": "sudo apt-get install -y nodejs npm",
     "risk": "Low",
     "explanation": "Installs Node.js and npm via apt."},
    {"issue": "npm broken",               "os": "Linux",
     "command": "sudo npm install -g npm@latest",
     "risk": "Low",
     "explanation": "Reinstalls npm globally to the latest stable version."},

    # ── Git ──────────────────────────────────────────────────────────────
    {"issue": "Git missing",              "os": "Windows",
     "command": "winget install --id Git.Git --exact --silent",
     "risk": "Low",
     "explanation": "Installs Git for Windows via Winget."},
    {"issue": "Git missing",              "os": "Linux",
     "command": "sudo apt-get install -y git",
     "risk": "Low",
     "explanation": "Installs Git via apt."},

    # ── Docker ───────────────────────────────────────────────────────────
    {"issue": "Docker service stopped",   "os": "Linux",
     "command": "sudo systemctl start docker && sudo systemctl enable docker",
     "risk": "Medium",
     "explanation": "Starts the Docker daemon and enables it to start on boot."},
    {"issue": "Docker service stopped",   "os": "Windows",
     "command": "Start-Service -Name com.docker.service",
     "risk": "Medium",
     "explanation": "Starts the Docker Desktop backend service via PowerShell."},
    {"issue": "Docker missing",           "os": "Linux",
     "command": "sudo apt-get install -y docker.io && sudo systemctl enable --now docker",
     "risk": "Low",
     "explanation": "Installs Docker engine and starts/enables the daemon."},

    # ── VS Code ──────────────────────────────────────────────────────────
    {"issue": "VS Code corrupted installation", "os": "Windows",
     "command": "winget install --id Microsoft.VisualStudioCode --exact --silent",
     "risk": "Low",
     "explanation": "Reinstalls VS Code via Winget in silent mode."},
    {"issue": "VS Code corrupted installation", "os": "Linux",
     "command": "sudo snap install --classic code",
     "risk": "Low",
     "explanation": "Installs the official VS Code package via snap."},

    # ── Java ─────────────────────────────────────────────────────────────
    {"issue": "Java missing",             "os": "Windows",
     "command": "winget install --id Oracle.JDK.21 --exact --silent",
     "risk": "Low",
     "explanation": "Installs JDK 21 via Winget."},
    {"issue": "Java missing",             "os": "Linux",
     "command": "sudo apt-get install -y default-jdk",
     "risk": "Low",
     "explanation": "Installs the default JDK package via apt."},
    {"issue": "JAVA_HOME not set",        "os": "Linux",
     "command": "if which java >/dev/null 2>&1; then echo \"export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java))))\" >> ~/.bashrc; else echo \"Java not found on PATH\" >&2; exit 1; fi",
     "risk": "Low",
     "explanation": "Detects the active Java path and appends the JAVA_HOME environment variable setup to your .bashrc file."},

    # ── Temp file cleanup ────────────────────────────────────────────────
    {"issue": "Clear temporary files",    "os": "Windows",
     "command": "del /q/f/s \"%TEMP%\\*\" 2>nul & del /q/f/s \"%TMP%\\*\" 2>nul",
     "risk": "Low",
     "explanation": "Deletes all files in the Windows TEMP and TMP directories."},
    {"issue": "Clear temporary files",    "os": "Linux",
     "command": "find /tmp -mindepth 1 -user $(whoami) -depth -delete 2>/dev/null || true && rm -rf ~/.cache/thumbnails/*",
     "risk": "Low",
     "explanation": "Removes all files in /tmp and thumbnail cache."},

    # ── RAM optimization ─────────────────────────────────────────────────
    {"issue": "Boost RAM",                "os": "Windows",
     "command": "powershell -Command \"Get-Process | Where-Object { $_.WorkingSet -gt 500MB } | Format-Table Name,Id,WorkingSet -AutoSize\"",
     "risk": "Low",
     "explanation": "Lists processes using more than 500 MB of RAM so you can decide what to close."},
    {"issue": "Boost RAM",                "os": "Linux",
     "command": "sync && echo 3 | sudo tee /proc/sys/vm/drop_caches",
     "risk": "Medium",
     "explanation": "Flushes the Linux page cache, dentries, and inodes to free RAM. Safe for running systems."},

    # ── Startup optimization ─────────────────────────────────────────────
    {"issue": "Slow startup",             "os": "Windows",
     "command": "powershell -Command \"Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location | Format-Table -AutoSize\"",
     "risk": "Low",
     "explanation": "Lists all programs configured to run at Windows startup."},
    {"issue": "Slow startup",             "os": "Linux",
     "command": "systemctl list-unit-files --state=enabled --type=service",
     "risk": "Low",
     "explanation": "Lists all systemd services enabled to start at boot."},

    # ── Chocolatey ───────────────────────────────────────────────────────
    {"issue": "Chocolatey missing",       "os": "Windows",
     "command": "Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))",
     "risk": "Medium",
     "explanation": "Installs the Chocolatey package manager for Windows via PowerShell."},

    # ── Android Studio ────────────────────────────────────────────────────
    {"issue": "Android Studio missing",   "os": "Linux",
     "command": "sudo snap install android-studio --classic",
     "risk": "Low",
     "explanation": "Installs Android Studio via Snap on Ubuntu/Debian-based systems."},
    {"issue": "Android Studio missing",   "os": "Windows",
     "command": "winget install --id Google.AndroidStudio --exact --silent",
     "risk": "Low",
     "explanation": "Installs Android Studio via Winget."},
    {"issue": "Ollama missing",            "os": "Linux",
     "command": "curl -sSL https://ollama.ai/install.sh | sudo bash",
     "risk": "Medium",
     "explanation": "Installs Ollama locally so the offline AI repair assistant can run."},
    {"issue": "Ollama missing",            "os": "Windows",
     "command": "powershell -NoProfile -ExecutionPolicy Bypass -Command \"iwr https://ollama.ai/install.ps1 -UseBasicParsing | iex\"",
     "risk": "Medium",
     "explanation": "Installs Ollama on Windows so the offline AI repair assistant can run."},

    # ── Browser cleanup ───────────────────────────────────────────────────
    {"issue": "Browser cache cleanup",    "os": "Linux",
     "command": "rm -rf ~/.cache/google-chrome/ ~/.cache/chromium/ ~/.mozilla/firefox/*.default-release/cache2/",
     "risk": "Low",
     "explanation": "Clears cache directories for Chrome, Chromium, and Firefox on Linux."},
    {"issue": "Browser cache cleanup",    "os": "Windows",
     "command": "del /q/f/s \"%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Cache\\*\"",
     "risk": "Low",
     "explanation": "Deletes the Chrome cache folder on Windows."},
    {"issue": "install_nvidia_drivers",    "os": "Linux",
     "command": "sudo ubuntu-drivers install",
     "risk": "Medium",
     "explanation": "Automatically installs the recommended proprietary NVIDIA graphics driver using ubuntu-drivers CLI."},
]


def create_and_populate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            issue       TEXT    NOT NULL,
            os          TEXT    NOT NULL,
            command     TEXT    NOT NULL,
            risk        TEXT    NOT NULL DEFAULT 'Low',
            explanation TEXT    NOT NULL DEFAULT ''
        )
    """)
    
    # Get existing (issue, os) pairs
    cur.execute("SELECT issue, os FROM recipes")
    existing = {(row[0], row[1]) for row in cur.fetchall()}
    
    to_insert = []
    for recipe in RECIPES:
        key = (recipe["issue"], recipe["os"])
        if key in existing:
            # Update default commands to ensure they remain current
            cur.execute(
                "UPDATE recipes SET command=:command, risk=:risk, explanation=:explanation "
                "WHERE issue=:issue AND os=:os",
                recipe
            )
        else:
            to_insert.append(recipe)
            
    if to_insert:
        cur.executemany(
            "INSERT INTO recipes (issue, os, command, risk, explanation) "
            "VALUES (:issue, :os, :command, :risk, :explanation)",
            to_insert
        )
        
    # Create adaptive self-healing tables
    cur.execute("""
        CREATE TABLE IF NOT EXISTS adaptive_knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            os_name TEXT NOT NULL,
            os_version TEXT,
            kernel_version TEXT,
            error_pattern TEXT NOT NULL,
            successful_fix TEXT NOT NULL,
            default_fallback TEXT,
            confidence_score REAL NOT NULL,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            verification_status TEXT NOT NULL,
            source TEXT NOT NULL,
            last_verified TEXT NOT NULL,
            fingerprint_id TEXT,
            error_signature TEXT,
            related_fixes TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS learned_command_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_command TEXT NOT NULL,
            failed_command TEXT NOT NULL,
            replacement_command TEXT NOT NULL,
            verification_result TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS self_healing_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_message TEXT NOT NULL,
            error_source TEXT NOT NULL,
            cause TEXT NOT NULL,
            attempted_fix TEXT NOT NULL,
            fix_source TEXT NOT NULL,
            result TEXT NOT NULL,
            safety_class TEXT NOT NULL,
            validation_result TEXT NOT NULL,
            archived INTEGER DEFAULT 0,
            config_backup TEXT,
            timestamp TEXT NOT NULL
        )
    """)

    # Seed initial OS version rules in adaptive_knowledge_base
    cur.execute("SELECT COUNT(*) FROM adaptive_knowledge_base")
    if cur.fetchone()[0] == 0:
        initial_rules = [
            ("Linux", "24.04", "6.8.0", "ubuntu-drivers install", "sudo ubuntu-drivers install", "sudo ubuntu-drivers install", 1.0, 5, 0, "Trusted", "Local System Rules", "2026-06-10T00:00:00Z"),
            ("Linux", "24.04", "6.8.0", "linux-firmware", "sudo apt-get install -y linux-firmware", "sudo apt-get install -y linux-firmware", 1.0, 5, 0, "Trusted", "Local System Rules", "2026-06-10T00:00:00Z"),
            ("Windows", "11", "10.0", "winget upgrade", "winget upgrade --all", "winget upgrade --all", 1.0, 5, 0, "Trusted", "Local System Rules", "2026-06-10T00:00:00Z")
        ]
        cur.executemany("""
            INSERT INTO adaptive_knowledge_base (
                os_name, os_version, kernel_version, error_pattern, successful_fix, default_fallback,
                confidence_score, success_count, failure_count, verification_status, source, last_verified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, initial_rules)

    conn.commit()
    conn.close()
    print(f"[ok] Seeded/Updated recipes and adaptive knowledge tables into {DB_PATH}")


if __name__ == "__main__":
    create_and_populate()
