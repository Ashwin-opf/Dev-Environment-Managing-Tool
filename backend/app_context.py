import os
import shutil
from pathlib import Path
from repair_engine import RepairEngine
from scanner import scanner, SystemScanner
from safety import SafetyLayer
from vector_search import VectorSearch

from runtime_paths import get_runtime_db_path, BASE_DIR

DB_PATH = get_runtime_db_path()

def _prepare_database(db_path: Path):
    """Seed an external or user data database from the bundled DB when empty."""
    bundled_db = BASE_DIR / "knowledge.db"
    if db_path == bundled_db or db_path.exists() or not bundled_db.exists():
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundled_db, db_path)


_prepare_database(DB_PATH)

engine = RepairEngine(DB_PATH)
safety = SafetyLayer()
vector_searcher = VectorSearch(DB_PATH)
