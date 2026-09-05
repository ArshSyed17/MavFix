"""
MavFix Genesis — Incident Manager
Top-level orchestrator that wires together:

  AlertStream → IncidentClusterer → ClaudeRCAEngine → RemediationEngine → AuditLogger

The IncidentManager owns one instance of each sub-system and exposes a
clean interface consumed by the Streamlit UI and by tests.

Lifecycle:
  manager = IncidentManager()
  manager.start()          # begins listening to the alert stream
  manager.trigger("A")     # fires scenario A
  incidents = manager.incidents()
  manager.approve_step(incident_id, step_index)
  manager.stop()
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from config.settings import settings
from core.clustering import IncidentClusterer
from core.llm_engine import ClaudeRCAEngine
from core.models import Incident, IncidentStatus, RemediationStep
from core.remediator import RemediationEngine
from simulator.models import Alert
from simulator.stream import AlertStream, create_stream

logger = logging.getLogger(__name__)


class IncidentManager:
    """
    Central orchestrator.

    Thread safety: individual sub-systems are internally thread-safe.
    The manager itself is single-owner (one per Streamlit session).
    """

    def __init__(
        self,
        stream: Optional[AlertStream] = None,
        enable_llm: bool = True,
        enable_remediation: bool = True,
    ) -> None:
        self._stream       = stream or create_stream()
        self._clusterer    = IncidentClusterer()
        self._remediator   = RemediationEngine(
            on_step_complete=self._on_step_complete
        ) if enable_remediation else None

        self._llm_enabled  = enable_llm
        self._remed_enabled = enable_remediation
        self._engine: Optional[ClaudeRCAEngine] = None

        # Recent raw alerts (ring buffer, newest first)
        self._recent_alerts: list[Alert] = []
        self._alert_lock = threading.Lock()
        self._max_recent = 500

        # In-memory audit log (supplement to SQLite)
        self._audit_events: list[dict] = []
        self._audit_lock = threading.Lock()

        # Flush stale incidents every 60 seconds
        self._flush_timer: Optional[threading.Timer] = None
        self._started = False

        # Register audit logger callback if db module is available
        self._db_logger = None
        self._try_init_db_logger()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> "IncidentManager":
        """Wire up the alert stream callback and start the stream."""
        if self._started:
            return self

        self._stream.register_callback(self._on_alert)
        if not self._stream.is_running:
            self._stream.start()

        # Initialise LLM engine (validates API key)
        if self._llm_enabled:
            try:
                self._engine = ClaudeRCAEngine()
                logger.info("Claude RCA engine initialised (model=%s).", settings.llm_model)
            except EnvironmentError as e:
                logger.warning("LLM disabled: %s", e)
                self._llm_enabled = False

        self._schedule_flush()
        self._started = True
        logger.info("IncidentManager started.")
        return self

    def stop(self) -> None:
        """Stop the alert stream and cancel scheduled tasks."""
        if self._flush_timer:
            self._flush_timer.cancel()
        self._stream.stop()
        self._started = False
        logger.info("IncidentManager stopped.")

    def __enter__(self) -> "IncidentManager":
        return self.start()

    def __exit__(self, *args) -> None:
        self.stop()

    # ── Alert ingestion pipeline ────────────────────────────────────────────

    def _on_alert(self, alert: Alert) -> None:
        """Callback: runs on the AlertStream's emitter thread for every alert."""
        # 1. Persist to recent buffer
        with self._alert_lock:
            self._recent_alerts.insert(0, alert)
            if len(self._recent_alerts) > self._max_recent:
                self._recent_alerts.pop()

        # 2. Audit log
        self._audit("alert_received", {"alert_id": alert.id, "service": alert.service,
                                        "metric": alert.metric, "severity": alert.severity.value})

        # 3. Persist to DB
        if self._db_logger:
            try:
                self._db_logger.log_alert(alert)
            except Exception as e:
                logger.debug("DB alert log failed: %s", e)

        # 4. Cluster
        promoted = self._clusterer.ingest(alert)
        if promoted:
            logger.info("Incident %s promoted with %d alerts.", promoted.name, promoted.alert_count)
            self._on_incident_promoted(promoted)

    def _on_incident_promoted(self, incident: Incident) -> None:
        """Called when a cluster reaches min_alerts and becomes a named incident."""
        incident.status = IncidentStatus.INVESTIGATING
        self._audit("incident_opened", {"incident_id": incident.id, "name": incident.name})

        if self._db_logger:
            try:
                self._db_logger.log_incident(incident)
            except Exception as e:
                logger.debug("DB incident log failed: %s", e)

        if self._llm_enabled and self._engine:
            threading.Thread(
                target=self._run_rca,
                args=(incident,),
                daemon=True,
                name=f"rca-{incident.name}",
            ).start()

    def _run_rca(self, incident: Incident) -> None:
        """Background thread: run LLM RCA then hand off to remediator."""
        logger.info("RCA started for %s …", incident.name)
        rca = self._engine.analyse_safe(incident)
        incident.rca = rca
        incident.status = IncidentStatus.REMEDIATING
        incident.updated_at = datetime.now(timezone.utc)

        self._audit("rca_complete", {
            "incident_id": incident.id,
            "root_cause":  rca.root_cause[:120],
            "confidence":  rca.confidence,
            "risk":        rca.risk_level.value,
            "steps":       len(rca.remediation_steps),
        })

        if self._db_logger:
            try:
                self._db_logger.log_rca(incident)
            except Exception as e:
                logger.debug("DB RCA log failed: %s", e)

        if self._remed_enabled and self._remediator:
            self._remediator.execute_plan(incident)

    def _on_step_complete(self, incident: Incident, step: RemediationStep) -> None:
        """Callback: fires after every remediation step completes."""
        self._audit("remediation_step", {
            "incident_id": incident.id,
            "command":     step.command,
            "status":      step.status,
            "tier":        step.tier,
            "result":      (step.result_message or "")[:200],
        })

        if self._db_logger:
            try:
                self._db_logger.log_remediation_step(incident, step)
            except Exception as e:
                logger.debug("DB remediation log failed: %s", e)

        # Transition to closed-loop health verification when all steps are terminal
        if incident.rca:
            all_done = all(
                s.status in ("executed", "rejected", "blocked", "failed")
                for s in incident.rca.remediation_steps
            )
            has_executed = any(s.status == "executed" for s in incident.rca.remediation_steps)
            if all_done and incident.status == IncidentStatus.REMEDIATING:
                if has_executed and self._remed_enabled and self._remediator:
                    logger.info("All remediation steps terminal for %s. Starting closed-loop verification...", incident.name)
                    self._start_verification(incident)
                elif not has_executed:
                    incident.status = IncidentStatus.ESCALATED
                    self._audit("incident_escalated", {
                        "incident_id": incident.id,
                        "name": incident.name,
                        "reason": "No remediation actions executed",
                    })
                    logger.warning("Incident %s escalated: no actions executed.", incident.name)

    def _start_verification(self, incident: Incident, force_fail: bool = False) -> None:
        """Begin closed-loop health verification on daemon thread."""
        incident.status = IncidentStatus.VERIFYING
        incident.updated_at = datetime.now(timezone.utc)
        self._audit("verification_started", {
            "incident_id": incident.id,
            "name": incident.name,
            "service": incident.primary_service,
        })
        if self._remediator:
            self._remediator.verify_service_health(
                incident,
                on_verified=self._on_verification_complete,
                force_fail=force_fail,
            )

    def _on_verification_complete(self, incident: Incident, passed: bool) -> None:
        """Fires when closed-loop health check finishes."""
        if passed:
            self._audit("incident_resolved", {
                "incident_id": incident.id,
                "name": incident.name,
                "verification": "passed",
            })
            logger.info("Incident %s verification passed -> RESOLVED.", incident.name)
            # Trigger Automated Post-Mortem Generator
            self._trigger_post_mortem(incident)
        else:
            self._audit("incident_escalated", {
                "incident_id": incident.id,
                "name": incident.name,
                "verification": "failed",
                "status": incident.status.value,
            })
            logger.warning("Incident %s verification failed -> ESCALATED: MANUAL_INTERVENTION_REQUIRED.", incident.name)

    def _trigger_post_mortem(self, incident: Incident) -> None:
        """Generate Post-Mortem report via Claude / fallback generator in background."""
        def _post_mortem_worker():
            try:
                engine = self._engine or ClaudeRCAEngine()
                logger.info("Generating post-mortem for %s …", incident.name)
                report = engine.generate_post_mortem(incident)
                incident.post_mortem = report
                self._audit("post_mortem_generated", {
                    "incident_id": incident.id,
                    "name": incident.name,
                    "length": len(report),
                })
                logger.info("Post-mortem generated for %s (%d chars).", incident.name, len(report))
            except Exception as e:
                logger.error("Failed to generate post-mortem for %s: %s", incident.name, e)

        threading.Thread(
            target=_post_mortem_worker,
            daemon=True,
            name=f"post-mortem-{incident.name}",
        ).start()

    # ── Public read API ────────────────────────────────────────────────────

    def recent_alerts(self, limit: int = 100) -> list[Alert]:
        with self._alert_lock:
            return self._recent_alerts[:limit]

    def incidents(self) -> list[Incident]:
        return self._clusterer.all_incidents()

    def active_incidents(self) -> list[Incident]:
        return self._clusterer.all_open_incidents()

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        return self._clusterer.get_incident(incident_id)

    def audit_log(self, limit: int = 200) -> list[dict]:
        with self._audit_lock:
            return list(reversed(self._audit_events))[:limit]

    # ── Trigger API ────────────────────────────────────────────────────────

    def trigger(self, scenario_tag: str) -> list[Alert]:
        """Manually fire a named scenario burst (A–E)."""
        return self._stream.trigger(scenario_tag)

    def trigger_scenario(self, scenario_tag: str) -> list[Alert]:
        """Alias for trigger(scenario_tag)."""
        return self.trigger(scenario_tag)

    # ── Approval API ───────────────────────────────────────────────────────

    def approve_step(self, incident_id: str, step_index: int) -> bool:
        """Approve a pending remediation step. Returns True on success."""
        incident = self._clusterer.get_incident(incident_id)
        if not incident or not incident.rca:
            return False
        try:
            step = incident.rca.remediation_steps[step_index]
        except IndexError:
            return False
        if step.status != "pending_approval":
            return False
        if self._remediator:
            self._remediator.approve_step(incident, step)
        return True

    def reject_step(self, incident_id: str, step_index: int) -> bool:
        """Reject a pending remediation step. Returns True on success."""
        incident = self._clusterer.get_incident(incident_id)
        if not incident or not incident.rca:
            return False
        try:
            step = incident.rca.remediation_steps[step_index]
        except IndexError:
            return False
        if step.status != "pending_approval":
            return False
        if self._remediator:
            self._remediator.reject_step(incident, step)
        return True

    # ── Stats ──────────────────────────────────────────────────────────────

    @property
    def stream(self) -> AlertStream:
        return self._stream

    @property
    def total_alerts(self) -> int:
        return self._stream.total_emitted

    @property
    def queue_depth(self) -> int:
        return self._stream.queue_depth

    # ── Internals ──────────────────────────────────────────────────────────

    def _audit(self, event: str, data: dict) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event":     event,
            "actor":     "system",
            **data,
        }
        with self._audit_lock:
            self._audit_events.append(entry)
            if len(self._audit_events) > 2000:
                self._audit_events = self._audit_events[-2000:]

    def _schedule_flush(self) -> None:
        """Schedule periodic stale-incident flush."""
        self._clusterer.flush_stale()
        self._flush_timer = threading.Timer(60.0, self._schedule_flush)
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _try_init_db_logger(self) -> None:
        """Lazily wire up the DB audit logger — skip gracefully if DB unavailable."""
        try:
            from audit_logs.logger import AuditLogger
            self._db_logger = AuditLogger()
        except Exception as e:
            logger.debug("DB logger not available yet: %s", e)
