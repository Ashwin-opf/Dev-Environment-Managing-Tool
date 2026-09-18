"""
Agent Orchestrator
==================
The orchestrator (§9 of the spec) given the ability to plan, act across
multiple tools, and verify its own work.

This is NOT a separate subsystem — it IS the SHCE engine extended with:
  - Goal decomposition (high-level ask → ordered subtask plan)
  - Replanning loop (plan → act → verify → replan if failed)
  - Session working memory (this run only)
  - Long-term memory (the knowledge base, persistent)
  - Full reasoning trail (every tool call, input, result — inspectable)

All 12 discrete tools the agent can call are defined here as methods.
Nothing executes outside of dry-run → snapshot → execute → verify.
"""

from __future__ import annotations

import asyncio
import json
import platform
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ─── Tool imports ──────────────────────────────────────────────────────────────
from resolver import CanonicalAction, DependencyResolver
from sandbox import dry_run as sandbox_dry_run
import snapshot as snapshot_engine
from verifier import check as verifier_check
from risk_engine import assess as risk_assess

import logging
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
REASONING_LOG_FILE = BASE_DIR / "agent_reasoning_log.jsonl"

MAX_RETRY = 3  # Max replanning iterations per subtask


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── Working memory ────────────────────────────────────────────────────────────

@dataclass
class WorkingMemory:
    """Session-scoped working memory. Cleared between runs."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    goal: str = ""
    plan: List[Dict[str, Any]] = field(default_factory=list)
    completed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    tried_adapters: Dict[str, List[str]] = field(default_factory=dict)  # target → tried adapters
    reasoning_trail: List[Dict[str, Any]] = field(default_factory=list)

    def log(self, tool: str, inputs: Dict[str, Any], result: Any) -> None:
        entry = {
            "timestamp": _utc_now(),
            "tool": tool,
            "inputs": inputs,
            "result": result if isinstance(result, (dict, list, str, bool, int, float, type(None))) else str(result),
        }
        self.reasoning_trail.append(entry)

    def mark_complete(self, subtask: str) -> None:
        self.completed.append(subtask)

    def mark_failed(self, subtask: str) -> None:
        self.failed.append(subtask)

    def note_tried_adapter(self, target: str, adapter: str) -> None:
        self.tried_adapters.setdefault(target, []).append(adapter)

    def get_tried_adapters(self, target: str) -> List[str]:
        return self.tried_adapters.get(target, [])


# ─── Orchestrator ──────────────────────────────────────────────────────────────

class AgentOrchestrator:
    """
    The PC Doctor agent.  Receives a high-level goal, decomposes it into
    subtasks, and executes each with the full verify-before-store loop.
    """

    def __init__(self, approval_callback: Optional[Callable[[Dict[str, Any]], bool]] = None):
        self._approval_callback = approval_callback  # (risk_context) → bool
        self._resolver = DependencyResolver()

    # ══════════════════════════════════════════════════════════════════════════
    # TOOL LAYER  — 12 discrete, independently testable methods
    # ══════════════════════════════════════════════════════════════════════════

    def tool_resolver_build_tree(self, target: str, adapter_name: Optional[str] = None) -> Dict[str, Any]:
        """resolver.build_tree(target) → dependency graph"""
        action = CanonicalAction(intent="install", target=target, adapter_name=adapter_name)
        tree = self._resolver.build_tree(action)
        return tree.to_dict()

    def tool_adapter_resolve_latest(self, name: str, adapter_name: Optional[str] = None) -> str:
        """adapter.resolve_latest(name) → version string"""
        from adapters.registry import get_adapter, get_system_adapter
        adp = get_adapter(adapter_name) if adapter_name else get_system_adapter()
        if not adp:
            return "unknown"
        return adp.resolve_latest(name)

    def tool_adapter_install(self, name: str, adapter_name: Optional[str] = None,
                             constraints: Optional[List[str]] = None) -> str:
        """adapter.install(name, constraints) → generated command (never stored)"""
        from adapters.registry import get_adapter, get_system_adapter
        adp = get_adapter(adapter_name) if adapter_name else get_system_adapter()
        if not adp:
            return ""
        return adp.install(name, constraints or [])

    def tool_adapter_remove(self, name: str, adapter_name: Optional[str] = None) -> str:
        """adapter.remove(name) → generated command"""
        from adapters.registry import get_adapter, get_system_adapter
        adp = get_adapter(adapter_name) if adapter_name else get_system_adapter()
        if not adp:
            return ""
        return adp.remove(name)

    def tool_sandbox_dry_run(self, command: str) -> Dict[str, Any]:
        """sandbox.dry_run(command) → predicted diff"""
        return sandbox_dry_run(command)

    def tool_snapshot_create(self, action: str = "") -> Dict[str, Any]:
        """snapshot.create() → snapshot record with id"""
        return snapshot_engine.create(action=action)

    def tool_snapshot_revert(self, snapshot_id: str) -> Dict[str, Any]:
        """snapshot.revert(id) → revert plan"""
        return snapshot_engine.revert(snapshot_id)

    def tool_executor_run(self, command: str, timeout: int = 120) -> Dict[str, Any]:
        """executor.run(command) → result, exit state via CentralizedExecutionEngine"""
        from execution_engine import execution_engine
        start = time.time()
        try:
            outcome = execution_engine.execute_command(
                command=command,
                operation="EXECUTE",
                source="AGENT",
                timeout=timeout,
            )
            return {
                "success": outcome.success,
                "exit_code": outcome.return_code if outcome.return_code is not None else (-1 if not outcome.success else 0),
                "stdout": (outcome.stdout or "")[:3000],
                "stderr": (outcome.stderr or outcome.message or "")[:1000],
                "elapsed_s": round(time.time() - start, 2),
                "status": outcome.status,
                "verification": outcome.verification,
            }
        except Exception as exc:
            return {"success": False, "exit_code": -1, "stdout": "", "stderr": str(exc), "elapsed_s": 0}

    def tool_verifier_check(self, target: str, expected_state: Dict[str, Any]) -> Dict[str, Any]:
        """verifier.check(target, expected_state) → pass/fail + evidence"""
        return verifier_check(target, expected_state)

    def tool_kb_retrieve(self, symptom: str) -> Dict[str, Any]:
        """kb.retrieve(symptom) → ranked recipe matches + confidence"""
        try:
            import sqlite3
            db_path = str(BASE_DIR / "knowledge.db")
            con = sqlite3.connect(db_path, timeout=3)
            cur = con.cursor()
            try:
                cur.execute(
                    "SELECT issue, fix, os, confidence, reuse_count, source "
                    "FROM error_intelligence "
                    "WHERE issue LIKE ? OR fix LIKE ? "
                    "ORDER BY confidence DESC, reuse_count DESC LIMIT 5",
                    (f"%{symptom}%", f"%{symptom}%"),
                )
                rows = cur.fetchall()
                matches = [
                    {"issue": r[0], "fix": r[1], "os": r[2],
                     "confidence": r[3], "reuse_count": r[4], "source": r[5]}
                    for r in rows
                ]
                return {"matches": matches, "confidence": matches[0]["confidence"] if matches else 0.0}
            except sqlite3.OperationalError:
                # Fallback to repair_recipes table
                cur.execute(
                    "SELECT issue, command, os FROM repair_recipes WHERE issue LIKE ? LIMIT 5",
                    (f"%{symptom}%",),
                )
                rows = cur.fetchall()
                matches = [{"issue": r[0], "fix": r[1], "os": r[2], "confidence": 0.5, "reuse_count": 0} for r in rows]
                return {"matches": matches, "confidence": 0.5 if matches else 0.0}
        except Exception as exc:
            return {"matches": [], "confidence": 0.0, "error": str(exc)}

    def tool_kb_write(self, recipe: Dict[str, Any], verification_evidence: Dict[str, Any]) -> Dict[str, Any]:
        """
        kb.write(recipe, verification_evidence) → stored / discarded.
        Only persists if verification passed. Deduplicates near-identical entries.
        """
        if not verification_evidence.get("passed", False):
            return {"stored": False, "reason": "Verification failed — not persisted."}

        try:
            import sqlite3
            db_path = str(BASE_DIR / "knowledge.db")
            con = sqlite3.connect(db_path, timeout=5)
            cur = con.cursor()

            # Ensure table exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS error_intelligence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue TEXT,
                    fix TEXT,
                    os TEXT,
                    confidence REAL DEFAULT 0.5,
                    reuse_count INTEGER DEFAULT 0,
                    source TEXT,
                    target TEXT,
                    unverified INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)

            # Deduplicate: check if near-identical recipe exists
            cur.execute(
                "SELECT id, reuse_count FROM error_intelligence WHERE issue = ? AND os = ? LIMIT 1",
                (recipe.get("issue", ""), recipe.get("os", platform.system())),
            )
            existing = cur.fetchone()

            if existing:
                # Merge: increment reuse_count, raise confidence slightly
                new_confidence = min(1.0, (recipe.get("confidence", 0.7) + 0.05))
                cur.execute(
                    "UPDATE error_intelligence SET reuse_count = ?, confidence = ?, updated_at = ? WHERE id = ?",
                    (existing[1] + 1, new_confidence, _utc_now(), existing[0]),
                )
                con.commit()
                return {"stored": True, "action": "merged", "id": existing[0]}
            else:
                cur.execute(
                    "INSERT INTO error_intelligence (issue, fix, os, confidence, reuse_count, source, target, unverified, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        recipe.get("issue", ""),
                        recipe.get("fix", ""),
                        recipe.get("os", platform.system()),
                        recipe.get("confidence", 0.7),
                        0,
                        recipe.get("source", "agent"),
                        recipe.get("target", ""),
                        1 if recipe.get("unverified") else 0,
                        _utc_now(), _utc_now(),
                    ),
                )
                con.commit()
                new_id = cur.lastrowid
                return {"stored": True, "action": "inserted", "id": new_id}
        except Exception as exc:
            return {"stored": False, "error": str(exc)}

    def tool_model_propose_fix(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        model.propose_fix(context) → candidate command (Ollama, optional).
        Tagged unverified until confirmed by verifier.
        """
        try:
            import urllib.request
            payload = json.dumps({
                "model": "phi3:mini",
                "prompt": (
                    f"PC Doctor AI: Suggest a safe shell command to fix this problem.\n"
                    f"OS: {context.get('os', platform.system())}\n"
                    f"Problem: {context.get('symptom', '')}\n"
                    f"Tool: {context.get('target', '')}\n"
                    f"Respond with ONLY the shell command, nothing else."
                ),
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                command = data.get("response", "").strip().split("\n")[0]
                return {
                    "command": command,
                    "unverified": True,
                    "source": "ollama",
                    "model": "phi3:mini",
                }
        except Exception:
            return {"command": "", "unverified": True, "source": "ollama", "error": "Ollama not available"}

    def tool_risk_assess(self, action: Dict[str, Any], kb_history: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """risk.assess(action, history) → risk tier"""
        return risk_assess(action, kb_history)

    def tool_approval_request(self, action: Dict[str, Any], risk: Dict[str, Any]) -> bool:
        """approval.request(action, risk) → user decision (or auto if within ceiling)."""
        # Auto-approve low-risk actions
        if risk.get("tier") == "Low":
            return True
        # Use callback if provided (Control Center UI or CLI)
        if self._approval_callback:
            return self._approval_callback({"action": action, "risk": risk})
        # No callback: queue to Control Center (non-blocking, returns False to pause)
        return False

    # ══════════════════════════════════════════════════════════════════════════
    # PLANNING & EXECUTION
    # ══════════════════════════════════════════════════════════════════════════

    def _decompose_goal(self, goal: str) -> List[Dict[str, Any]]:
        """
        Decompose a high-level goal into an ordered subtask list.
        Each subtask: {type, target, adapter, description}
        """
        goal_lower = goal.lower()
        subtasks: List[Dict[str, Any]] = []

        # Simple goal parser — in production, this is backed by the KB + model
        action_words = {
            "install": "install",
            "add": "install",
            "setup": "install",
            "remove": "remove",
            "uninstall": "remove",
            "fix": "repair",
            "repair": "repair",
            "update": "update",
            "upgrade": "update",
        }
        intent = "install"
        for word, mapped in action_words.items():
            if word in goal_lower:
                intent = mapped
                break

        # Extract tool names (basic heuristic — phrases after action word)
        import re
        targets = re.findall(r'\b(?:my\s+)?([a-zA-Z][a-zA-Z0-9_\-\.]+)\b', goal)
        skip = {"my", "the", "all", "dev", "environment", "setup", "fix", "install",
                "remove", "update", "upgrade", "repair", "and", "or", "a", "an"}
        targets = [t for t in targets if t.lower() not in skip and len(t) > 2]

        if not targets:
            targets = [goal.strip()[:40]]

        for target in targets[:10]:
            subtasks.append({
                "type": intent,
                "target": target,
                "adapter": None,
                "description": f"{intent} {target}",
            })

        return subtasks

    def _execute_subtask(self, subtask: Dict[str, Any], memory: WorkingMemory, retry: int = 0) -> Dict[str, Any]:
        """
        Execute one subtask through the full tool chain.
        Returns result dict with success flag.
        """
        target = subtask["target"]
        intent = subtask["type"]
        preferred_adapter = subtask.get("adapter")

        # Skip already-tried adapters on retries
        tried = memory.get_tried_adapters(target)
        from adapters.registry import get_all_active_adapters
        available_adapters = [a for a in get_all_active_adapters() if a.name not in tried]

        if not available_adapters and tried:
            return {"success": False, "error": f"All adapters exhausted for {target}"}

        adapter = available_adapters[0] if not preferred_adapter else None
        if preferred_adapter:
            from adapters.registry import get_adapter
            adapter = get_adapter(preferred_adapter) or (available_adapters[0] if available_adapters else None)

        if not adapter:
            return {"success": False, "error": "No adapter available"}

        memory.note_tried_adapter(target, adapter.name)

        # ── Tier 1: KB retrieval ──────────────────────────────────────────────
        kb_result = self.tool_kb_retrieve(target)
        memory.log("kb.retrieve", {"symptom": target}, kb_result)

        command = ""
        recipe_source = "adapter"

        if kb_result["confidence"] >= 0.6 and kb_result["matches"]:
            command = kb_result["matches"][0]["fix"]
            recipe_source = "kb"
            memory.log("kb.hit", {"target": target, "confidence": kb_result["confidence"]}, command)
        else:
            # ── Tier 2: Generate command via adapter ──────────────────────────
            if intent == "install":
                command = self.tool_adapter_install(target, adapter.name)
            elif intent == "remove":
                command = self.tool_adapter_remove(target, adapter.name)
            else:
                # Repair: try model propose
                model_result = self.tool_model_propose_fix({"os": platform.system(), "symptom": f"{intent} {target}", "target": target})
                memory.log("model.propose_fix", {"target": target}, model_result)
                command = model_result.get("command", "")
                recipe_source = "ai_proposed_unverified"

        if not command:
            return {"success": False, "error": f"Could not generate command for {target}"}

        # ── Risk assessment ───────────────────────────────────────────────────
        dr = self.tool_sandbox_dry_run(command)
        memory.log("sandbox.dry_run", {"command": command}, dr)

        if dr.get("blocked"):
            return {"success": False, "error": f"Command blocked by safety layer: {command}"}

        risk = self.tool_risk_assess({"command": command, "target": target, "dry_run_result": dr})
        memory.log("risk.assess", {"command": command, "target": target}, risk)

        # ── Approval gate ─────────────────────────────────────────────────────
        approved = self.tool_approval_request({"command": command, "target": target}, risk)
        memory.log("approval.request", {"risk_tier": risk["tier"]}, {"approved": approved})

        if not approved:
            return {"success": False, "error": "Awaiting user approval via Control Center", "pending_approval": True}

        # ── Snapshot ──────────────────────────────────────────────────────────
        snap = self.tool_snapshot_create(action=f"{intent} {target}")
        memory.log("snapshot.create", {"action": f"{intent} {target}"}, snap)

        # ── Execute ───────────────────────────────────────────────────────────
        exec_result = self.tool_executor_run(command)
        memory.log("executor.run", {"command": command}, exec_result)

        if not exec_result["success"]:
            return {
                "success": False,
                "error": exec_result["stderr"][:200],
                "snapshot_id": snap["id"],
                "tried_command": command,
            }

        # ── Verify ────────────────────────────────────────────────────────────
        verify = self.tool_verifier_check(target, {"on_path": True, "adapter": adapter.name})
        memory.log("verifier.check", {"target": target}, verify)

        if not verify["passed"]:
            return {
                "success": False,
                "error": f"Verification failed: {verify['failures']}",
                "snapshot_id": snap["id"],
            }

        # ── KB Write (only on verified success) ───────────────────────────────
        recipe = {
            "issue": f"{intent} {target}",
            "fix": command,
            "os": platform.system(),
            "confidence": 0.75,
            "source": recipe_source,
            "target": target,
            "unverified": recipe_source == "ai_proposed_unverified",
        }
        kb_write_result = self.tool_kb_write(recipe, verify)
        memory.log("kb.write", {"recipe": recipe}, kb_write_result)

        return {
            "success": True,
            "target": target,
            "command": command,
            "adapter": adapter.name,
            "snapshot_id": snap["id"],
            "kb_write": kb_write_result,
            "evidence": verify["evidence"],
        }

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIC ENTRY POINT
    # ══════════════════════════════════════════════════════════════════════════

    def run(self, goal: str) -> Dict[str, Any]:
        """
        Execute a high-level goal end-to-end.

        Flow:
          goal → decompose → for each subtask:
            kb.retrieve → [model.propose if low confidence]
            risk.assess → approval.request → snapshot → execute → verify
            → replan if failed (up to MAX_RETRY) → kb.write on success
          → log full reasoning trail → return outcome
        """
        memory = WorkingMemory(goal=goal)
        memory.log("agent.start", {"goal": goal, "os": platform.system()}, {})

        subtasks = self._decompose_goal(goal)
        memory.plan = subtasks
        memory.log("goal.decompose", {"goal": goal}, {"subtasks": [s["description"] for s in subtasks]})

        results: List[Dict[str, Any]] = []

        for subtask in subtasks:
            success = False
            last_result: Dict[str, Any] = {}

            for attempt in range(MAX_RETRY):
                result = self._execute_subtask(subtask, memory, retry=attempt)
                last_result = result
                memory.log(f"subtask.attempt.{attempt + 1}", subtask, result)

                if result.get("success"):
                    success = True
                    memory.mark_complete(subtask["description"])
                    break

                if result.get("pending_approval"):
                    # Don't retry — it's waiting for user
                    break

                # Replanning: different adapter on next attempt
                if attempt < MAX_RETRY - 1:
                    memory.log("agent.replan", {"reason": result.get("error")}, {"attempt": attempt + 2})

            if not success:
                memory.mark_failed(subtask["description"])

            results.append({"subtask": subtask["description"], "success": success, "detail": last_result})

        # Persist reasoning trail
        try:
            with open(REASONING_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "session_id": memory.session_id,
                    "goal": goal,
                    "completed": memory.completed,
                    "failed": memory.failed,
                    "trail": memory.reasoning_trail,
                    "timestamp": _utc_now(),
                }) + "\n")
        except Exception:
            pass

        overall_success = len(memory.failed) == 0 and len(memory.completed) > 0

        return {
            "ok": overall_success,
            "session_id": memory.session_id,
            "goal": goal,
            "completed": memory.completed,
            "failed": memory.failed,
            "results": results,
            "reasoning_trail": memory.reasoning_trail,
            "summary": (
                f"Completed {len(memory.completed)}/{len(subtasks)} subtasks. "
                + (f"Failed: {', '.join(memory.failed)}." if memory.failed else "All tasks succeeded.")
            ),
        }
