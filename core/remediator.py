"""
MavFix Genesis — Remediation Engine
Semi-autonomous executor that gates every LLM-proposed remediation step
against the allow-list before simulating or (in LIVE_MODE) actually running it.

Flow per step:
  1. Look up command in allow-list
  2a. AUTO   → simulate/execute immediately, log result
  2b. APPROVAL → persist to approval_queue table, surface in UI
  2c. BLOCKED  → log rejection, annotate step

Simulated execution: prints a rich formatted line + waits `timeout_sec / 10`
  to give realistic "I'm doing something" feel in the dashboard.

Live execution (LIVE_MODE=true): runs the `live_cmd` template as a subprocess
  with {params} interpolated. stdout/stderr are captured and logged.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from config.loader import CommandTier, load_allow_list
from config.settings import settings
from core.models import Incident, IncidentStatus, RemediationStep, RiskLevel

logger = logging.getLogger(__name__)
_console = Console(highlight=False)

# Callback type: called after each step completes so IncidentManager / UI can react
StepCallback = Callable[[Incident, RemediationStep], None]


def check_service_health(service_name: str, force_fail: bool = False) -> bool:
    """
    Simulated closed-loop health check for a service after remediation.
    Simulates a 5-second health verification probe window (time.sleep(5.0)).
    Returns True if service telemetry and probes are healthy, or False on failure.
    """
    logger.info(
        "Running closed-loop health check for service '%s' (5s verification window)...",
        service_name,
    )
    time.sleep(5.0)
    if force_fail:
        logger.warning("Closed-loop health check FAILED for '%s'.", service_name)
        return False
    logger.info(
        "Closed-loop health check PASSED for '%s' — metrics restored to nominal bounds.",
        service_name,
    )
    return True


class RemediationEngine:
    """
    Semi-autonomous remediation executor.

    Instantiated once by IncidentManager and reused across incidents.
    All execution happens on daemon threads so the caller never blocks.
    """

    def __init__(self, on_step_complete: Optional[StepCallback] = None) -> None:
        self._allow_list  = load_allow_list()
        self._callbacks: list[StepCallback] = []
        if on_step_complete:
            self._callbacks.append(on_step_complete)

    def register_callback(self, fn: StepCallback) -> None:
        self._callbacks.append(fn)

    # ── Public API ─────────────────────────────────────────────────────────

    def execute_plan(
        self,
        incident: Incident,
        approval_callback: Optional[Callable[[Incident, RemediationStep], None]] = None,
    ) -> None:
        """
        Process all remediation steps in the incident's RCA plan.
        Runs on a background daemon thread — non-blocking.
        """
        if not incident.rca or not incident.rca.remediation_steps:
            logger.warning("execute_plan called on %s with no RCA/steps.", incident.name)
            return

        threading.Thread(
            target=self._run_plan,
            args=(incident, approval_callback),
            daemon=True,
            name=f"remediate-{incident.name}",
        ).start()

    def approve_step(self, incident: Incident, step: RemediationStep) -> None:
        """
        Human approves a pending APPROVAL-tier step.
        Executes immediately on a daemon thread.
        """
        logger.info("Human approved step '%s' for %s.", step.command, incident.name)
        threading.Thread(
            target=self._execute_step,
            args=(incident, step),
            daemon=True,
            name=f"approved-{step.command}",
        ).start()

    def reject_step(self, incident: Incident, step: RemediationStep) -> None:
        """Human rejects a pending APPROVAL-tier step."""
        step.status = "rejected"
        step.executed_at = datetime.now(timezone.utc)
        step.result_message = "Rejected by operator."
        logger.info("Operator rejected step '%s' for %s.", step.command, incident.name)
        self._fire_callbacks(incident, step)

    def classify_step(self, step: RemediationStep) -> str:
        """Classify a step's tier against the allow-list and mutate step.tier."""
        cmd_def = self._allow_list.get(step.command)
        tier = cmd_def.tier if cmd_def else CommandTier.BLOCKED
        step.tier = tier.value
        return step.tier

    _classify_step = classify_step

    def verify_service_health(
        self,
        incident: Incident,
        on_verified: Optional[Callable[[Incident, bool], None]] = None,
        force_fail: bool = False,
    ) -> None:
        """
        Closed-loop health verification.
        Transitions incident state to VERIFYING.
        Runs simulated 5-second health check on a daemon thread.
        Flipping to RESOLVED on pass, or ESCALATED: MANUAL_INTERVENTION_REQUIRED on fail.
        """
        incident.status = IncidentStatus.VERIFYING
        incident.updated_at = datetime.now(timezone.utc)
        logger.info("[%s] State transitioned to VERIFYING. Running closed-loop health checks...", incident.name)

        def _worker() -> None:
            svc = incident.primary_service or "system"
            passed = check_service_health(svc, force_fail=force_fail)
            if passed:
                incident.status = IncidentStatus.RESOLVED
                incident.resolved_at = datetime.now(timezone.utc)
                logger.info("[%s] Health check passed -> State flipped to RESOLVED.", incident.name)
            else:
                incident.status = IncidentStatus.ESCALATED
                logger.warning("[%s] Health check failed -> State flipped to ESCALATED: MANUAL_INTERVENTION_REQUIRED.", incident.name)
            incident.updated_at = datetime.now(timezone.utc)
            if on_verified:
                on_verified(incident, passed)

        threading.Thread(
            target=_worker,
            daemon=True,
            name=f"verify-{incident.name}",
        ).start()

    # ── Internal plan execution ────────────────────────────────────────────

    def _run_plan(
        self,
        incident: Incident,
        approval_callback: Optional[Callable] = None,
    ) -> None:
        for step in incident.rca.remediation_steps:
            tier_str = self.classify_step(step)
            tier = CommandTier(tier_str)

            if tier == CommandTier.AUTO:
                self._execute_step(incident, step)
                time.sleep(0.5)  # brief gap between auto-steps

            elif tier == CommandTier.APPROVAL:
                step.status = "pending_approval"
                step.result_message = (
                    "⏳ Awaiting operator approval before execution."
                )
                logger.info(
                    "[%s] Step '%s' queued for approval.",
                    incident.name, step.command,
                )
                self._fire_callbacks(incident, step)
                if approval_callback:
                    approval_callback(incident, step)

            else:  # BLOCKED or unknown
                step.status = "blocked"
                step.executed_at = datetime.now(timezone.utc)
                step.result_message = (
                    f"🚫 Command '{step.command}' is on the blocked list. "
                    "Escalate to ops team."
                )
                logger.warning(
                    "[%s] Step '%s' BLOCKED by allow-list.",
                    incident.name, step.command,
                )
                self._fire_callbacks(incident, step)

    def _execute_step(self, incident: Incident, step: RemediationStep) -> None:
        """Execute one step — simulated or live depending on LIVE_MODE."""
        step.executed_at = datetime.now(timezone.utc)

        if settings.live_mode:
            self._run_live(incident, step)
        else:
            self._run_simulated(incident, step)

        self._fire_callbacks(incident, step)

    # ── Simulated execution ────────────────────────────────────────────────

    def _run_simulated(self, incident: Incident, step: RemediationStep) -> None:
        """
        Simulate execution: log richly to console, wait a realistic interval,
        then mark as executed.
        """
        cmd_def  = self._allow_list.get(step.command)
        timeout  = cmd_def.timeout_sec if cmd_def else 10
        sim_wait = max(1.0, timeout / 10)

        try:
            _console.print(
                Panel(
                    Text.assemble(
                        ("[SIMULATED] ", "bold green"),
                        (f"{step.command}", "bold white"),
                        ("\n  Incident : ", "dim"),
                        (incident.name, "cyan"),
                        ("\n  Rationale: ", "dim"),
                        (step.rationale[:80], "white"),
                        ("\n  Params   : ", "dim"),
                        (str(step.params), "yellow"),
                    ),
                    title=f"[bold green]AUTO REMEDIATION[/] — {incident.name}",
                    border_style="green",
                )
            )
        except Exception:
            # Fallback if console encoding doesn't support rich formatting
            logger.info("[SIMULATED] %s for %s: %s", step.command, incident.name, step.params)

        # Simulate doing work
        time.sleep(sim_wait)

        step.status = "executed"
        step.result_message = (
            f"✅ Simulated: {step.command} completed in ~{sim_wait:.0f}s "
            f"(live_mode=False). No real system changes made."
        )
        logger.info(
            "[%s] Simulated step '%s' ✓ (%.1fs)",
            incident.name, step.command, sim_wait,
        )

    # ── Live execution ─────────────────────────────────────────────────────

    def _run_live(self, incident: Incident, step: RemediationStep) -> None:
        """
        Execute the allow-list live_cmd as a real subprocess.
        {params} are interpolated before execution.
        stdout/stderr are captured and stored in step.result_message.
        """
        cmd_def = self._allow_list.get(step.command)
        if not cmd_def or not cmd_def.live_cmd:
            step.status = "blocked"
            step.result_message = "No live_cmd defined — execution skipped."
            return

        try:
            shell_cmd = cmd_def.live_cmd.format(params=step.params)
        except KeyError as e:
            step.status = "failed"
            step.result_message = f"Param interpolation failed: missing key {e}"
            logger.error("[%s] live_cmd param error: %s", incident.name, e)
            return

        logger.warning(
            "[LIVE_MODE] [%s] Executing: %s", incident.name, shell_cmd
        )

        try:
            _console.print(
                Panel(
                    Text.assemble(
                        ("[LIVE] ", "bold red"),
                        (f"{step.command}", "bold white"),
                        ("\n  CMD: ", "dim"),
                        (shell_cmd, "yellow"),
                    ),
                    title=f"[bold red]LIVE REMEDIATION[/] — {incident.name}",
                    border_style="red",
                )
            )
        except Exception:
            logger.info("[LIVE] %s: %s", step.command, shell_cmd)

        try:
            proc = subprocess.run(
                shell_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=cmd_def.timeout_sec,
            )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()

            if proc.returncode == 0:
                step.status = "executed"
                step.result_message = (
                    f"✅ Exit 0. "
                    + (f"stdout: {stdout[:300]}" if stdout else "No output.")
                )
            else:
                step.status = "failed"
                step.result_message = (
                    f"❌ Exit {proc.returncode}. "
                    + (f"stderr: {stderr[:300]}" if stderr else "No error output.")
                )
                logger.error(
                    "[LIVE] step '%s' failed (rc=%d): %s",
                    step.command, proc.returncode, stderr[:200],
                )

        except subprocess.TimeoutExpired:
            step.status = "failed"
            step.result_message = f"⏱ Command timed out after {cmd_def.timeout_sec}s."
            logger.error("[LIVE] step '%s' timed out.", step.command)

        except Exception as exc:
            step.status = "failed"
            step.result_message = f"💥 Unexpected error: {exc}"
            logger.exception("[LIVE] step '%s' raised.", step.command)

    # ── Callbacks ──────────────────────────────────────────────────────────

    def _fire_callbacks(self, incident: Incident, step: RemediationStep) -> None:
        for cb in self._callbacks:
            try:
                cb(incident, step)
            except Exception as exc:
                logger.error("Remediation callback %s raised: %s", cb, exc)
