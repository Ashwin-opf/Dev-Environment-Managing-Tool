import platform
import psutil
import sqlite3
import subprocess
from pathlib import Path

def get_active_problems():
    problems = []
    
    # 1. Check critical services on Windows
    if platform.system() == "Windows":
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Service -Name wuauserv, Winmgmt | Select-Object Name, Status | ConvertTo-Json"],
                capture_output=True, text=True, timeout=5
            )
            import json
            services = json.loads(res.stdout) if res.stdout.strip() else []
            if isinstance(services, dict):
                services = [services]
            for s in services:
                # Status: 1 = Stopped, 4 = Running
                if s.get("Status") == 1 or s.get("Status") == "Stopped":
                    s_name = s.get("Name")
                    if s_name == "wuauserv":
                        problems.append({
                            "id": "svc-wuauserv",
                            "title": "Windows Update Agent Stopped",
                            "detail": "The Windows Update service (wuauserv) is stopped, preventing OS patches and security updates.",
                            "category": "Services",
                            "command": 'powershell -Command "Start-Service wuauserv"',
                            "risk": "Low",
                            "source": "Standard Library",
                            "auto_implement": True,
                            "requires_approval": False
                        })
        except Exception:
            pass

    # 2. Check pending dynamic solutions from knowledge_dynamic.db
    dyn_path = Path("backend/knowledge_dynamic.db")
    if dyn_path.exists():
        try:
            conn = sqlite3.connect(dyn_path)
            c = conn.cursor()
            rows = c.execute("SELECT id, trigger_pattern, proposed_fix, category, os FROM learned_solutions WHERE user_approved = 0").fetchall()
            conn.close()
            for r in rows:
                problems.append({
                    "id": f"dyn-{r[0]}",
                    "solution_id": r[0],
                    "title": f"Learned Fix: {r[1]}",
                    "detail": f"AI Engine proposed fix for trigger pattern: '{r[1]}'. Requires user authorization before running.",
                    "category": r[3] or "AI Learned",
                    "command": r[2],
                    "risk": "Medium",
                    "source": "Dynamic KB",
                    "auto_implement": False,
                    "requires_approval": True
                })
        except Exception:
            pass

    return problems

probs = get_active_problems()
print(f"Detected {len(probs)} active system problems:")
for p in probs:
    print(f" - [{p['source']}] {p['title']} (Risk: {p['risk']}, AutoImplement: {p['auto_implement']})")
