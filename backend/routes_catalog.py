"""
Tool Catalog & Discovery Routes
================================
Searchable catalog generated at query time by calling adapters live.
No static tool list stored anywhere.

Endpoints:
  GET /api/catalog/search   — search for packages across all active adapters
  GET /api/catalog/info     — get detailed info for a package from a specific adapter
  GET /api/catalog/adapters — list currently available package managers
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from adapters.registry import get_active_adapter_names, get_adapter, get_all_active_adapters
from risk_engine import assess as risk_assess
from sandbox import dry_run

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/adapters")
async def list_adapters() -> Dict[str, Any]:
    """Return all package managers currently available on this machine."""
    return {
        "ok": True,
        "adapters": get_active_adapter_names(),
    }


@router.get("/search")
async def search_catalog(
    query: str = Query(..., min_length=1, description="Search term"),
    adapter: Optional[str] = Query(None, description="Limit to one adapter (e.g. winget, flatpak)"),
    limit: int = Query(20, le=50),
) -> Dict[str, Any]:
    """
    Search across all active package managers (or one specific adapter).
    Risk level is computed live from the risk engine, not a static label.
    """
    adapters = (
        [get_adapter(adapter)] if adapter and get_adapter(adapter)
        else get_all_active_adapters()
    )

    results: List[Dict[str, Any]] = []

    for adp in adapters:
        if adp is None:
            continue
        try:
            hits = adp.search(query)
            for hit in hits:
                # Generate install command live
                install_cmd = adp.install(hit["id"] or hit["name"])

                # Compute risk tier dynamically
                dr = dry_run(install_cmd)
                risk = risk_assess({"command": install_cmd, "target": hit["name"], "dry_run_result": dr})

                results.append({
                    "name": hit["name"],
                    "id": hit["id"],
                    "version": hit["version"],
                    "description": hit.get("description", ""),
                    "adapter": adp.name,
                    "install_command": install_cmd,   # generated live, never stored
                    "risk_tier": risk["tier"],
                    "risk_reasons": risk["reasons"],
                })
        except Exception:
            pass

    # Deduplicate by name, keep first occurrence
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for r in results:
        key = r["name"].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    return {
        "ok": True,
        "query": query,
        "results": deduped[:limit],
        "total": len(deduped),
        "adapters_queried": [a.name for a in adapters if a],
    }


@router.get("/info")
async def get_package_info(
    name: str = Query(..., description="Package name"),
    adapter: Optional[str] = Query(None, description="Adapter name"),
) -> Dict[str, Any]:
    """Get detailed package info including dependency tree preview."""
    from resolver import CanonicalAction, DependencyResolver

    adp = get_adapter(adapter) if adapter else None
    if not adp:
        from adapters.registry import get_system_adapter
        adp = get_system_adapter()

    if not adp:
        return {"ok": False, "error": "No package manager available"}

    info = adp.info(name)
    install_cmd = adp.install(name)
    dr = dry_run(install_cmd)
    risk = risk_assess({"command": install_cmd, "target": name, "dry_run_result": dr})

    # Build shallow dependency tree
    action = CanonicalAction(intent="install", target=name, adapter_name=adp.name)
    resolver = DependencyResolver()
    tree = resolver.build_tree(action)

    return {
        "ok": True,
        "name": name,
        "adapter": adp.name,
        "info": info,
        "install_command": install_cmd,
        "risk_tier": risk["tier"],
        "risk_reasons": risk["reasons"],
        "dry_run_preview": dr,
        "dependency_tree": tree.to_dict(),
    }
