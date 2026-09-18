"""
recipe_engine.py — Authoritative Structured Recipe Engine for PC Doctor.

Defines:
- Recipe operations (INSTALL, UPDATE, UNINSTALL, REINSTALL, VERSION_CHECK, VERIFY, REPAIR).
- Repair strategies (NATIVE, REINSTALL, CONFIG_RESET, CACHE_CLEAR, NONE).
- 15-state Recipe Lifecycle enum.
- Structured recipe schema.
- Recipe Resolver loading and validating recipes from Static DB.
"""

from __future__ import annotations

import json
import os
import platform
import shlex
import sqlite3
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from canonical_identity import CanonicalIdentity, canonical_store


class RecipeOperation(str, Enum):
    INSTALL = "INSTALL"
    UPDATE = "UPDATE"
    UNINSTALL = "UNINSTALL"
    REINSTALL = "REINSTALL"
    VERSION_CHECK = "VERSION_CHECK"
    VERIFY = "VERIFY"
    REPAIR = "REPAIR"


class RepairStrategy(str, Enum):
    NATIVE = "NATIVE"
    REINSTALL = "REINSTALL"
    CONFIG_RESET = "CONFIG_RESET"
    CACHE_CLEAR = "CACHE_CLEAR"
    NONE = "NONE"


class RecipeLifecycle(str, Enum):
    GENERATED = "GENERATED"
    VALIDATED = "VALIDATED"
    SAFETY_REJECTED = "SAFETY_REJECTED"
    USER_DECLINED = "USER_DECLINED"
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"
    EXECUTING = "EXECUTING"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTED = "EXECUTED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFICATION_TIMEOUT = "VERIFICATION_TIMEOUT"
    EXECUTED_BUT_UNVERIFIED = "EXECUTED_BUT_UNVERIFIED"
    VERIFIED = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PROMOTION_ELIGIBLE = "PROMOTION_ELIGIBLE"
    PROMOTED_TO_STATIC = "PROMOTED_TO_STATIC"
    DEPRECATED = "DEPRECATED"
    DISABLED = "DISABLED"
    STABLE = "PROMOTED_TO_STATIC"
    CANDIDATE = "GENERATED"


@dataclass
class StructuredRecipe:
    recipe_id: str
    recipe_version: int
    identity_id: str
    operation: RecipeOperation
    os: str                                # "Windows", "Linux", "Darwin", "Any"
    architecture: str                      # "x64", "arm64", "x86", "Any"
    package_manager: str                   # "winget", "apt", "brew", "npm", "pip", "custom"
    executable: str                        # Executable to invoke: "winget", "git", etc.
    arguments: list[str]                   # Arguments list: ["install", "--id", "Git.Git", "--silent"]
    verification_command: list[str]        # ["git", "--version"]
    expected_result: dict[str, Any] = field(default_factory=dict)
    risk_base: str = "Low"                 # "Low", "Medium", "High"
    official_url: str = ""
    source: str = "STATIC_DB"              # "STATIC_DB", "DYNAMIC_DB"
    supported_environment: dict[str, Any] = field(default_factory=dict)
    repair_strategy: RepairStrategy = RepairStrategy.NONE
    validation_status: RecipeLifecycle = RecipeLifecycle.READY_FOR_EXECUTION
    last_validated_at: str = ""
    validation_frequency: int = 86400      # 24 hours

    def to_command_string(self) -> str:
        """Render safely quoted shell command string."""
        if not self.executable:
            return ""
        # On Windows, winget/powershell arguments can be joined or quoted
        parts = [self.executable] + [str(a) for a in self.arguments]
        if platform.system() == "Windows":
            # For Windows cmd/powershell, quote args with spaces
            quoted = []
            for p in parts:
                if " " in p and not (p.startswith('"') and p.endswith('"')):
                    quoted.append(f'"{p}"')
                else:
                    quoted.append(p)
            return " ".join(quoted)
        return " ".join(shlex.quote(p) for p in parts)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["operation"] = self.operation.value
        d["repair_strategy"] = self.repair_strategy.value
        d["validation_status"] = self.validation_status.value
        d["command_string"] = self.to_command_string()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StructuredRecipe:
        op = RecipeOperation(data.get("operation", "REPAIR"))
        strat = RepairStrategy(data.get("repair_strategy", "NONE"))
        status = RecipeLifecycle(data.get("validation_status", "READY_FOR_EXECUTION"))

        args = data.get("arguments", [])
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = args.split()

        vcmd = data.get("verification_command", [])
        if isinstance(vcmd, str):
            try:
                vcmd = json.loads(vcmd)
            except Exception:
                vcmd = vcmd.split()

        exp = data.get("expected_result", {})
        if isinstance(exp, str):
            try:
                exp = json.loads(exp)
            except Exception:
                exp = {}

        env = data.get("supported_environment", {})
        if isinstance(env, str):
            try:
                env = json.loads(env)
            except Exception:
                env = {}

        return cls(
            recipe_id=str(data.get("recipe_id", "")),
            recipe_version=int(data.get("recipe_version", 1)),
            identity_id=str(data.get("identity_id", "")),
            operation=op,
            os=str(data.get("os", "Any")),
            architecture=str(data.get("architecture", "Any")),
            package_manager=str(data.get("package_manager", "winget")),
            executable=str(data.get("executable", "")),
            arguments=list(args),
            verification_command=list(vcmd),
            expected_result=dict(exp),
            risk_base=str(data.get("risk_base", "Low")),
            official_url=str(data.get("official_url", "")),
            source=str(data.get("source", "STATIC_DB")),
            supported_environment=dict(env),
            repair_strategy=strat,
            validation_status=status,
            last_validated_at=str(data.get("last_validated_at", "")),
            validation_frequency=int(data.get("validation_frequency", 86400)),
        )


class RecipeResolver:
    """Resolves structured recipes from Static DB and canonical identity definitions."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            db_path = Path(__file__).parent / "knowledge_static.db"
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def resolve_recipe(
        self,
        tool_query: str,
        operation: RecipeOperation,
        current_os: Optional[str] = None,
        arch: Optional[str] = None,
    ) -> Optional[StructuredRecipe]:
        """Resolve authoritative recipe for a tool query and operation."""
        if current_os is None:
            current_os = platform.system()
        if arch is None:
            import platform as _p
            arch = _p.machine().lower()
            if "x86_64" in arch or "amd64" in arch:
                arch = "x64"

        # 1. Resolve canonical identity
        identity = canonical_store.resolve(tool_query)
        identity_id = identity.identity_id if identity else tool_query.lower()

        # 2. Check Static DB structured recipes table
        recipe = self._query_static_db(identity_id, operation, current_os, arch)
        if recipe:
            return recipe

        # 3. If no DB record exists, synthesize canonical recipe if identity is known
        if identity:
            return self._synthesize_from_identity(identity, operation, current_os)

        return None

    find_recipe = resolve_recipe

    def _query_static_db(
        self,
        identity_id: str,
        operation: RecipeOperation,
        current_os: str,
        arch: str,
    ) -> Optional[StructuredRecipe]:
        if not self.db_path.exists():
            return None
        try:
            with self._get_conn() as conn:
                # Check for table existence
                tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if "static_recipes" not in tables:
                    return None

                # Fetch rows matching identity_id or app_id or package_id
                rows = conn.execute(
                    """
                    SELECT * FROM static_recipes 
                    WHERE (app_id = ? OR package_id = ? OR issue LIKE ?)
                      AND (os = ? OR os = 'Any')
                    """,
                    (identity_id, identity_id, f"%{identity_id}%", current_os),
                ).fetchall()

                for row in rows:
                    r_dict = dict(row)
                    row_op = r_dict.get("operation", "REPAIR").upper()
                    # If looking for specific operation
                    if row_op == operation.value:
                        return self._row_to_structured_recipe(r_dict, identity_id)

                    # If looking for REPAIR and row is repair
                    if operation == RecipeOperation.REPAIR and row_op in ("REPAIR", "NATIVE"):
                        return self._row_to_structured_recipe(r_dict, identity_id)

                    # If looking for INSTALL
                    if operation == RecipeOperation.INSTALL and row_op == "INSTALL":
                        return self._row_to_structured_recipe(r_dict, identity_id)

                    # If looking for UPDATE
                    if operation == RecipeOperation.UPDATE and row_op == "UPDATE":
                        return self._row_to_structured_recipe(r_dict, identity_id)
        except Exception as exc:
            pass

        return None

    def _row_to_structured_recipe(self, r_dict: dict, identity_id: str) -> StructuredRecipe:
        cmd_str = r_dict.get("command", "").strip()
        parts = cmd_str.split() if cmd_str else []
        executable = parts[0] if parts else ""
        arguments = parts[1:] if len(parts) > 1 else []

        vcmd_str = r_dict.get("verification_command", "").strip()
        vcmd = vcmd_str.split() if vcmd_str else []

        repair_strat = RepairStrategy.NONE
        strat_raw = r_dict.get("repair_strategy", "").upper()
        if strat_raw in RepairStrategy.__members__:
            repair_strat = RepairStrategy(strat_raw)
        elif "install" in cmd_str.lower() and "--force" in cmd_str.lower():
            repair_strat = RepairStrategy.REINSTALL

        op_raw = r_dict.get("operation", "REPAIR").upper()
        op = RecipeOperation(op_raw) if op_raw in RecipeOperation.__members__ else RecipeOperation.REPAIR

        # CRITICAL RULE: Never mislabel REINSTALL as native REPAIR
        if op == RecipeOperation.REPAIR and repair_strat == RepairStrategy.REINSTALL:
            repair_strat = RepairStrategy.REINSTALL

        return StructuredRecipe(
            recipe_id=f"static_{r_dict.get('id', identity_id)}",
            recipe_version=1,
            identity_id=r_dict.get("app_id") or identity_id,
            operation=op,
            os=r_dict.get("os", "Any"),
            architecture="Any",
            package_manager=r_dict.get("package_manager", "winget"),
            executable=executable,
            arguments=arguments,
            verification_command=vcmd,
            expected_result={"return_code": 0},
            risk_base=r_dict.get("risk", "Low"),
            official_url=r_dict.get("official_url", ""),
            source="STATIC_DB",
            supported_environment={"os": r_dict.get("os", "Any")},
            repair_strategy=repair_strat,
            validation_status=RecipeLifecycle.READY_FOR_EXECUTION,
            last_validated_at=r_dict.get("created_at", ""),
            validation_frequency=86400,
        )

    def _synthesize_from_identity(
        self,
        identity: CanonicalIdentity,
        operation: RecipeOperation,
        current_os: str,
    ) -> StructuredRecipe:
        pkg_id = identity.get_package_id(current_os) or identity.package_id
        pm = identity.get_package_manager(current_os) or identity.package_manager or ("winget" if current_os == "Windows" else "brew" if current_os == "Darwin" else "apt")

        executable = pm
        arguments = []
        repair_strategy = RepairStrategy.NONE

        if current_os == "Windows" and pm == "winget":
            if operation == RecipeOperation.INSTALL:
                executable = "winget"
                arguments = ["install", "--id", pkg_id, "--exact", "--silent", "--accept-source-agreements", "--accept-package-agreements"]
            elif operation == RecipeOperation.UPDATE:
                executable = "winget"
                arguments = ["upgrade", "--id", pkg_id, "--exact", "--silent"]
            elif operation == RecipeOperation.UNINSTALL:
                executable = "winget"
                arguments = ["uninstall", "--id", pkg_id, "--exact", "--silent"]
            elif operation == RecipeOperation.REINSTALL:
                executable = "winget"
                arguments = ["install", "--id", pkg_id, "--exact", "--force", "--silent"]
                repair_strategy = RepairStrategy.REINSTALL
            elif operation == RecipeOperation.REPAIR:
                executable = "winget"
                arguments = ["install", "--id", pkg_id, "--exact", "--force", "--silent"]
                repair_strategy = RepairStrategy.REINSTALL
            elif operation in (RecipeOperation.VERSION_CHECK, RecipeOperation.VERIFY):
                executable = identity.version_command[0] if identity.version_command else identity.executable
                arguments = identity.version_command[1:] if len(identity.version_command) > 1 else ["--version"]
        elif current_os == "Darwin" or pm == "brew":
            # macOS / Homebrew
            if operation == RecipeOperation.INSTALL:
                executable = "brew"
                arguments = ["install", pkg_id]
            elif operation == RecipeOperation.UPDATE:
                executable = "brew"
                arguments = ["upgrade", pkg_id]
            elif operation == RecipeOperation.UNINSTALL:
                executable = "brew"
                arguments = ["uninstall", pkg_id]
            elif operation in (RecipeOperation.REINSTALL, RecipeOperation.REPAIR):
                executable = "brew"
                arguments = ["reinstall", pkg_id]
                repair_strategy = RepairStrategy.REINSTALL
            elif operation in (RecipeOperation.VERSION_CHECK, RecipeOperation.VERIFY):
                executable = identity.version_command[0] if identity.version_command else identity.executable
                arguments = identity.version_command[1:] if len(identity.version_command) > 1 else ["--version"]
        else:
            # Linux / apt standard
            if operation == RecipeOperation.INSTALL:
                executable = "sudo"
                arguments = ["apt-get", "install", "-y", pkg_id]
            elif operation == RecipeOperation.UPDATE:
                executable = "sudo"
                arguments = ["apt-get", "install", "--only-upgrade", "-y", pkg_id]
            elif operation == RecipeOperation.UNINSTALL:
                executable = "sudo"
                arguments = ["apt-get", "remove", "-y", pkg_id]
            elif operation == RecipeOperation.REINSTALL:
                executable = "sudo"
                arguments = ["apt-get", "install", "--reinstall", "-y", pkg_id]
                repair_strategy = RepairStrategy.REINSTALL
            elif operation == RecipeOperation.REPAIR:
                executable = "sudo"
                arguments = ["apt-get", "install", "--reinstall", "-y", pkg_id]
                repair_strategy = RepairStrategy.REINSTALL
            elif operation in (RecipeOperation.VERSION_CHECK, RecipeOperation.VERIFY):
                executable = identity.version_command[0] if identity.version_command else identity.executable
                arguments = identity.version_command[1:] if len(identity.version_command) > 1 else ["--version"]

        return StructuredRecipe(
            recipe_id=f"syn_{identity.identity_id}_{operation.value.lower()}",
            recipe_version=1,
            identity_id=identity.identity_id,
            operation=operation,
            os=current_os,
            architecture="Any",
            package_manager=pm,
            executable=executable,
            arguments=arguments,
            verification_command=list(identity.version_command),
            expected_result={"return_code": 0},
            risk_base="Low" if operation in (RecipeOperation.VERSION_CHECK, RecipeOperation.VERIFY) else "Medium",
            official_url=identity.official_url,
            source="STATIC_DB",
            supported_environment={"os": current_os},
            repair_strategy=repair_strategy,
            validation_status=RecipeLifecycle.READY_FOR_EXECUTION,
            last_validated_at="",
            validation_frequency=86400,
        )


# Global singleton resolver
recipe_resolver = RecipeResolver()
