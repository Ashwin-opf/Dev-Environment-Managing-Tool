"""
Vector Search – Semantic fuzzy matching for repair recipes using TF-IDF.
This is a lightweight offline alternative to embedding models.
Requires: scikit-learn (optional, added to requirements-optional.txt)
Falls back to SQL LIKE search if scikit-learn is not available.
"""
from pathlib import Path
import sqlite3

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


DB_PATH = Path(__file__).parent / "knowledge.db"


class VectorSearch:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._index = None
        self._recipes = []
        self._vectorizer = None
        if SKLEARN_AVAILABLE:
            self._build_index()

    def _load_recipes(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT id, issue, os, command, risk, explanation FROM recipes"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _build_index(self):
        """Build TF-IDF matrix over issue+explanation text."""
        self._recipes = self._load_recipes()
        if not self._recipes:
            return
        corpus = [
            f"{r['issue']} {r['explanation']}" for r in self._recipes
        ]
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._index = self._vectorizer.fit_transform(corpus)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return top_k most relevant recipes for the query."""
        if not SKLEARN_AVAILABLE or self._index is None:
            return self._fallback_search(query)

        q_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self._index).flatten()
        ranked = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )[:top_k]
        results = []
        for idx, score in ranked:
            if score > 0.05:   # minimum relevance threshold
                r = dict(self._recipes[idx])
                r["score"] = round(float(score), 4)
                results.append(r)
        return results

    def _fallback_search(self, query: str) -> list[dict]:
        """SQL LIKE fallback when scikit-learn is unavailable."""
        pattern = f"%{query}%"
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT id, issue, os, command, risk, explanation "
                "FROM recipes WHERE issue LIKE ? OR explanation LIKE ?",
                (pattern, pattern),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
