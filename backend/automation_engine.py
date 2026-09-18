"""
automation_engine.py — Background Automation & Promotion Engine for PC Doctor.

Enforces:
- Section 18 Background Automation Rules:
  - Checks user idle state before starting any mutation.
  - If user becomes active BEFORE EXECUTE: defers/pauses.
  - If EXECUTE has already started: DO NOT INTERRUPT. Let it complete, then verify, log, and refresh.
- Section 11 Dynamic -> Static Promotion:
  - Local successful execution only yields PROMOTION_ELIGIBLE (never PROMOTED_TO_STATIC).
  - Promotion to Static DB strictly requires independent validation evidence across
    distinct environments matching declared scope, review, and explicit promotion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from recipe_engine import RecipeLifecycle, StructuredRecipe


@dataclass
class ValidationEvidence:
    environment_id: str                   # Unique machine/container ID
    os: str                               # e.g. "Windows 11"
    architecture: str                     # e.g. "x64"
    package_manager: str                  # e.g. "winget"
    timestamp: str
    verified: bool
    details: Dict[str, Any] = field(default_factory=dict)


class AuthoritativePromotionEngine:
    """Manages candidate recipe promotion according to architectural standards."""

    MIN_INDEPENDENT_ENVIRONMENTS = 3

    def record_execution_outcome(
        self,
        recipe: StructuredRecipe,
        execution_success: bool,
        verification_success: bool,
        env_id: str = "local",
    ) -> RecipeLifecycle:
        """
        Processes execution outcome.
        ARCHITECTURAL RULE:
        A successful local execution yields PROMOTION_ELIGIBLE.
        It NEVER directly grants PROMOTED_TO_STATIC.
        """
        if not execution_success:
            recipe.validation_status = RecipeLifecycle.EXECUTION_FAILED
            return recipe.validation_status

        if not verification_success:
            recipe.validation_status = RecipeLifecycle.VERIFICATION_FAILED
            return recipe.validation_status

        # Command succeeded and real-world state is verified
        # Local execution grants PROMOTION_ELIGIBLE only
        recipe.validation_status = RecipeLifecycle.PROMOTION_ELIGIBLE
        return recipe.validation_status

    def evaluate_for_static_promotion(
        self,
        recipe: StructuredRecipe,
        evidence_list: List[ValidationEvidence],
        user_approved_review: bool = False,
    ) -> tuple[bool, RecipeLifecycle, str]:
        """
        Evaluates whether recipe meets all 5 promotion requirements:
        1. Successful validation.
        2. Independent validation across environments matching declared scope.
        3. Appropriate evidence from distinct environments.
        4. Review/approval.
        5. Promotion.
        """
        if recipe.validation_status not in (RecipeLifecycle.PROMOTION_ELIGIBLE, RecipeLifecycle.REVIEW_REQUIRED):
            return False, recipe.validation_status, "Recipe is not in promotion eligible state."

        # Verify evidence comes from distinct environments matching recipe scope
        valid_envs: Set[str] = set()
        for ev in evidence_list:
            if not ev.verified:
                continue
            # Match declared OS if not "Any"
            if recipe.os != "Any" and recipe.os.lower() not in ev.os.lower():
                continue
            valid_envs.add(ev.environment_id)

        if len(valid_envs) < self.MIN_INDEPENDENT_ENVIRONMENTS:
            recipe.validation_status = RecipeLifecycle.REVIEW_REQUIRED
            return False, recipe.validation_status, (
                f"Insufficient cross-environment evidence. Found {len(valid_envs)} independent environments; "
                f"minimum {self.MIN_INDEPENDENT_ENVIRONMENTS} matching declared scope required."
            )

        if not user_approved_review:
            recipe.validation_status = RecipeLifecycle.REVIEW_REQUIRED
            return False, recipe.validation_status, "Cross-environment evidence validated. Awaiting final promotion review."

        recipe.validation_status = RecipeLifecycle.PROMOTED_TO_STATIC
        recipe.source = "STATIC_DB"
        return True, recipe.validation_status, "Recipe successfully promoted to Static DB."


class BackgroundAutomationController:
    """Manages background task execution respecting user idle state."""

    def __init__(self) -> None:
        self._user_active: bool = False
        self._last_active_time: float = time.time()
        self._executing_mutation: bool = False

    def mark_user_activity(self) -> None:
        self._user_active = True
        self._last_active_time = time.time()

    def is_idle(self, idle_threshold_seconds: float = 60.0) -> bool:
        return (time.time() - self._last_active_time) >= idle_threshold_seconds

    def should_defer_pre_execution(self) -> bool:
        """
        Called immediately before entering EXECUTE stage.
        If user is active, defer/pause mutation.
        """
        if self._executing_mutation:
            # Already in execute: DO NOT INTERRUPT
            return False
        return not self.is_idle()

    def enter_execution(self) -> None:
        """Flags that mutation execution has started (non-interruptible)."""
        self._executing_mutation = True

    def exit_execution(self) -> None:
        """Flags that mutation has concluded."""
        self._executing_mutation = False


promotion_engine = AuthoritativePromotionEngine()
background_automation = BackgroundAutomationController()
