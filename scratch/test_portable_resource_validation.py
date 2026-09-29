"""
test_portable_resource_validation.py — Validate extracted runtime resources outside source repo
"""

import os
import sys
import tempfile
import zipfile
import shutil
from pathlib import Path

def test_extracted_resources():
    zip_path = Path("PC_Doctor_WINDOWS_PORTABLE.zip").resolve()
    if not zip_path.exists():
        print(f"FAIL: {zip_path} not found")
        sys.exit(1)
        
    temp_dir = Path(tempfile.mkdtemp(prefix="pc_doc_portable_val_"))
    print(f"Extracting portable zip to isolated directory: {temp_dir}...")
    
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)
            
        base_dir = temp_dir / "PC_Doctor_Portable"
        if not base_dir.exists():
            print(f"FAIL: Base directory {base_dir} not found after extraction")
            sys.exit(1)
            
        # Resource checklist
        checks = [
            ("Standalone Backend Executable", base_dir / "pc-doctor-backend" / "pc-doctor-backend.exe"),
            ("Backend Internal Runtime Dir", base_dir / "pc-doctor-backend" / "_internal"),
            ("Knowledge Runtime DB (root)", base_dir / "pc-doctor-backend" / "knowledge.db"),
            ("Knowledge Runtime DB (internal)", base_dir / "pc-doctor-backend" / "_internal" / "knowledge.db"),
            ("Knowledge Static DB (root)", base_dir / "pc-doctor-backend" / "knowledge_static.db"),
            ("Knowledge Static DB (internal)", base_dir / "pc-doctor-backend" / "_internal" / "knowledge_static.db"),
            ("Package Catalog JSON", base_dir / "pc-doctor-backend" / "pkg_catalog.json"),
            ("Resources Knowledge DB", base_dir / "resources" / "knowledge.db"),
            ("Resources Static DB", base_dir / "resources" / "knowledge_static.db"),
            ("Frontend Dist Index", base_dir / "frontend-dist" / "index.html"),
            ("Frontend Dist CSS", base_dir / "frontend-dist" / "style.css"),
            ("Frontend Dist JS", base_dir / "frontend-dist" / "main.js"),
            ("Portable Run Batch", base_dir / "run_portable.bat"),
            ("Portable Stop Batch", base_dir / "stop_portable.bat"),
            ("Portable Readme", base_dir / "README_PORTABLE.txt"),
        ]
        
        all_passed = True
        for name, path in checks:
            exists = path.exists()
            size = path.stat().st_size if exists else 0
            status = "PASS" if exists and size > 0 else "FAIL"
            if status == "FAIL":
                all_passed = False
            print(f"[{status}] {name:<35} -> {path.name} ({size:,} bytes)")
            
        if not all_passed:
            print("\nRESOURCE VALIDATION FAILED!")
            sys.exit(1)
            
        print("\nALL RUNTIME RESOURCES VALIDATED SUCCESSFULLY IN ISOLATED DIRECTORY!")
    finally:
        print(f"Cleaning up temporary test directory: {temp_dir}...")
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    test_extracted_resources()
