"""
plan_freeze.py — Batch Plan Freezing & Resource-Level Concurrency Locking.

Implements:
- Plan Freeze:
  When a batch plan is constructed, trust, risk, confidence, and execution tier are FROZEN.
  Before EACH step is mutated, the Live Pre-Execution Safety Gate evaluates DYNAMICALLY.
  If machine state changed (e.g. disk space degraded below threshold), the step cannot
  blindly execute, even though the plan tier remains frozen.
- Fine-Grained Resource Locking:
  No global lock. Locks only affected resources (e.g. package manager "winget",
  target identity "git") allowing unrelated tools to run concurrently.
  Releases locks only after execution AND verification complete.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from authoritative_safety import authoritative_safety, SafetyGateResult, BlockedReason
from execution_tier import ExecutionTier
from recipe_engine import StructuredRecipe


@dataclass
class FrozenPlanStep:
    step_id: str
    recipe: StructuredRecipe
    frozen_tier: ExecutionTier
    frozen_trust: float
    frozen_risk: float
    frozen_confidence: float
    frozen_at: str
    status: str = "PENDING"              # PENDING, EXECUTING, COMPLETED, BLOCKED, FAILED
    live_safety_result: Optional[SafetyGateResult] = None
    execution_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "recipe_id": self.recipe.recipe_id,
            "identity_id": self.recipe.identity_id,
            "command": self.recipe.to_command_string(),
            "frozen_tier": self.frozen_tier.value,
            "frozen_trust": self.frozen_trust,
            "frozen_risk": self.frozen_risk,
            "frozen_confidence": self.frozen_confidence,
            "frozen_at": self.frozen_at,
            "status": self.status,
            "live_safety_result": self.live_safety_result.to_dict() if self.live_safety_result else None,
        }


@dataclass
class BatchPlan:
    plan_id: str
    steps: List[FrozenPlanStep]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "steps": [s.to_dict() for s in self.steps],
        }


class ResourceLockManager:
    """
    Fine-grained resource lock manager.
    Locks specific resources (e.g. package_manager:winget, target:git).
    Allows unrelated tools to execute concurrently without a global lock.
    """

    def __init__(self) -> None:
        self._global_mutex = threading.Lock()
        self._active_locks: Dict[str, str] = {}  # resource_key -> owner_id

    def acquire_resources(self, owner_id: str, resources: List[str], timeout: float = 10.0) -> bool:
        """Attempt to acquire locks for all requested resources."""
        start = time.time()
        while time.time() - start < timeout:
            with self._global_mutex:
                # Check if all resources are free
                can_acquire = all(r not in self._active_locks or self._active_locks[r] == owner_id for r in resources)
                if can_acquire:
                    for r in resources:
                        self._active_locks[r] = owner_id
                    return True
            time.sleep(0.05)
        return False

    def release_resources(self, owner_id: str, resources: List[str]) -> None:
        """Release locks for all resources owned by owner_id."""
        with self._global_mutex:
            for r in resources:
                if self._active_locks.get(r) == owner_id:
                    del self._active_locks[r]

    def is_locked(self, resource: str) -> bool:
        with self._global_mutex:
            return resource in self._active_locks


# Global singleton lock manager
resource_lock_mgr = ResourceLockManager()


def create_frozen_batch_plan(
    plan_id: str,
    recipes_with_scores: List[Tuple[StructuredRecipe, ExecutionTier, float, float, float]],
) -> BatchPlan:
    """
    Creates a batch plan with frozen tiers and ratings.
    """
    now = datetime.now(timezone.utc).isoformat()
    steps = []
    for idx, (recipe, tier, trust, risk, conf) in enumerate(recipes_with_scores):
        step = FrozenPlanStep(
            step_id=f"{plan_id}_step_{idx+1}",
            recipe=recipe,
            frozen_tier=tier,
            frozen_trust=trust,
            frozen_risk=risk,
            frozen_confidence=conf,
            frozen_at=now,
        )
        steps.append(step)
    return BatchPlan(plan_id=plan_id, steps=steps)


def evaluate_step_live_safety_gate(
    step: FrozenPlanStep,
    required_disk_gb: float = 2.0,
    machine_state: Optional[Any] = None,
) -> SafetyGateResult:
    """
    Runs the live pre-execution safety gate immediately before a step's execution.
    The step's frozen_tier remains frozen, but live safety is evaluated against current machine state.
    """
    cmd = step.recipe.to_command_string()
    is_static = (step.recipe.source == "STATIC_DB")

    if machine_state is None:
        try:
            from state_refresh import state_refresher
            machine_state = state_refresher.refresh_machine_state(target_identity=step.recipe.identity_id)
        except Exception:
            machine_state = None

    res = authoritative_safety.live_pre_execution_gate(
        command=cmd,
        operation=step.recipe.operation.value,
        required_disk_gb=required_disk_gb,
        is_static_recipe=is_static,
        recipe=step.recipe,
        machine_state=machine_state,
        package_manager=step.recipe.package_manager,
        target_resource=step.recipe.identity_id,
    )
    step.live_safety_result = res
    if not res.allowed:
        step.status = "BLOCKED"
    return res
