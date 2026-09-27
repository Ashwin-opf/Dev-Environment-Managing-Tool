"""
execution_plan.py — Execution Request, Plan, and Resolver Abstraction.

Implements the authoritative execution context model:
    ExecutionRequest → ExecutionResolver → ExecutionPlan

Invariants:
1. Untrusted, AI-generated, RAG-derived, or raw unknown requests NEVER receive
   fabricated maximum trust (1.0) or maximum confidence (1.0).
2. Raw / ad-hoc commands are never wrapped in a fake StructuredRecipe with false Low risk.
3. Distinguishes authentic provenance classes:
   - STATIC_RECIPE (high trust, validated knowledge_static.db)
   - DYNAMIC_CANDIDATE (bounded trust, knowledge_dynamic.db)
   - AI_RAG_CANDIDATE (untrusted candidate, <= 0.40 trust, <= 0.40 confidence)
   - UNRESOLVED_RAW (low trust, <= 0.35 trust, <= 0.40 confidence)
4. Evaluates tier and derives explicit approval_required requirements.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from canonical_identity import canonical_store
from execution_tier import ExecutionTier, compute_live_risk, select_execution_tier
from recipe_engine import RecipeOperation, StructuredRecipe, recipe_resolver


class ProvenanceClass(str, Enum):
    """Authoritative classification of execution request origin and authenticity."""
    STATIC_RECIPE = "STATIC_RECIPE"          # knowledge_static.db / validated static recipe
    DYNAMIC_CANDIDATE = "DYNAMIC_CANDIDATE"  # knowledge_dynamic.db / validated dynamic source
    AI_RAG_CANDIDATE = "AI_RAG_CANDIDATE"    # AI / RAG / agent / assistant generated
    SOURCE_MIGRATION = "SOURCE_MIGRATION"    # Explicit cross-source migration plan
    UNRESOLVED_RAW = "UNRESOLVED_RAW"        # Raw unknown command / unverified provenance


@dataclass
class ExecutionRequest:
    """Incoming request for system inspection or mutation."""
    command: Optional[str] = None
    recipe: Optional[StructuredRecipe] = None
    target: Optional[str] = None
    operation: str = "REPAIR"
    source: str = "UNRESOLVED"
    provenance_hint: Optional[ProvenanceClass] = None
    elevate: bool = False
    scope: Optional[str] = None
    title: Optional[str] = None
    timeout: int = 120
    original_problem: Optional[str] = None
    trigger_shce: bool = True
    pm: Optional[str] = None
    tier: Optional[ExecutionTier] = None
    owner_id: Optional[str] = None
    approved: Optional[bool] = None
    trust: Optional[float] = None
    confidence: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    """Fully resolved, policy-evaluated plan ready for authoritative execution."""
    request: ExecutionRequest
    clean_command: str
    target_name: str
    operation_enum: RecipeOperation
    recipe: Optional[StructuredRecipe]       # None for raw / untrusted ad-hoc commands!
    provenance_class: ProvenanceClass
    source: str
    trust_score: float                       # Derived from authentic provenance, never fabricated
    confidence_score: float                  # Derived from evidence, never fabricated
    risk_score: float                        # Evaluated live risk
    tier: ExecutionTier                      # Evaluated execution tier
    tier_reason: str
    approval_required: bool                  # True if tier.requires_approval
    approved: bool                           # Effective authorization state (True if auto-authorized or user-approved)
    requires_elevation: bool
    scope: str
    pm: str
    is_automatically_authorized: bool = False
    authorization_reason: str = ""


class ExecutionResolver:
    """Authoritative resolver transforming an ExecutionRequest into a hardened ExecutionPlan."""

    @staticmethod
    def _infer_target(command: str, title: Optional[str] = None) -> str:
        if title:
            t_low = title.lower()
            for candidate in ["python", "pip", "node", "npm", "git", "docker", "vscode", "mysql", "ollama", "rust", "cargo", "go"]:
                if candidate in t_low:
                    return candidate
        c_low = command.lower()
        for candidate in ["python", "pip", "node", "npm", "git", "docker", "vscode", "mysql", "ollama", "rustc", "cargo", "go"]:
            if candidate in c_low:
                return candidate
        tokens = command.strip().split()
        if tokens:
            first = os.path.basename(tokens[0]).replace(".exe", "").lower()
            if first not in ("powershell", "cmd", "sudo", "bash", "sh", "setx", "echo") and len(first) > 1:
                return first
            if len(tokens) > 1:
                second = os.path.basename(tokens[1]).replace(".exe", "").lower()
                if len(second) > 1 and not second.startswith("-"):
                    return second
        return "system"

    @staticmethod
    def _detect_pm(command: str) -> str:
        c_low = command.lower()
        for pm in ["winget", "choco", "scoop", "apt-get", "apt", "dnf", "pacman", "zypper", "apk", "brew", "flatpak", "snap", "pip", "npm", "cargo"]:
            if pm in c_low:
                return pm
        return "system"

    @classmethod
    def _command_matches_recipe(cls, command: str, recipe: StructuredRecipe) -> bool:
        if not command or not recipe:
            return False
        clean = command.strip()
        recipe_cmd = recipe.to_command_string().strip()
        if clean == recipe_cmd:
            return True
        if recipe.executable:
            first_tok = clean.split()[0] if clean.split() else ""
            if first_tok == recipe.executable or first_tok.endswith(recipe.executable):
                return True
        return False

    def resolve(self, request: ExecutionRequest, machine_state: Optional[Any] = None) -> ExecutionPlan:
        """Resolves an ExecutionRequest into an ExecutionPlan without inventing trust or recipes."""
        clean_cmd = (request.command or "").strip()
        target_name = request.target or self._infer_target(clean_cmd, request.title)

        # 1. Determine Operation
        op_enum = RecipeOperation.REPAIR
        if request.operation:
            try:
                op_enum = RecipeOperation(request.operation.upper())
            except Exception:
                op_enum = RecipeOperation.REPAIR

        # Detect observation / info commands
        if not clean_cmd.startswith("#") and clean_cmd:
            c_low = clean_cmd.lower()
            if c_low.startswith("echo ") or c_low.endswith("--version") or c_low.endswith("-v") or c_low == "echo":
                if op_enum not in (RecipeOperation.VERSION_CHECK, RecipeOperation.VERIFY):
                    op_enum = RecipeOperation.VERSION_CHECK

        pm = request.pm or self._detect_pm(clean_cmd)

        # 2. Identify Provenance Class & Candidate Recipe
        recipe: Optional[StructuredRecipe] = None
        source_upper = (request.source or "UNRESOLVED").upper()

        is_ai_origin = (
            request.provenance_hint == ProvenanceClass.AI_RAG_CANDIDATE
            or source_upper in ("AI", "RAG", "AGENT", "ASSISTANT", "AI_GENERATED")
        )

        if request.recipe is not None:
            # Explicit recipe provided by caller
            if is_ai_origin:
                provenance_class = ProvenanceClass.AI_RAG_CANDIDATE
                recipe = None  # Do not treat AI output as an authoritative recipe
            elif request.recipe.source == "STATIC_DB":
                provenance_class = ProvenanceClass.STATIC_RECIPE
                recipe = request.recipe
            elif request.recipe.source == "DYNAMIC_DB":
                provenance_class = ProvenanceClass.DYNAMIC_CANDIDATE
                recipe = request.recipe
            else:
                provenance_class = ProvenanceClass.UNRESOLVED_RAW
                recipe = request.recipe
        elif is_ai_origin:
            # AI / RAG / Agent generated command — NEVER promote to static recipe
            provenance_class = ProvenanceClass.AI_RAG_CANDIDATE
            recipe = None
        elif source_upper == "STATIC_DB":
            # Explicitly requested static recipe resolution
            provenance_class = ProvenanceClass.STATIC_RECIPE
            candidate = recipe_resolver.resolve_recipe(target_name, operation=op_enum)
            if candidate and (not clean_cmd or self._command_matches_recipe(clean_cmd, candidate)):
                recipe = candidate
            else:
                recipe = None
        elif source_upper == "DYNAMIC_DB":
            provenance_class = ProvenanceClass.DYNAMIC_CANDIDATE
            recipe = None
        elif request.provenance_hint == ProvenanceClass.SOURCE_MIGRATION or source_upper == "SOURCE_MIGRATION":
            provenance_class = ProvenanceClass.SOURCE_MIGRATION
            recipe = None
        else:
            # Check if there is an existing verified static recipe that matches the command
            candidate = recipe_resolver.resolve_recipe(target_name, operation=op_enum)
            if candidate and clean_cmd and self._command_matches_recipe(clean_cmd, candidate):
                provenance_class = ProvenanceClass.STATIC_RECIPE
                recipe = candidate
            else:
                provenance_class = ProvenanceClass.UNRESOLVED_RAW
                recipe = None

        # 3. Assign Trust and Confidence based on authentic provenance (NEVER INVENTED)
        if provenance_class == ProvenanceClass.STATIC_RECIPE:
            trust_score = 1.0
            confidence_score = request.confidence if request.confidence is not None else 0.95
            effective_source = "STATIC_DB"
        elif provenance_class == ProvenanceClass.DYNAMIC_CANDIDATE:
            trust_score = min(0.85, max(0.70, request.trust if request.trust is not None else 0.75))
            confidence_score = min(0.85, request.confidence if request.confidence is not None else 0.70)
            effective_source = "DYNAMIC_DB"
        elif provenance_class == ProvenanceClass.SOURCE_MIGRATION:
            trust_score = 0.95
            confidence_score = request.confidence if request.confidence is not None else 0.90
            effective_source = "SOURCE_MIGRATION"
        elif provenance_class == ProvenanceClass.AI_RAG_CANDIDATE:
            # Untrusted dynamic candidate — strictly bounded <= 0.40
            trust_score = min(0.40, request.trust if request.trust is not None else 0.40)
            confidence_score = min(0.40, request.confidence if request.confidence is not None else 0.40)
            effective_source = source_upper if source_upper != "UNRESOLVED" else "AI"
        else:
            # UNRESOLVED_RAW — strictly bounded <= 0.35 trust, <= 0.40 confidence
            trust_score = min(0.35, request.trust if request.trust is not None else 0.30)
            confidence_score = min(0.40, request.confidence if request.confidence is not None else 0.35)
            effective_source = request.source or "UNRESOLVED"

        # If recipe is available and clean_cmd was empty, derive clean_cmd from recipe
        if not clean_cmd and recipe:
            clean_cmd = recipe.to_command_string()

        # 4. Privilege & Elevation requirements
        requires_elevation = bool(request.elevate or request.scope == "machine")
        scope = request.scope or ("machine" if requires_elevation else "user")

        # 5. Live Risk & Tier Evaluation
        if machine_state is None:
            from state_refresh import state_refresher
            machine_state = state_refresher.refresh_machine_state(target_identity=target_name)

        risk_score = compute_live_risk(
            recipe=recipe,
            machine_state=machine_state,
            requires_elevation=requires_elevation,
            command=clean_cmd,
            operation=op_enum,
        )

        if request.tier is not None:
            tier = request.tier
            tier_reason = f"Explicit tier: {tier}"
        else:
            tier, tier_reason = select_execution_tier(
                recipe=recipe,
                trust_score=trust_score,
                risk_score=risk_score,
                confidence_score=confidence_score,
                machine_state=machine_state,
                command=clean_cmd,
                operation=op_enum,
            )

        approval_required = tier.requires_approval

        is_auto_auth, auth_reason = self.evaluate_authorization(
            provenance_class=provenance_class,
            recipe=recipe,
            target_name=target_name,
            trust_score=trust_score,
            tier=tier,
            source=effective_source,
            request_approved=request.approved,
        )

        plan_approved = False
        if request.approved is False:
            plan_approved = False
        elif request.approved is True:
            plan_approved = True
        elif is_auto_auth:
            plan_approved = True
        elif not approval_required:
            plan_approved = True

        return ExecutionPlan(
            request=request,
            clean_command=clean_cmd,
            target_name=target_name,
            operation_enum=op_enum,
            recipe=recipe,
            provenance_class=provenance_class,
            source=effective_source,
            trust_score=trust_score,
            confidence_score=confidence_score,
            risk_score=risk_score,
            tier=tier,
            tier_reason=tier_reason,
            approval_required=approval_required,
            approved=plan_approved,
            requires_elevation=requires_elevation,
            scope=scope,
            pm=pm,
            is_automatically_authorized=is_auto_auth,
            authorization_reason=auth_reason,
        )

    @staticmethod
    def evaluate_authorization(
        provenance_class: ProvenanceClass,
        recipe: Optional[StructuredRecipe],
        target_name: str,
        trust_score: float,
        tier: ExecutionTier,
        source: str,
        request_approved: Optional[bool] = None,
    ) -> Tuple[bool, str]:
        """
        Centrally derives execution authorization based on provenance, trust, target verification,
        and user approval state.

        Separation of Concerns:
        - Trust: Derived authentically from provenance (never fabricated).
        - Risk: Evaluated dynamic live risk.
        - Approval: User explicit confirmation / rejection state.
        - Authorization: Central policy decision whether execution is permitted to proceed to Live Safety Gate.
        - Safety: Live Safety Gate remains the final absolute runtime blocker.
        """
        # 1. Explicit user rejection takes absolute precedence
        if request_approved is False:
            return False, "Explicit user disapproval/rejection."

        # 2. Blocked tier cannot be authorized
        if tier == ExecutionTier.BLOCKED:
            return False, "Blocked by execution tier policy."

        # 3. Untrusted, AI/RAG, and raw unresolved commands require manual approval
        if provenance_class in (ProvenanceClass.AI_RAG_CANDIDATE, ProvenanceClass.UNRESOLVED_RAW):
            return False, "AI/RAG or unresolved provenance requires explicit user review and approval."

        if source.upper() in ("AI", "RAG", "AGENT", "ASSISTANT", "AI_GENERATED", "UNRESOLVED"):
            return False, "Unverified source requires explicit user review and approval."

        # 4. Trusted STATIC_DB / Golden Recipe Automatic Authorization
        # Risk score alone does NOT force manual approval for trusted, verified STATIC_DB golden recipes.
        # LIVE Safety Gate remains the final absolute blocker.
        if (
            (provenance_class == ProvenanceClass.STATIC_RECIPE or source.upper() == "STATIC_DB" or (recipe and recipe.source == "STATIC_DB"))
            and recipe is not None
            and trust_score >= 0.85
            and target_name
        ):
            return True, "Policy: trusted STATIC_DB golden recipe automatically authorized."

        # Default: requires manual approval if tier demands it
        if tier.requires_approval:
            return False, f"Execution tier '{tier.value}' requires explicit user approval."
        return False, "Standard execution path."


execution_resolver = ExecutionResolver()
