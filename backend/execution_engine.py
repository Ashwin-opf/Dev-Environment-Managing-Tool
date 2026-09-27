"""
execution_engine.py — Centralized Authoritative Execution Engine for PC Doctor.

The SINGLE authoritative pipeline for all command and recipe execution.
Orchestrates:
1. Canonical identity & recipe resolution.
2. Dynamic risk evaluation & tier selection.
3. Fine-grained resource locking.
4. Live Pre-Execution Safety Gate (always evaluated dynamically).
5. Process execution with real-time stdout/stderr capture (synchronous or SSE stream).
6. Result classification via result_classifier.
7. Multi-tier verification via verification_engine (FAST, CONTROLLED, FULL).
8. 16-field structured logging via structured_logger (secrets redacted).
9. Post-mutation real machine state refresh.
10. Resource lock release.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Tuple

from authoritative_safety import authoritative_safety, BlockedReason, SafetyGateResult
from canonical_identity import canonical_store
from execution_plan import (
    ExecutionPlan,
    ExecutionRequest,
    ExecutionResolver,
    ProvenanceClass,
    execution_resolver,
)
from execution_tier import ExecutionTier, compute_live_risk, select_execution_tier
from plan_freeze import resource_lock_mgr
from recipe_engine import RecipeLifecycle, RecipeOperation, RepairStrategy, StructuredRecipe, recipe_resolver
from result_classifier import classify_execution_result
from state_refresh import state_refresher
from structured_logger import structured_logger
from verification_engine import VerificationLevel, VerificationPolicy, VerificationResult, VerificationStatus, verification_engine


@dataclass
class ExecutionOutcome:
    success: bool
    status: str                         # "VERIFIED", "EXECUTED", "EXECUTION_FAILED", "VERIFICATION_FAILED", "VERIFICATION_TIMEOUT", "BLOCKED"
    operation: str
    target: str
    command: str
    return_code: Optional[int]
    stdout: str
    stderr: str
    classification: str
    verification: Dict[str, Any]
    tier: str = "TIER_1_AUTO"
    trust: float = 1.0
    risk: float = 0.0
    confidence: float = 1.0
    message: str = ""
    execution_status: str = "EXECUTION_SUCCEEDED"
    verification_status: str = "VERIFIED"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "execution_status": self.execution_status,
            "verification_status": self.verification_status,
            "operation": self.operation,
            "target": self.target,
            "command": self.command,
            "return_code": self.return_code,
            "stdout": self.stdout[-2000:] if self.stdout else "",
            "stderr": self.stderr[-1000:] if self.stderr else "",
            "classification": self.classification,
            "verification": self.verification,
            "tier": self.tier,
            "trust": self.trust,
            "risk": self.risk,
            "confidence": self.confidence,
            "message": self.message,
            "details": self.details,
        }


class SafetyAuthorizationViolation(RuntimeError):
    """Raised when mutation execution is attempted without explicit Live Safety Gate clearance."""
    pass


class CentralizedExecutionEngine:
    """The authoritative execution coordinator."""

    @staticmethod
    def _assert_safety_authorized(safety_res: Optional[SafetyGateResult]) -> None:
        """
        Enforces the permanent architectural invariant:
        ExecutionTier describes the protection/approval level, NOT execution authorization.
        Execution authorization can only come from authoritative_safety.live_pre_execution_gate.
        """
        if safety_res is None or not getattr(safety_res, "allowed", False):
            raise SafetyAuthorizationViolation(
                f"Execution rejected: Authoritative live safety gate clearance is required before process execution. "
                f"Result: {safety_res}"
            )

    def execute_recipe(
        self,
        recipe: StructuredRecipe,
        verification_level: VerificationLevel = VerificationLevel.FAST,
        trust_score: Optional[float] = None,
        confidence_score: Optional[float] = None,
        original_problem: Optional[str] = None,
        timeout: int = 120,
        machine_state: Optional[Any] = None,
        approved: bool = True,
    ) -> ExecutionOutcome:
        """Synchronously executes a structured recipe through the full authoritative pipeline."""
        target_name = recipe.identity_id
        cmd_str = recipe.to_command_string()

        # 1. Authoritative Plan Resolution
        req = ExecutionRequest(
            recipe=recipe,
            command=cmd_str,
            target=target_name,
            operation=recipe.operation.value,
            source=recipe.source,
            timeout=timeout,
            original_problem=original_problem,
            approved=approved,
            trust=trust_score,
            confidence=confidence_score,
        )
        plan = execution_resolver.resolve(req, machine_state=machine_state)
        tier = plan.tier
        tier_reason = plan.tier_reason
        trust_score = plan.trust_score
        confidence_score = plan.confidence_score
        risk_score = plan.risk_score

        if tier == ExecutionTier.BLOCKED:
            structured_logger.log_event(
                operation=recipe.operation.value,
                application=target_name,
                identity=target_name,
                status="BLOCKED",
                message=f"Execution blocked: {tier_reason}",
                command=cmd_str,
                recipe_id=recipe.recipe_id,
                source=recipe.source,
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
            )
            return ExecutionOutcome(
                success=False,
                status="BLOCKED",
                execution_status="EXECUTION_FAILED",
                verification_status="NOT_RUN",
                operation=recipe.operation.value,
                target=target_name,
                command=cmd_str,
                return_code=None,
                stdout="",
                stderr=tier_reason,
                classification="RISK_ABOVE_HARD_LIMIT",
                verification={},
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
                message=tier_reason,
            )

        # 2. Centralized Approval & Authorization Enforcement
        if approved is False or (not plan.is_automatically_authorized and tier.requires_approval and not approved):
            reason = "Execution cancelled: user explicitly declined approval." if approved is False else f"Execution tier '{tier.value}' requires explicit user approval before execution."
            structured_logger.log_event(
                operation=recipe.operation.value,
                application=target_name,
                identity=target_name,
                status="APPROVAL_REQUIRED",
                message=reason,
                command=cmd_str,
                recipe_id=recipe.recipe_id,
                source=recipe.source,
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
            )
            return ExecutionOutcome(
                success=False,
                status="APPROVAL_REQUIRED",
                execution_status="NOT_RUN",
                verification_status="NOT_RUN",
                operation=recipe.operation.value,
                target=target_name,
                command=cmd_str,
                return_code=None,
                stdout="",
                stderr=reason,
                classification="APPROVAL_REQUIRED",
                verification={},
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
                message=reason,
                details={"requires_approval": True, "tier": tier.value, "approval_required": True},
            )

        # 2. Acquire fine-grained resource locks
        owner_id = f"exec_{target_name}_{int(time.time()*1000)}"
        resources = [f"pm:{recipe.package_manager.lower()}", f"tool:{target_name.lower()}"]
        acquired = resource_lock_mgr.acquire_resources(owner_id, resources, timeout=5.0)
        if not acquired:
            msg = f"Resource lock conflict: tool or package manager {recipe.package_manager} is currently busy."
            return ExecutionOutcome(
                success=False,
                status="BLOCKED",
                operation=recipe.operation.value,
                target=target_name,
                command=cmd_str,
                return_code=None,
                stdout="",
                stderr=msg,
                classification="RESOURCE_BUSY",
                verification={},
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
                message=msg,
            )

        try:
            # 2. Privilege Resolution
            from privilege_manager import privilege_manager
            privilege_manager.resolve_privilege(tier=tier)

            # 3. Live Pre-Execution Safety Gate
            m_state = machine_state if machine_state is not None else state_refresher.refresh_machine_state(target_identity=target_name)
            safety_res = authoritative_safety.live_pre_execution_gate(
                command=cmd_str,
                operation=recipe.operation.value,
                is_static_recipe=(recipe.source == "STATIC_DB"),
                recipe=recipe,
                machine_state=m_state,
                package_manager=recipe.package_manager,
                target_resource=target_name,
                owner_id=owner_id,
            )
            if not safety_res.allowed:
                msg = f"Live pre-execution safety gate blocked execution: {safety_res.message}"
                structured_logger.log_event(
                    operation=recipe.operation.value,
                    application=target_name,
                    identity=target_name,
                    status="BLOCKED",
                    message=msg,
                    command=cmd_str,
                    recipe_id=recipe.recipe_id,
                    source=recipe.source,
                    tier=tier.value,
                    trust=trust_score,
                    risk=risk_score,
                    confidence=confidence_score,
                )
                return ExecutionOutcome(
                    success=False,
                    status="BLOCKED",
                    operation=recipe.operation.value,
                    target=target_name,
                    command=cmd_str,
                    return_code=None,
                    stdout="",
                    stderr=safety_res.message,
                    classification=safety_res.blocked_reason.value if safety_res.blocked_reason else "SAFETY_POLICY_REJECTED",
                    verification={},
                    tier=tier.value,
                    trust=trust_score,
                    risk=risk_score,
                    confidence=confidence_score,
                    message=msg,
                )

            # 4. Command Execution (guarded by permanent safety authorization invariant)
            self._assert_safety_authorized(safety_res)
            start_t = time.time()
            try:
                proc = subprocess.run(
                    cmd_str,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
                rc = proc.returncode
                stdout = proc.stdout
                stderr = proc.stderr
            except subprocess.TimeoutExpired:
                rc = -1
                stdout = ""
                stderr = f"Command timed out after {timeout} seconds."
            except Exception as exc:
                rc = -1
                stdout = ""
                stderr = str(exc)

            # 5. Output Classification
            classified = classify_execution_result(
                command=cmd_str,
                returncode=rc,
                stdout=stdout,
                stderr=stderr,
                package_id=target_name,
                app_name=target_name,
                operation=recipe.operation.value,
            )

            # 6. Tiered Verification
            # Authoritative separation: only run post-repair verification if process exited 0!
            policy = VerificationPolicy.from_env(recipe.operation.value)
            verif_res: Optional[VerificationResult] = None

            if rc == 0:
                # Configurable stabilization/grace period before first verification attempt
                if policy.stabilization_grace > 0:
                    time.sleep(policy.stabilization_grace)

                verif_res = verification_engine.verify_tool(
                    target_name_or_id=target_name,
                    level=verification_level,
                    recipe=recipe,
                    original_problem=original_problem,
                    policy=policy,
                )

            # 7. Final status determination
            if rc != 0:
                final_status = "EXECUTION_FAILED"
                exec_status = "EXECUTION_FAILED"
                verif_status = "NOT_RUN"
                success = False
            elif verif_res and verif_res.status == VerificationStatus.VERIFIED:
                final_status = "VERIFIED"
                exec_status = "EXECUTION_SUCCEEDED"
                verif_status = "VERIFIED"
                success = True
            elif verif_res and verif_res.status == VerificationStatus.VERIFICATION_TIMEOUT:
                final_status = "VERIFICATION_TIMEOUT"
                exec_status = "EXECUTION_SUCCEEDED"
                verif_status = "VERIFICATION_TIMEOUT"
                success = False
            else:
                final_status = "VERIFICATION_FAILED"
                exec_status = "EXECUTION_SUCCEEDED"
                verif_status = "VERIFICATION_FAILED"
                success = False

            explanation = classified.get("explanation", "") if isinstance(classified, dict) else ""
            if final_status == "VERIFICATION_TIMEOUT":
                message = f"{recipe.operation.value} for {target_name} executed, but verification timed out after {verif_res.attempts if verif_res else 3} attempts."
            elif success:
                message = f"{recipe.operation.value} for {target_name} confirmed and verified."
            elif rc != 0:
                message = f"{recipe.operation.value} for {target_name} failed: {explanation or stderr}"
            else:
                message = f"{recipe.operation.value} for {target_name} failed verification: {explanation or (verif_res.message if verif_res else '')}"

            # 8. Post-mutation State Refresh (RESCAN)
            if recipe.operation not in (RecipeOperation.VERSION_CHECK, RecipeOperation.VERIFY):
                state_refresher.refresh_tool_state(target_name)

            # 9. Structured Logging (LOG)
            structured_logger.log_event(
                operation=recipe.operation.value,
                application=target_name,
                identity=target_name,
                status=final_status,
                message=message,
                command=cmd_str,
                recipe_id=recipe.recipe_id,
                source=recipe.source,
                return_code=rc,
                versions={"detected": verif_res.version_detected if verif_res else None},
                verification=verif_res.to_dict() if verif_res else {},
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
            )

            class_val = classified.get("classification", "SUCCESS") if isinstance(classified, dict) else "SUCCESS"
            return ExecutionOutcome(
                success=success,
                status=final_status,
                execution_status=exec_status,
                verification_status=verif_status,
                operation=recipe.operation.value,
                target=target_name,
                command=cmd_str,
                return_code=rc,
                stdout=stdout,
                stderr=stderr,
                classification=class_val,
                verification=verif_res.to_dict() if verif_res else {},
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
                message=message,
                details=classified if isinstance(classified, dict) else {},
            )

        finally:
            # 10. Release fine-grained resource locks
            resource_lock_mgr.release_resources(owner_id, resources)

    async def stream_execute_recipe(
        self,
        recipe: StructuredRecipe,
        verification_level: VerificationLevel = VerificationLevel.FAST,
        trust_score: Optional[float] = None,
        confidence_score: Optional[float] = None,
        original_problem: Optional[str] = None,
        timeout: int = 1800,
        approved: bool = True,
    ) -> AsyncGenerator[str, None]:
        """
        Executes a recipe streaming actual SSE events in real-time.
        Emits genuine output lines and stages; NEVER fabricates progress.
        """
        target_name = recipe.identity_id
        cmd_str = recipe.to_command_string()

        # Stage 0: Plan & Tier Resolution
        req = ExecutionRequest(
            recipe=recipe,
            command=cmd_str,
            target=target_name,
            operation=recipe.operation.value,
            source=recipe.source,
            timeout=timeout,
            original_problem=original_problem,
            approved=approved,
            trust=trust_score,
            confidence=confidence_score,
        )
        m_state = state_refresher.refresh_machine_state(target_identity=target_name)
        plan = execution_resolver.resolve(req, machine_state=m_state)

        if plan.tier == ExecutionTier.BLOCKED:
            err_msg = f"Execution blocked: {plan.tier_reason}"
            yield f"data: {json.dumps({'type': 'error', 'message': err_msg, 'classification': 'RISK_ABOVE_HARD_LIMIT'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'returncode': -1, 'status': 'BLOCKED', 'execution_status': 'EXECUTION_FAILED', 'verification_status': 'NOT_RUN', 'message': err_msg})}\n\n"
            return

        if approved is False or (not plan.is_automatically_authorized and plan.tier.requires_approval and not approved):
            reason = "Execution cancelled: user explicitly declined approval." if approved is False else f"Execution tier '{plan.tier.value}' requires explicit user approval before execution."
            yield f"data: {json.dumps({'type': 'error', 'message': reason, 'classification': 'APPROVAL_REQUIRED'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'returncode': -1, 'status': 'APPROVAL_REQUIRED', 'execution_status': 'NOT_RUN', 'verification_status': 'NOT_RUN', 'classification': 'APPROVAL_REQUIRED', 'message': reason, 'approval_required': True, 'tier': plan.tier.value})}\n\n"
            return

        if plan.is_automatically_authorized:
            yield f"data: {json.dumps({'type': 'stage', 'stage': 'AUTHORIZING', 'message': 'Trusted repair. Executing automatically...', 'auto_authorized': True})}\n\n"

        # Stage 1: Assessment & Live Pre-Execution Gate
        yield f"data: {json.dumps({'type': 'stage', 'stage': 'PREPARING', 'message': f'Preparing {recipe.operation.value} for {target_name}...' })}\n\n"
        await asyncio.sleep(0.01)

        safety_res = authoritative_safety.live_pre_execution_gate(
            command=cmd_str,
            operation=recipe.operation.value,
            is_static_recipe=(recipe.source == "STATIC_DB"),
            recipe=recipe,
            machine_state=m_state,
            package_manager=recipe.package_manager,
            target_resource=target_name,
        )
        if not safety_res.allowed:
            err_msg = f"Safety Gate Rejected: {safety_res.message}"
            yield f"data: {json.dumps({'type': 'error', 'message': err_msg, 'classification': safety_res.blocked_reason.value if safety_res.blocked_reason else 'SAFETY_BLOCKED'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'returncode': -1, 'status': 'BLOCKED', 'message': err_msg})}\n\n"
            return

        # Acquire lock
        owner_id = f"stream_{target_name}_{int(time.time()*1000)}"
        resources = [f"pm:{recipe.package_manager.lower()}", f"tool:{target_name.lower()}"]
        if not resource_lock_mgr.acquire_resources(owner_id, resources, timeout=3.0):
            err_msg = f"Package manager {recipe.package_manager} or {target_name} is currently busy."
            yield f"data: {json.dumps({'type': 'error', 'message': err_msg, 'classification': 'RESOURCE_BUSY'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'returncode': -1, 'status': 'BLOCKED', 'message': err_msg})}\n\n"
            return

        stdout_chunks = []
        stderr_chunks = []

        try:
            self._assert_safety_authorized(safety_res)
            yield f"data: {json.dumps({'type': 'stage', 'stage': 'EXECUTING', 'message': f'Executing: {cmd_str}'})}\n\n"
            await asyncio.sleep(0.01)

            # Spawn real subprocess with async streaming
            proc = await asyncio.create_subprocess_shell(
                cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def read_stream(stream, stream_name):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if stream_name == "stdout":
                        stdout_chunks.append(decoded)
                    else:
                        stderr_chunks.append(decoded)
                    return decoded

            # Read both stdout and stderr
            while proc.returncode is None:
                line_out = ""
                try:
                    if proc.stdout:
                        raw_line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.1)
                        if raw_line:
                            line_out = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                            stdout_chunks.append(line_out)
                            yield f"data: {json.dumps({'type': 'output', 'stream': 'stdout', 'line': line_out})}\n\n"
                except asyncio.TimeoutError:
                    pass

                try:
                    if proc.stderr:
                        raw_err = await asyncio.wait_for(proc.stderr.readline(), timeout=0.05)
                        if raw_err:
                            line_err = raw_err.decode("utf-8", errors="replace").rstrip("\r\n")
                            stderr_chunks.append(line_err)
                            yield f"data: {json.dumps({'type': 'output', 'stream': 'stderr', 'line': line_err})}\n\n"
                except asyncio.TimeoutError:
                    pass

                if proc.returncode is not None:
                    break

            # Finish reading remaining buffers
            remaining_out, remaining_err = await proc.communicate()
            if remaining_out:
                for line in remaining_out.decode("utf-8", errors="replace").splitlines():
                    stdout_chunks.append(line)
                    yield f"data: {json.dumps({'type': 'output', 'stream': 'stdout', 'line': line})}\n\n"
            if remaining_err:
                for line in remaining_err.decode("utf-8", errors="replace").splitlines():
                    stderr_chunks.append(line)
                    yield f"data: {json.dumps({'type': 'output', 'stream': 'stderr', 'line': line})}\n\n"

            rc = proc.returncode or 0
            full_stdout = "\n".join(stdout_chunks)
            full_stderr = "\n".join(stderr_chunks)

            # Stage 3: Output Classification
            yield f"data: {json.dumps({'type': 'stage', 'stage': 'CLASSIFYING', 'message': 'Classifying execution results...'})}\n\n"
            classified = classify_execution_result(
                command=cmd_str,
                returncode=rc,
                stdout=full_stdout,
                stderr=full_stderr,
                package_id=target_name,
                app_name=target_name,
                operation=recipe.operation.value,
            )

            # Stage 4: Verification (Only if execution succeeded!)
            policy = VerificationPolicy.from_env(recipe.operation.value)
            verif_res: Optional[VerificationResult] = None

            if rc == 0:
                if policy.stabilization_grace > 0:
                    yield f"data: {json.dumps({'type': 'stage', 'stage': 'STABILIZING', 'message': f'Waiting for toolchain to stabilize ({policy.stabilization_grace}s)...'})}\n\n"
                    await asyncio.sleep(policy.stabilization_grace)

                yield f"data: {json.dumps({'type': 'stage', 'stage': 'VERIFYING', 'message': f'Running {verification_level.value} functional verification...'})}\n\n"

                attempt_logs: List[str] = []

                def on_stream_attempt(att: int, ev_type: str, delay: Optional[float]):
                    if ev_type == "VERIFICATION_TIMEOUT" and delay is not None:
                        attempt_logs.append(f"[Verification Timeout] Attempt {att} timed out. Retrying in {delay:.1f}s...")
                    elif ev_type == "VERIFICATION_TIMEOUT" and delay is None:
                        attempt_logs.append(f"[Verification Timeout] Terminal timeout reached after {att} attempts.")
                    elif ev_type == "VERIFICATION_SUCCEEDED":
                        attempt_logs.append(f"[Verification Succeeded] Tool verified operational on attempt {att}.")

                verif_res = verification_engine.verify_tool(
                    target_name_or_id=target_name,
                    level=verification_level,
                    recipe=recipe,
                    original_problem=original_problem,
                    policy=policy,
                    on_attempt=on_stream_attempt,
                )

                for l in attempt_logs:
                    yield f"data: {json.dumps({'type': 'log', 'stream': 'stdout', 'line': l})}\n\n"

            if rc != 0:
                final_status = "EXECUTION_FAILED"
                exec_status = "EXECUTION_FAILED"
                verif_status = "NOT_RUN"
                success = False
            elif verif_res and verif_res.status == VerificationStatus.VERIFIED:
                final_status = "VERIFIED"
                exec_status = "EXECUTION_SUCCEEDED"
                verif_status = "VERIFIED"
                success = True
            elif verif_res and verif_res.status == VerificationStatus.VERIFICATION_TIMEOUT:
                final_status = "VERIFICATION_TIMEOUT"
                exec_status = "EXECUTION_SUCCEEDED"
                verif_status = "VERIFICATION_TIMEOUT"
                success = False
            else:
                final_status = "VERIFICATION_FAILED"
                exec_status = "EXECUTION_SUCCEEDED"
                verif_status = "VERIFICATION_FAILED"
                success = False

            explanation = classified.get("explanation", "") if isinstance(classified, dict) else ""
            if final_status == "VERIFICATION_TIMEOUT":
                msg = f"{recipe.operation.value} for {target_name} executed, but verification timed out after {verif_res.attempts if verif_res else 3} attempts."
            elif success:
                msg = f"{recipe.operation.value} for {target_name} confirmed and verified."
            elif rc != 0:
                msg = f"{recipe.operation.value} for {target_name} failed: {explanation or full_stderr}"
            else:
                msg = f"{recipe.operation.value} for {target_name} failed verification: {explanation or (verif_res.message if verif_res else '')}"

            # Structured logging
            structured_logger.log_event(
                operation=recipe.operation.value,
                application=target_name,
                identity=target_name,
                status=final_status,
                message=msg,
                command=cmd_str,
                recipe_id=recipe.recipe_id,
                source=recipe.source,
                return_code=rc,
                versions={"detected": verif_res.version_detected if verif_res else None},
                verification=verif_res.to_dict() if verif_res else {},
                trust=plan.trust_score,
                confidence=plan.confidence_score,
            )

            # State refresh
            if recipe.operation not in (RecipeOperation.VERSION_CHECK, RecipeOperation.VERIFY):
                state_refresher.refresh_tool_state(target_name)

            done_payload = {
                "type": "done",
                "returncode": rc,
                "success": success,
                "status": final_status,
                "execution_status": exec_status,
                "verification_status": verif_status,
                "classification": classified.get("classification", "SUCCESS") if isinstance(classified, dict) else "SUCCESS",
                "is_publisher_managed": classified.get("is_publisher_managed", False) if isinstance(classified, dict) else False,
                "official_url": classified.get("official_url", "") if isinstance(classified, dict) else "",
                "publisher_update_command": classified.get("publisher_update_command", "") if isinstance(classified, dict) else "",
                "publisher_update_instructions": classified.get("publisher_update_instructions", "") if isinstance(classified, dict) else "",
                "verification": verif_res.to_dict() if verif_res else {},
                "explanation": explanation,
                "message": msg,
                "executed_but_unverified": (rc == 0 and final_status == "VERIFICATION_TIMEOUT"),
            }
            yield f"data: {json.dumps(done_payload)}\n\n"

        finally:
            resource_lock_mgr.release_resources(owner_id, resources)

    def _infer_target(self, command: str, title: Optional[str] = None) -> str:
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

    def _detect_pm(self, command: str) -> str:
        c_low = command.lower()
        for pm in ["winget", "choco", "scoop", "apt-get", "apt", "dnf", "pacman", "brew", "flatpak", "snap", "pip", "npm", "cargo"]:
            if pm in c_low:
                return pm
        return "system"

    def execute_command(
        self,
        command: str,
        target: Optional[str] = None,
        operation: str = "REPAIR",
        elevate: bool = False,
        scope: Optional[str] = None,
        title: Optional[str] = None,
        source: str = "UNRESOLVED",
        timeout: int = 120,
        original_problem: Optional[str] = None,
        trigger_shce: bool = True,
        target_name: Optional[str] = None,
        pm: Optional[str] = None,
        tier: Optional[Any] = None,
        owner_id: Optional[str] = None,
        approved: Optional[bool] = None,
        **kwargs: Any,
    ) -> ExecutionOutcome:
        """
        The single authoritative entrypoint for executing any command or mutation.
        Enforces canonical resolution, risk/tier assessment, resource locking, live pre-execution
        safety gate, elevation, process execution, result classification, authoritative verification,
        and structured telemetry logging.
        """
        clean_cmd = (command or "").strip()
        target_name = target or target_name or self._infer_target(clean_cmd, title)

        # 1. Empty, comment, natural language, or destructive syntax check
        from authoritative_safety import is_natural_language_command, HARD_BLACKLIST
        import re
        is_blacklisted = any(re.search(p, clean_cmd, re.IGNORECASE) for p in HARD_BLACKLIST)
        if not clean_cmd or clean_cmd.startswith("#") or is_natural_language_command(clean_cmd) or is_blacklisted:
            reason = "Cannot execute empty command or comment."
            if is_blacklisted:
                reason = "Command matches blacklisted destructive pattern."
            elif is_natural_language_command(clean_cmd):
                reason = "Natural language recommendation cannot be executed as a command."

            structured_logger.log_event(
                operation=operation,
                application=target_name,
                identity=target_name,
                status="BLOCKED",
                message=reason,
                command=clean_cmd,
                source=source,
            )
            return ExecutionOutcome(
                success=False,
                status="BLOCKED",
                execution_status="EXECUTION_FAILED",
                verification_status="NOT_RUN",
                operation=operation,
                target=target_name,
                command=clean_cmd,
                return_code=1,
                stdout="",
                stderr=reason,
                classification="SAFETY_POLICY_REJECTED",
                verification={},
                tier="BLOCKED",
                trust=0.0,
                risk=100.0,
                confidence=0.0,
                message=reason,
            )

        # 2. Phase 0.1 Invariant: Approval gate fires BEFORE any subprocess / state refresh.
        #    Use a lightweight default MachineState for initial plan resolution so that
        #    no subprocess is spawned until the approval check has passed.
        from machine_state import MachineState as _MachineState
        _sentinel_state = _MachineState(free_disk_gb=50.0)  # conservative defaults, no subprocess calls
        req = ExecutionRequest(
            command=clean_cmd,
            target=target or target_name,
            operation=operation,
            source=source,
            elevate=elevate,
            scope=scope,
            title=title,
            timeout=timeout,
            original_problem=original_problem,
            trigger_shce=trigger_shce,
            pm=pm,
            tier=tier,
            owner_id=owner_id,
            approved=approved,
        )
        plan = execution_resolver.resolve(req, machine_state=_sentinel_state)

        recipe = plan.recipe
        tier = plan.tier
        tier_reason = plan.tier_reason
        risk_score = plan.risk_score
        trust_score = plan.trust_score
        confidence_score = plan.confidence_score
        pm = plan.pm
        target_name = plan.target_name

        if tier == ExecutionTier.BLOCKED:
            return ExecutionOutcome(
                success=False,
                status="BLOCKED",
                execution_status="EXECUTION_FAILED",
                verification_status="NOT_RUN",
                operation=operation,
                target=target_name,
                command=clean_cmd,
                return_code=None,
                stdout="",
                stderr=tier_reason,
                classification="RISK_ABOVE_HARD_LIMIT",
                verification={},
                tier=tier.value,
                trust=0.0,
                risk=risk_score,
                confidence=0.0,
                message=tier_reason,
            )

        # 3. Centralized Approval Enforcement (Section 6)
        #    Fires BEFORE any subprocess — satisfies Phase 0.1 invariant.
        #    NOTE: is_elevation_prompted reflects caller-initiated elevation intent ONLY
        #    (elevate=True or scope='machine'). We do NOT use tier == TIER_3_ELEVATED_ADMIN
        #    because TIER_3_ELEVATED_ADMIN is an alias for TIER_3_FULL_PROTECTED (same value),
        #    which would bypass the approval gate for ALL TIER_3 commands.
        is_elevation_prompted = bool(elevate or scope == "machine")
        if approved is False or (not plan.is_automatically_authorized and tier.requires_approval and (not approved and not is_elevation_prompted)):
            reason = "Execution cancelled: user explicitly declined approval." if approved is False else f"Execution tier '{tier.value}' requires explicit user approval before execution."
            structured_logger.log_event(
                operation=operation,
                application=target_name,
                identity=target_name,
                status="APPROVAL_REQUIRED",
                message=reason,
                command=clean_cmd,
                source=plan.source,
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
            )
            return ExecutionOutcome(
                success=False,
                status="APPROVAL_REQUIRED",
                execution_status="NOT_RUN",
                verification_status="NOT_RUN",
                operation=operation,
                target=target_name,
                command=clean_cmd,
                return_code=None,
                stdout="",
                stderr=reason,
                classification="APPROVAL_REQUIRED",
                verification={},
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
                message=reason,
                details={"requires_approval": True, "tier": tier.value, "approval_required": True},
            )

        # 4. Deferred full machine state refresh — only runs after approval is confirmed.
        #    Phase 0.1 invariant: no subprocess spawned before approval gate.
        #    The tier from the sentinel resolve is used for execution; the real machine_state
        #    is passed to the safety gate for disk/lock/reboot live checks.
        machine_state = state_refresher.refresh_machine_state(target_identity=target_name)

        # 4b. Privilege Resolution
        from privilege_manager import privilege_manager
        privilege_manager.resolve_privilege(tier=tier, elevate=elevate, scope=scope)

        # 5. Live Pre-Execution Safety Gate
        safety_res = authoritative_safety.live_pre_execution_gate(
            command=clean_cmd,
            operation=operation,
            is_static_recipe=(plan.provenance_class == ProvenanceClass.STATIC_RECIPE),
            recipe=recipe,
            machine_state=machine_state,
            package_manager=pm,
            target_resource=target_name,
            owner_id=owner_id,
        )
        if not safety_res.allowed:
            blocked_class = safety_res.blocked_reason.value if safety_res.blocked_reason else "SAFETY_POLICY_REJECTED"
            if safety_res.blocked_reason == BlockedReason.RESOURCE_LOCKED:
                blocked_class = "RESOURCE_BUSY"
            structured_logger.log_event(
                operation=operation,
                application=target_name,
                identity=target_name,
                status="BLOCKED",
                message=f"Safety Gate Blocked: {safety_res.message}",
                command=clean_cmd,
                source=source,
            )
            return ExecutionOutcome(
                success=False,
                status="BLOCKED",
                execution_status="EXECUTION_FAILED",
                verification_status="NOT_RUN",
                operation=operation,
                target=target_name,
                command=clean_cmd,
                return_code=None,
                stdout="",
                stderr=safety_res.message,
                classification=blocked_class,
                verification={},
                tier="BLOCKED",
                trust=0.0,
                risk=100.0,
                confidence=0.0,
                message=safety_res.message,
                details={"blocked_reason": blocked_class},
            )

        # 6. Resource lock
        owner_id = owner_id or f"exec_{target_name}_{int(time.time()*1000)}"
        resources = [f"pm:{pm.lower()}", f"tool:{target_name.lower()}"]
        lock_acquired = resource_lock_mgr.acquire_resources(owner_id, resources, timeout=3.0)
        if not lock_acquired:
            msg = f"Resource lock conflict: tool '{target_name}' or package manager '{pm}' is currently busy with another operation."
            structured_logger.log_event(
                operation=operation,
                application=target_name,
                identity=target_name,
                status="BLOCKED",
                message=msg,
                command=clean_cmd,
                source=source,
            )
            return ExecutionOutcome(
                success=False,
                status="BLOCKED",
                execution_status="NOT_RUN",
                verification_status="NOT_RUN",
                operation=operation,
                target=target_name,
                command=clean_cmd,
                return_code=None,
                stdout="",
                stderr=msg,
                classification="RESOURCE_BUSY",
                verification={},
                tier=tier.value,
                trust=0.9,
                risk=risk_score,
                confidence=1.0,
                message=msg,
                details={"blocked_reason": "RESOURCE_BUSY", "locked_resources": resources},
            )

        out = ""
        err = ""
        rc = 0
        is_proc_timeout = False

        try:
            # 6. Execution (guarded by permanent safety authorization invariant)
            self._assert_safety_authorized(safety_res)
            from privilege_manager import privilege_manager
            from feature_flags import ENABLE_DEV_MODE

            if elevate or scope == "machine":
                out, err, rc = privilege_manager.run_with_elevation(clean_cmd, title=title or target_name)
                if privilege_manager.is_cancelled_by_user(rc, err) or rc == 1223 or "permission was not granted" in (err or "").lower():
                    cancel_rc = rc if rc != 0 else 1223
                    structured_logger.log_event(
                        operation=operation,
                        application=target_name,
                        identity=target_name,
                        status="USER_DECLINED_ELEVATION",
                        message="Administrator permission was declined by user. System state was not changed.",
                        command=clean_cmd,
                        return_code=cancel_rc,
                    )
                    return ExecutionOutcome(
                        success=False,
                        status="USER_DECLINED_ELEVATION",
                        execution_status="USER_DECLINED_ELEVATION",
                        verification_status="NOT_RUN",
                        operation=operation,
                        target=target_name,
                        command=clean_cmd,
                        return_code=cancel_rc,
                        stdout=out,
                        stderr=err or "Administrator permission was not granted.",
                        classification="USER_DECLINED_ELEVATION",
                        verification={},
                        tier=tier.value,
                        trust=trust_score,
                        risk=risk_score,
                        confidence=confidence_score,
                        message="Administrator permission was not granted. System state was not changed.",
                        details={"requires_elevation": True, "code": "ELEVATION_CANCELLED"},
                    )
            else:
                if ENABLE_DEV_MODE and any(token in clean_cmd.lower() for token in ("sudo", "install", "upgrade", "systemctl")):
                    out = f"Mock execution successful in Dev Mode for: {clean_cmd}"
                    err = ""
                    rc = 0
                else:
                    is_proc_timeout = False
                    try:
                        proc = subprocess.run(
                            clean_cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=timeout,
                        )
                        out = proc.stdout
                        err = proc.stderr
                        rc = proc.returncode
                    except subprocess.TimeoutExpired:
                        out = ""
                        err = f"Command timed out after {timeout} seconds."
                        rc = 124
                        is_proc_timeout = True
                    except Exception as exc:
                        out = ""
                        err = str(exc)
                        rc = -1

            # 7. Output Classification
            classified = classify_execution_result(
                command=clean_cmd,
                returncode=rc,
                stdout=out,
                stderr=err,
                package_id=target_name,
                app_name=title or target_name,
                operation=operation,
            )

            # 8. Tiered Verification
            policy = VerificationPolicy.from_env(operation)
            verif_res: Optional[VerificationResult] = None
            post_verify: Optional[Dict[str, Any]] = None

            if rc == 0:
                if policy.stabilization_grace > 0:
                    time.sleep(policy.stabilization_grace)

                is_verifiable_target = (
                    recipe is not None
                    or canonical_store.resolve(target_name) is not None
                    or source in ("STATIC_DB", "SYSTEM", "REPAIR")
                    or (operation and operation.upper() == "UNINSTALL")
                    or bool(shutil.which(target_name))
                )

                if is_verifiable_target:
                    verif_res = verification_engine.verify_tool(
                        target_name_or_id=target_name,
                        level=VerificationLevel.CONTROLLED,
                        recipe=recipe,
                        original_problem=original_problem,
                        policy=policy,
                        operation=operation,
                    )

                try:
                    from dev_environment_detector import dev_environment_detector
                    post_verify = dev_environment_detector.post_repair_verify(clean_cmd, title=title)
                except Exception:
                    pass

            # 9. Final Status Determination
            if rc != 0:
                final_status = "EXECUTION_FAILED"
                exec_status = "EXECUTION_FAILED"
                verif_status = "NOT_RUN"
                success = False
                if trigger_shce and err:
                    try:
                        from shce_engine import shce as _shce
                        _shce.handle_failure(command=clean_cmd, error=err, source="execution_engine", auto_queue=True)
                    except Exception:
                        pass
            else:
                is_generic_fallback = (
                    bool(post_verify) and
                    not post_verify.get("details") and
                    (
                        post_verify.get("message", "").startswith("Command execution completed")
                        or post_verify.get("message", "").startswith("Command completed")
                    )
                )
                has_domain_verification = bool(post_verify and post_verify.get("verified") and not is_generic_fallback)

                if (verif_res and verif_res.status == VerificationStatus.VERIFICATION_TIMEOUT) or (not verif_res and post_verify and (post_verify.get("status") == "VERIFICATION_TIMEOUT" or post_verify.get("timed_out"))):
                    final_status = "VERIFICATION_TIMEOUT"
                    exec_status = "EXECUTION_SUCCEEDED"
                    verif_status = "VERIFICATION_TIMEOUT"
                    success = False
                elif (verif_res and verif_res.status == VerificationStatus.VERIFIED) or (verif_res is None and post_verify and post_verify.get("verified")) or has_domain_verification:
                    final_status = "VERIFIED"
                    exec_status = "EXECUTION_SUCCEEDED"
                    verif_status = "VERIFIED"
                    success = True
                else:
                    final_status = "VERIFICATION_FAILED"
                    exec_status = "EXECUTION_SUCCEEDED"
                    verif_status = "VERIFICATION_FAILED"
                    success = False

            explanation = classified.get("explanation", "") if isinstance(classified, dict) else ""
            if is_proc_timeout or rc == 124:
                final_classification = "EXECUTION_TIMEOUT"
                final_status = "EXECUTION_FAILED"
                msg = f"{operation} for {target_name} timed out after {timeout} seconds."
            elif final_status == "VERIFICATION_TIMEOUT":
                final_classification = "VERIFICATION_TIMEOUT"
                msg = f"{operation} for {target_name} executed, but verification timed out after {verif_res.attempts if verif_res else policy.max_attempts} attempts."
            elif final_status == "VERIFICATION_FAILED":
                final_classification = "VERIFICATION_FAILED"
                msg = f"{operation} for {target_name} executed, but functional verification failed."
            elif success:
                final_classification = classified.get("classification", "SUCCESS") if isinstance(classified, dict) else "SUCCESS"
                msg = f"{operation} for {target_name} confirmed and verified."
            elif rc != 0:
                final_classification = classified.get("classification", "COMMAND_EXECUTION_FAILED") if isinstance(classified, dict) else "COMMAND_EXECUTION_FAILED"
                msg = f"{operation} for {target_name} failed: {explanation or err}"
            else:
                final_classification = "VERIFICATION_FAILED"
                msg = f"{operation} for {target_name} executed, but functional verification failed."

            # 10. State Refresh (RESCAN)
            state_refresher.refresh_tool_state(target_name)

            # 11. Structured Telemetry Logging (LOG)
            verif_dict = verif_res.to_dict() if verif_res else (post_verify or {})
            structured_logger.log_event(
                operation=operation,
                application=target_name,
                identity=target_name,
                status=final_status,
                message=msg,
                command=clean_cmd,
                recipe_id=recipe.recipe_id if recipe else None,
                source=source,
                return_code=rc,
                versions={"detected": verif_res.version_detected if verif_res else (post_verify.get("details", {}).get("version") if post_verify else None)},
                verification=verif_dict,
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
            )

            return ExecutionOutcome(
                success=success,
                status=final_status,
                execution_status=exec_status,
                verification_status=verif_status,
                operation=operation,
                target=target_name,
                command=clean_cmd,
                return_code=rc,
                stdout=out,
                stderr=err,
                classification=final_classification,
                verification=verif_dict,
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
                message=msg,
                details={
                    "classification": classified if isinstance(classified, dict) else {},
                    "post_verification": post_verify or {},
                    "executed_but_unverified": (rc == 0 and final_status == "VERIFICATION_TIMEOUT"),
                },
            )

        finally:
            if lock_acquired:
                resource_lock_mgr.release_resources(owner_id, resources)

    execute_command_pipeline = execute_command

    def stream_execute_command(
        self,
        command: str,
        target: Optional[str] = None,
        operation: str = "REPAIR",
        elevate: bool = False,
        scope: Optional[str] = None,
        title: Optional[str] = None,
        source: str = "UNRESOLVED",
        timeout: int = 1800,
        original_problem: Optional[str] = None,
        trigger_shce: bool = True,
        target_name: Optional[str] = None,
        pm: Optional[str] = None,
        tier: Optional[Any] = None,
        owner_id: Optional[str] = None,
        approved: Optional[bool] = None,
        **kwargs: Any,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Executes a command and yields real-time event dictionaries:
        yield {"type": "log", "text": line, "stream": "stdout"|"stderr"}
        yield {"type": "progress", "percent": int, "detail": str}
        yield {"type": "done", "returncode": int, "stdout": str, "stderr": str, "ok": bool, "status": str, ...}
        """
        clean_cmd = (command or "").strip()
        target_name = target or target_name or self._infer_target(clean_cmd, title)

        yield {"type": "start", "command": clean_cmd, "title": title or target_name}
        yield {"type": "stage", "stage": "PREPARING", "message": f"Preparing {operation} for {target_name}..."}

        # 1. Empty, comment, natural language, or destructive syntax check
        from authoritative_safety import is_natural_language_command, HARD_BLACKLIST
        import re
        is_blacklisted = any(re.search(p, clean_cmd, re.IGNORECASE) for p in HARD_BLACKLIST)
        if not clean_cmd or clean_cmd.startswith("#") or is_natural_language_command(clean_cmd) or is_blacklisted:
            reason = "Cannot execute empty command or comment."
            if is_blacklisted:
                reason = "Command matches blacklisted destructive pattern."
            elif is_natural_language_command(clean_cmd):
                reason = "Natural language recommendation cannot be executed as a command."

            structured_logger.log_event(
                operation=operation,
                application=target_name,
                identity=target_name,
                status="BLOCKED",
                message=reason,
                command=clean_cmd,
                source=source,
            )
            yield {"type": "log", "text": f"[Safety Policy Blocked]: {reason}", "stream": "stderr"}
            yield {
                "type": "done",
                "returncode": -1,
                "stdout": "",
                "stderr": reason,
                "ok": False,
                "status": "BLOCKED",
                "classification": "SAFETY_POLICY_REJECTED",
                "message": reason,
            }
            return

        # 2. Phase 0.1 Invariant: Approval gate fires BEFORE any subprocess / state refresh.
        #    Use a lightweight default MachineState for initial plan resolution.
        from machine_state import MachineState as _MachineState
        _sentinel_state = _MachineState(free_disk_gb=50.0)  # conservative defaults, no subprocess calls
        req = ExecutionRequest(
            command=clean_cmd,
            target=target or target_name,
            operation=operation,
            source=source,
            elevate=elevate,
            scope=scope,
            title=title,
            timeout=timeout,
            original_problem=original_problem,
            trigger_shce=trigger_shce,
            pm=pm,
            tier=tier,
            owner_id=owner_id,
            approved=approved,
        )
        plan = execution_resolver.resolve(req, machine_state=_sentinel_state)

        recipe = plan.recipe
        tier = plan.tier
        tier_reason = plan.tier_reason
        risk_score = plan.risk_score
        trust_score = plan.trust_score
        confidence_score = plan.confidence_score
        pm = plan.pm
        target_name = plan.target_name

        if tier == ExecutionTier.BLOCKED:
            yield {"type": "log", "text": f"[Tier Selection Blocked]: {tier_reason}", "stream": "stderr"}
            yield {
                "type": "done",
                "returncode": -1,
                "stdout": "",
                "stderr": tier_reason,
                "ok": False,
                "status": "BLOCKED",
                "classification": "RISK_ABOVE_HARD_LIMIT",
                "message": tier_reason,
            }
            return

        # 3. Centralized Approval Enforcement (Section 6)
        #    is_elevation_prompted: caller-initiated elevation only (elevate=True or scope='machine').
        is_elevation_prompted = bool(elevate or scope == "machine")
        if approved is False or (not plan.is_automatically_authorized and tier.requires_approval and (not approved and not is_elevation_prompted)):
            reason = "Execution cancelled: user explicitly declined approval." if approved is False else f"Execution tier '{tier.value}' requires explicit user approval before execution."
            yield {"type": "log", "text": f"[Approval Required]: {reason}", "stream": "stderr"}
            yield {
                "type": "done",
                "returncode": -1,
                "stdout": "",
                "stderr": reason,
                "ok": False,
                "status": "APPROVAL_REQUIRED",
                "execution_status": "NOT_RUN",
                "verification_status": "NOT_RUN",
                "classification": "APPROVAL_REQUIRED",
                "message": reason,
                "approval_required": True,
                "tier": tier.value,
            }
            return

        if plan.is_automatically_authorized:
            yield {
                "type": "stage",
                "stage": "AUTHORIZING",
                "message": plan.authorization_reason or "Trusted repair. Executing automatically...",
                "tier": tier.value,
                "trust": trust_score,
                "risk": risk_score,
                "auto_authorized": True,
            }

        # 4. Deferred full machine state refresh — only runs after approval is confirmed.
        #    Phase 0.1 invariant: no subprocess spawned before approval gate.
        machine_state = state_refresher.refresh_machine_state(target_identity=target_name)

        # 4b. Privilege Resolution
        from privilege_manager import privilege_manager
        privilege_manager.resolve_privilege(tier=tier, elevate=elevate, scope=scope)

        # 5. Live Pre-Execution Safety Gate
        safety_res = authoritative_safety.live_pre_execution_gate(
            command=clean_cmd,
            operation=operation,
            is_static_recipe=(plan.provenance_class == ProvenanceClass.STATIC_RECIPE),
            recipe=recipe,
            machine_state=machine_state,
            package_manager=pm,
            target_resource=target_name,
            owner_id=owner_id,
        )
        if not safety_res.allowed:
            blocked_class = safety_res.blocked_reason.value if safety_res.blocked_reason else "SAFETY_POLICY_REJECTED"
            if safety_res.blocked_reason == BlockedReason.RESOURCE_LOCKED:
                blocked_class = "RESOURCE_BUSY"
            structured_logger.log_event(
                operation=operation,
                application=target_name,
                identity=target_name,
                status="BLOCKED",
                message=f"Safety Gate Blocked: {safety_res.message}",
                command=clean_cmd,
                source=source,
            )
            yield {"type": "log", "text": f"[Safety Gate Blocked]: {safety_res.message}", "stream": "stderr"}
            yield {
                "type": "done",
                "returncode": -1,
                "stdout": "",
                "stderr": safety_res.message,
                "ok": False,
                "status": "BLOCKED",
                "classification": blocked_class,
                "message": safety_res.message,
            }
            return

        yield {"type": "progress", "percent": 20, "state": "SAFETY_CHECKED", "detail": "Live safety gate passed"}

        # 6. Resource lock
        owner_id = owner_id or f"stream_{target_name}_{int(time.time()*1000)}"
        resources = [f"pm:{pm.lower()}", f"tool:{target_name.lower()}"]
        lock_acquired = resource_lock_mgr.acquire_resources(owner_id, resources, timeout=3.0)
        if not lock_acquired:
            msg = f"Resource lock conflict: tool '{target_name}' or package manager '{pm}' is currently busy with another operation."
            structured_logger.log_event(
                operation=operation,
                application=target_name,
                identity=target_name,
                status="BLOCKED",
                message=msg,
                command=clean_cmd,
                source=source,
            )
            yield {"type": "log", "text": f"[Resource Busy]: {msg}", "stream": "stderr"}
            yield {
                "type": "done",
                "returncode": -1,
                "stdout": "",
                "stderr": msg,
                "ok": False,
                "status": "BLOCKED",
                "classification": "RESOURCE_BUSY",
                "message": msg,
            }
            return

        full_stdout = ""
        full_stderr = ""
        rc = 0

        try:
            self._assert_safety_authorized(safety_res)
            yield {"type": "stage", "stage": "EXECUTING", "message": f"Executing: {clean_cmd}"}
            from privilege_manager import privilege_manager
            from feature_flags import ENABLE_DEV_MODE

            if elevate or scope == "machine":
                yield {"type": "progress", "percent": 30, "state": "ELEVATION_REQUESTED", "detail": "Awaiting Administrator approval"}
                yield {"type": "log", "text": "Requesting administrator elevation...", "stream": "stdout"}

                elev_res = None
                target_dir = ""
                if "path" in clean_cmd.lower() or "environment" in clean_cmd.lower():
                    import re as _re
                    m = _re.search(r'([A-Za-z]:\\[^;"\']+)', clean_cmd)
                    if m:
                        target_dir = m.group(1)

                payload = {
                    "operation": "REPAIR_PATH" if target_dir else "EXECUTE_COMMAND",
                    "scope": scope or "USER",
                    "directory": target_dir,
                    "command": clean_cmd,
                    "application": title or target_name,
                    "source": source,
                }

                for ev in privilege_manager.stream_elevated_operation(payload, timeout=timeout):
                    if ev.get("type") in ("progress", "log"):
                        yield ev
                    elif ev.get("type") == "done":
                        elev_res = ev

                if not elev_res:
                    elev_res = {"ok": True, "status": "EXECUTED", "exit_code": 0, "message": "Elevated operation completed"}

                is_cancelled = (
                    elev_res.get("status") == "USER_DECLINED_ELEVATION"
                    or elev_res.get("code") == "ELEVATION_CANCELLED"
                    or elev_res.get("returncode") == 1223
                    or elev_res.get("exit_code") == 1223
                    or privilege_manager.is_cancelled_by_user(
                        elev_res.get("returncode", elev_res.get("exit_code", 0)),
                        elev_res.get("stderr", ""),
                        elev_res.get("status", "")
                    )
                )
                if is_cancelled:
                    cancel_rc = elev_res.get("returncode") or elev_res.get("exit_code") or 1223
                    cancel_msg = elev_res.get("message") or "Administrator permission was not granted."
                    structured_logger.log_event(
                        operation=operation,
                        application=target_name,
                        identity=target_name,
                        status="USER_DECLINED_ELEVATION",
                        message="Administrator permission was declined by user. System state was not changed.",
                        command=clean_cmd,
                        return_code=cancel_rc,
                    )
                    yield {
                        "type": "done",
                        "returncode": cancel_rc,
                        "stdout": "",
                        "stderr": cancel_msg,
                        "ok": False,
                        "status": "USER_DECLINED_ELEVATION",
                        "code": "ELEVATION_CANCELLED",
                        "classification": "USER_DECLINED_ELEVATION",
                        "requires_elevation": True,
                        "message": cancel_msg,
                    }
                    return

                rc = elev_res.get("exit_code", elev_res.get("returncode", 0))
                full_stdout = elev_res.get("stdout", "")
                full_stderr = elev_res.get("stderr", "")

            else:
                if ENABLE_DEV_MODE and any(token in clean_cmd.lower() for token in ("sudo", "install", "upgrade", "systemctl")):
                    full_stdout = f"Mock execution successful in Dev Mode for: {clean_cmd}"
                    full_stderr = ""
                    rc = 0
                    yield {"type": "log", "text": full_stdout, "stream": "stdout"}
                    yield {"type": "progress", "percent": 90, "detail": "Execution finished"}
                else:
                    import queue
                    import threading

                    line_queue = queue.Queue()
                    is_windows = platform.system() == "Windows"
                    current_os = platform.system()

                    wrapped_cmd = clean_cmd
                    if current_os == "Linux" and clean_cmd.startswith("sudo "):
                        wrapped_cmd = f"pkexec {clean_cmd[5:]}"
                    elif is_windows and clean_cmd.startswith("sudo "):
                        wrapped_cmd = f"powershell -Command \"Start-Process cmd -ArgumentList '/c {clean_cmd[5:]}' -Verb RunAs -Wait\""

                    proc = subprocess.Popen(
                        wrapped_cmd,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                    )

                    def read_pipe(pipe, stream_name):
                        for raw_line in iter(pipe.readline, ""):
                            line = raw_line.rstrip("\r\n")
                            if line:
                                line_queue.put((stream_name, line))
                        pipe.close()

                    t_out = threading.Thread(target=read_pipe, args=(proc.stdout, "stdout"), daemon=True)
                    t_err = threading.Thread(target=read_pipe, args=(proc.stderr, "stderr"), daemon=True)
                    t_out.start()
                    t_err.start()

                    start_time = time.time()
                    stdout_lines = []
                    stderr_lines = []

                    while True:
                        try:
                            stream_name, line = line_queue.get(timeout=0.1)
                            if stream_name == "stdout":
                                stdout_lines.append(line)
                            else:
                                stderr_lines.append(line)
                            yield {"type": "log", "text": line, "stream": stream_name}
                        except queue.Empty:
                            if proc.poll() is not None and not t_out.is_alive() and not t_err.is_alive() and line_queue.empty():
                                break

                        if time.time() - start_time > timeout:
                            try:
                                proc.kill()
                                proc.wait(timeout=2.0)
                            except Exception:
                                pass
                            rc = 124
                            line_queue.put(("stderr", f"[Timeout]: Process terminated after {timeout} seconds."))
                            break

                    if rc != 124:
                        rc = proc.returncode if proc.returncode is not None else -1
                    full_stdout = "\n".join(stdout_lines)
                    full_stderr = "\n".join(stderr_lines)

            # 7. Output Classification
            yield {"type": "stage", "stage": "CLASSIFYING", "message": "Classifying execution results..."}
            classified = classify_execution_result(
                command=clean_cmd,
                returncode=rc,
                stdout=full_stdout,
                stderr=full_stderr,
                package_id=target_name,
                app_name=title or target_name,
                operation=operation,
            )

            # 8. Tiered Verification
            policy = VerificationPolicy.from_env(operation)
            verif_res: Optional[VerificationResult] = None
            post_verify: Optional[Dict[str, Any]] = None

            if rc == 0:
                if policy.stabilization_grace > 0:
                    yield {"type": "stage", "stage": "STABILIZING", "message": f"Waiting for environment to stabilize ({policy.stabilization_grace}s)..."}
                    time.sleep(policy.stabilization_grace)

                yield {"type": "stage", "stage": "VERIFYING", "message": f"Running verification for {target_name}..."}

                def on_attempt(att: int, ev_type: str, delay: Optional[float]):
                    if ev_type == "VERIFICATION_TIMEOUT" and delay is not None:
                        line = f"[Verification Timeout] Attempt {att} timed out. Retrying verification in {delay:.1f}s..."
                        line_queue = None
                    elif ev_type == "VERIFICATION_TIMEOUT" and delay is None:
                        line = f"[Verification Timeout] Verification timed out after {att} attempts."
                    elif ev_type == "VERIFICATION_SUCCEEDED":
                        line = f"[Verification Succeeded] Operational status verified on attempt {att}."

                is_verifiable_target = (
                    recipe is not None
                    or canonical_store.resolve(target_name) is not None
                    or source in ("STATIC_DB", "SYSTEM", "REPAIR")
                    or (operation and operation.upper() == "UNINSTALL")
                    or bool(shutil.which(target_name))
                )

                if is_verifiable_target:
                    verif_res = verification_engine.verify_tool(
                        target_name_or_id=target_name,
                        level=VerificationLevel.CONTROLLED,
                        recipe=recipe,
                        original_problem=original_problem,
                        policy=policy,
                        on_attempt=on_attempt,
                        operation=operation,
                    )

                try:
                    from dev_environment_detector import dev_environment_detector
                    post_verify = dev_environment_detector.post_repair_verify(clean_cmd, title=title)
                except Exception:
                    pass

            # 9. Final Status Determination
            if rc != 0:
                final_status = "EXECUTION_FAILED"
                exec_status = "EXECUTION_FAILED"
                verif_status = "NOT_RUN"
                success = False
                if trigger_shce and full_stderr:
                    try:
                        from shce_engine import shce as _shce
                        _shce.handle_failure(command=clean_cmd, error=full_stderr, source="execution_engine", auto_queue=True)
                    except Exception:
                        pass
            else:
                is_generic_fallback = (
                    bool(post_verify) and
                    not post_verify.get("details") and
                    (
                        post_verify.get("message", "").startswith("Command execution completed")
                        or post_verify.get("message", "").startswith("Command completed")
                    )
                )
                has_domain_verification = bool(post_verify and post_verify.get("verified") and not is_generic_fallback)

                if (verif_res and verif_res.status == VerificationStatus.VERIFICATION_TIMEOUT) or (not verif_res and post_verify and (post_verify.get("status") == "VERIFICATION_TIMEOUT" or post_verify.get("timed_out"))):
                    final_status = "VERIFICATION_TIMEOUT"
                    exec_status = "EXECUTION_SUCCEEDED"
                    verif_status = "VERIFICATION_TIMEOUT"
                    success = False
                elif (verif_res and verif_res.status == VerificationStatus.VERIFIED) or (verif_res is None and post_verify and post_verify.get("verified")) or has_domain_verification:
                    final_status = "VERIFIED"
                    exec_status = "EXECUTION_SUCCEEDED"
                    verif_status = "VERIFIED"
                    success = True
                else:
                    final_status = "VERIFICATION_FAILED"
                    exec_status = "EXECUTION_SUCCEEDED"
                    verif_status = "VERIFICATION_FAILED"
                    success = False

            explanation = classified.get("explanation", "") if isinstance(classified, dict) else ""
            if rc == 124:
                final_classification = "EXECUTION_TIMEOUT"
                final_status = "EXECUTION_FAILED"
                msg = f"{operation} for {target_name} timed out after {timeout} seconds."
            elif final_status == "VERIFICATION_TIMEOUT":
                final_classification = "VERIFICATION_TIMEOUT"
                msg = f"{operation} for {target_name} executed, but verification timed out."
            elif final_status == "VERIFICATION_FAILED":
                final_classification = "VERIFICATION_FAILED"
                msg = f"{operation} for {target_name} executed, but verification failed."
            elif success:
                final_classification = classified.get("classification", "SUCCESS") if isinstance(classified, dict) else "SUCCESS"
                msg = f"{operation} for {target_name} confirmed and verified."
            elif rc != 0:
                final_classification = classified.get("classification", "COMMAND_EXECUTION_FAILED") if isinstance(classified, dict) else "COMMAND_EXECUTION_FAILED"
                msg = f"{operation} for {target_name} failed: {explanation or full_stderr}"
            else:
                final_classification = "VERIFICATION_FAILED"
                msg = f"{operation} for {target_name} executed, but verification failed."

            # 8. State Refresh (RESCAN)
            state_refresher.refresh_tool_state(target_name)

            # 9. Structured Telemetry Logging (LOG)
            verif_dict = verif_res.to_dict() if verif_res else (post_verify or {})
            structured_logger.log_event(
                operation=operation,
                application=target_name,
                identity=target_name,
                status=final_status,
                message=msg,
                command=clean_cmd,
                recipe_id=recipe.recipe_id if recipe else None,
                source=source,
                return_code=rc,
                versions={"detected": verif_res.version_detected if verif_res else (post_verify.get("details", {}).get("version") if post_verify else None)},
                verification=verif_dict,
                tier=tier.value,
                trust=trust_score,
                risk=risk_score,
                confidence=confidence_score,
            )

            done_event = {
                "type": "done",
                "returncode": rc,
                "ok": success,
                "success": success,
                "status": final_status,
                "execution_status": exec_status,
                "verification_status": verif_status,
                "classification": final_classification,
                "is_publisher_managed": classified.get("is_publisher_managed", False) if isinstance(classified, dict) else False,
                "official_url": classified.get("official_url", "") if isinstance(classified, dict) else "",
                "publisher_update_command": classified.get("publisher_update_command", "") if isinstance(classified, dict) else "",
                "publisher_update_instructions": classified.get("publisher_update_instructions", "") if isinstance(classified, dict) else "",
                "verification": verif_dict,
                "post_verification": post_verify or {},
                "explanation": explanation,
                "message": msg,
                "stdout": full_stdout,
                "stderr": full_stderr,
                "tier": tier.value,
                "trust": trust_score,
                "risk": risk_score,
                "confidence": confidence_score,
                "executed_but_unverified": (rc == 0 and final_status == "VERIFICATION_TIMEOUT"),
            }
            yield done_event

        finally:
            if lock_acquired:
                resource_lock_mgr.release_resources(owner_id, resources)


# Global singleton execution engine
execution_engine = CentralizedExecutionEngine()

