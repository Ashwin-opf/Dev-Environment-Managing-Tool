import os
import shutil
from pathlib import Path
from repair_engine import RepairEngine
from scanner import scanner, SystemScanner
from safety import SafetyLayer
from vector_search import VectorSearch

BASE_DIR = Path(__file__).parent

# Support both Docker and local environments
DB_PATH_ENV = os.getenv("DB_PATH", None)
if DB_PATH_ENV:
    DB_PATH = Path(DB_PATH_ENV)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
    DB_PATH = BASE_DIR / "knowledge.db"


def _prepare_database(db_path: Path):
    """Seed an external Docker volume database from the bundled DB when empty."""
    bundled_db = BASE_DIR / "knowledge.db"
    if db_path == bundled_db or db_path.exists() or not bundled_db.exists():
        return
    shutil.copyfile(bundled_db, db_path)


_prepare_database(DB_PATH)

engine = RepairEngine(DB_PATH)
safety = SafetyLayer()
vector_searcher = VectorSearch(DB_PATH)
