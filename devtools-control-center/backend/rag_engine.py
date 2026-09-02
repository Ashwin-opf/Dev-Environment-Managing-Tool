"""
RAG Semantic Knowledge Engine & Dev Environment Auto-Repair Finder
===================================================================
Connects to SQLite knowledge.db for semantic search (TF-IDF / vector matching)
over verified developer repair recipes, error intelligence, and package knowledge.
Provides automated diagnostic scanning and proactive repair recommendations.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


DB_PATH = Path(__file__).parent / "knowledge.db"


class RAGEngine:
    """
    RAG semantic retrieval engine for developer tools, error intelligence,
    and automatic repair recommendations.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._recipes: List[Dict[str, Any]] = []
        self._vectorizer: Optional[Any] = None
        self._index: Optional[Any] = None
        self._load_and_index()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _load_and_index(self) -> None:
        if not self.db_path.exists():
            return
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT id, issue, os, command, risk, explanation FROM recipes"
                )
                cols = [d[0] for d in cur.description]
                self._recipes = [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception:
            self._recipes = []

        if SKLEARN_AVAILABLE and self._recipes:
            try:
                corpus = [f"{r['issue']} {r['explanation']}" for r in self._recipes]
                self._vectorizer = TfidfVectorizer(stop_words="english")
                self._index = self._vectorizer.fit_transform(corpus)
            except Exception:
                self._index = None

    def search_knowledge(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve top_k semantic matches from knowledge base for a search query.
        """
        if not query.strip():
            return self._recipes[:top_k]

        if SKLEARN_AVAILABLE and self._index is not None and self._vectorizer is not None:
            try:
                q_vec = self._vectorizer.transform([query])
                scores = cosine_similarity(q_vec, self._index).flatten()
                ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
                results = []
                for idx, score in ranked:
                    if score > 0.02:
                        r = dict(self._recipes[idx])
                        r["relevance_score"] = round(float(score), 4)
                        results.append(r)
                if results:
                    return results
            except Exception:
                pass

        # Fallback SQL search
        pattern = f"%{query.strip()}%"
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT id, issue, os, command, risk, explanation FROM recipes "
                    "WHERE issue LIKE ? OR explanation LIKE ? OR command LIKE ? LIMIT ?",
                    (pattern, pattern, pattern, top_k),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception:
            return []

    def get_package_knowledge(self, pkg_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve rich knowledge data for a specific package."""
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT * FROM package_knowledge WHERE name LIKE ? OR package_id LIKE ? LIMIT 1",
                    (f"%{pkg_name}%", f"%{pkg_name}%"),
                )
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
        except Exception:
            pass
        return None

    def find_environment_repairs(self) -> List[Dict[str, Any]]:
        """
        Automatic Repair Finder: Actively diagnoses local environment anomalies
        and matches them with verified RAG repair recipes.
        """
        repairs: List[Dict[str, Any]] = []
        is_win = platform.system() == "Windows"
        is_mac = platform.system() == "Darwin"

        # 1. Check Python & Pip Health
        py_bin = shutil.which("python") or shutil.which("py") or shutil.which("python3")
        if not py_bin:
            repairs.append({
                "id": "repair-python-missing",
                "component": "Python",
                "issue": "Python runtime is not found in system PATH",
                "severity": "High",
                "command": "winget install Python.Python.3.12 --exact --silent" if is_win else ("brew install python" if is_mac else "sudo apt-get install -y python3 python3-pip"),
                "risk": "Low",
                "explanation": "Installs verified Python 3 runtime and configures PATH environment automatically.",
                "source": "rag_auto_repair",
            })
        else:
            # Check pip
            pip_bin = shutil.which("pip") or shutil.which("pip3")
            if not pip_bin:
                repairs.append({
                    "id": "repair-pip-missing",
                    "component": "Python / Pip",
                    "issue": "pip package installer missing from Python environment",
                    "severity": "Medium",
                    "command": f"{py_bin} -m ensurepip --default-pip",
                    "risk": "Low",
                    "explanation": "Executes ensurepip to bootstrap pip inside the active Python environment.",
                    "source": "rag_auto_repair",
                })

        # 2. Check Node & npm Health
        node_bin = shutil.which("node") or shutil.which("nodejs")
        npm_bin = shutil.which("npm")
        if node_bin and not npm_bin:
            repairs.append({
                "id": "repair-npm-missing",
                "component": "Node.js / npm",
                "issue": "Node.js is installed but npm binary is not found in PATH",
                "severity": "High",
                "command": "winget install OpenJS.NodeJS --exact --silent" if is_win else "sudo apt-get install -y nodejs npm",
                "risk": "Low",
                "explanation": "Reinstalls or repairs the Node.js distribution to bundle the matching npm package manager.",
                "source": "rag_auto_repair",
            })

        # 3. Check Git Health & Safe Directories
        git_bin = shutil.which("git")
        if not git_bin:
            repairs.append({
                "id": "repair-git-missing",
                "component": "Git VCS",
                "issue": "Git version control system is missing",
                "severity": "High",
                "command": "winget install Git.Git -e --silent" if is_win else "sudo apt-get install -y git",
                "risk": "Low",
                "explanation": "Installs standard Git version control system.",
                "source": "rag_auto_repair",
            })
        else:
            # Check Git config for core.autocrlf
            try:
                out = subprocess.run(["git", "config", "--get", "core.autocrlf"], capture_output=True, text=True, timeout=3)
                if not out.stdout.strip():
                    val = "true" if is_win else "input"
                    repairs.append({
                        "id": "repair-git-autocrlf",
                        "component": "Git Configuration",
                        "issue": "Git core.autocrlf line-ending conversion is not configured",
                        "severity": "Low",
                        "command": f"git config --global core.autocrlf {val}",
                        "risk": "Low",
                        "explanation": f"Configures global git line endings to '{val}' to prevent CRLF/LF corruptions across branches.",
                        "source": "rag_auto_repair",
                    })
            except Exception:
                pass

        # 4. Check Package Manager Cache / Indices
        if is_win:
            # Check winget source health
            if shutil.which("winget"):
                # Offer winget source reset if needed
                pass
        else:
            # Linux apt index check
            if shutil.which("apt-get"):
                repairs.append({
                    "id": "repair-apt-update",
                    "component": "APT Package Manager",
                    "issue": "Package manager cache may be stale or out of sync",
                    "severity": "Low",
                    "command": "sudo apt-get update -y",
                    "risk": "Low",
                    "explanation": "Updates apt package index against all upstream repositories.",
                    "source": "rag_auto_repair",
                })

        # 5. Check PATH for invalid / non-existent directories
        path_dirs = os.environ.get("PATH", "").split(os.pathsep)
        invalid_paths = [p for p in path_dirs if p and not os.path.exists(p)]
        if len(invalid_paths) > 2:
            repairs.append({
                "id": "repair-stale-path",
                "component": "Environment PATH",
                "issue": f"{len(invalid_paths)} stale or deleted directories detected in system PATH",
                "severity": "Low",
                "command": "echo 'PATH cleanup recommended'",
                "risk": "Low",
                "explanation": f"Stale entries in PATH slow down command discovery: {', '.join(invalid_paths[:3])}...",
                "source": "rag_auto_repair",
            })

        # 6. Complement with top general recipes from knowledge.db
        matched_recipes = self.search_knowledge("repair clean cache", top_k=2)
        for r in matched_recipes:
            if not any(x["issue"] == r["issue"] for x in repairs):
                repairs.append({
                    "id": f"rag-recipe-{r['id']}",
                    "component": "System Maintenance",
                    "issue": r["issue"],
                    "severity": "Low",
                    "command": r["command"],
                    "risk": r.get("risk", "Low"),
                    "explanation": r.get("explanation", ""),
                    "source": "rag_knowledge_base",
                })

        return repairs


# Singleton RAG Engine instance
rag_engine = RAGEngine()
