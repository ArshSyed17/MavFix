"""
MavFix Genesis — Audit Logger
High-level write interface used by IncidentManager.
Bridges typed domain objects to the raw SQL helpers in db.py.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from core.models import Incident, RemediationStep
from simulator.models import Alert

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Wraps audit_logs/db.py with domain-aware serialisers.

    Called from IncidentManager's callbacks — should never raise;
    log errors silently so the main pipeline continues.
    """

    def log_alert(self, alert: Alert) -> None:
        try:
            from audit_logs import db
            db.upsert_alert({
                "id":           alert.id,
                "timestamp":    alert.timestamp.isoformat(),
                "service":      alert.service,
                "severity":     alert.severity.value,
                "metric":       alert.metric,
                "value":        alert.value,
                "unit":         alert.unit,
                "message":      alert.message,
                "scenario_tag": alert.scenario_tag,
                "status":       alert.status.value,
                "labels":       alert.labels,
                "runbook_url":  alert.runbook_url,
            })
        except Exception as e:
            logger.debug("log_alert failed: %s", e)

    def log_incident(self, incident: Incident) -> None:
        try:
            from audit_logs import db
            db.upsert_incident({
                "id":           incident.id,
                "name":         incident.name,
                "scenario_tag": incident.scenario_tag,
                "status":       incident.status.value,
                "severity":     incident.severity.value,
                "services":     incident.services,
                "alert_ids":    [a.id for a in incident.alerts],
                "rca_json":     None,
                "opened_at":    incident.opened_at.isoformat(),
                "resolved_at":  incident.resolved_at.isoformat() if incident.resolved_at else None,
                "updated_at":   incident.updated_at.isoformat(),
                "notes":        incident.notes,
            })
        except Exception as e:
            logger.debug("log_incident failed: %s", e)

    def log_rca(self, incident: Incident) -> None:
        """Persist RCA result into the incidents row."""
        if not incident.rca:
            return
        try:
            from audit_logs import db
            rca_dict = {
                "root_cause":               incident.rca.root_cause,
                "confidence":               incident.rca.confidence,
                "impact_summary":           incident.rca.impact_summary,
                "risk_level":               incident.rca.risk_level.value,
                "estimated_resolution_min": incident.rca.estimated_resolution_min,
                "analysed_at":              incident.rca.analysed_at.isoformat(),
                "remediation_steps": [
                    {
                        "command":   s.command,
                        "rationale": s.rationale,
                        "params":    s.params,
                        "risk":      s.risk.value,
                    }
                    for s in incident.rca.remediation_steps
                ],
            }
            db.upsert_incident({
                "id":           incident.id,
                "name":         incident.name,
                "scenario_tag": incident.scenario_tag,
                "status":       incident.status.value,
                "severity":     incident.severity.value,
                "services":     incident.services,
                "alert_ids":    [a.id for a in incident.alerts],
                "rca_json":     json.dumps(rca_dict),
                "opened_at":    incident.opened_at.isoformat(),
                "resolved_at":  incident.resolved_at.isoformat() if incident.resolved_at else None,
                "updated_at":   incident.updated_at.isoformat(),
                "notes":        incident.notes,
            })
        except Exception as e:
            logger.debug("log_rca failed: %s", e)

    def log_remediation_step(self, incident: Incident, step: RemediationStep) -> None:
        try:
            from audit_logs import db

            # Write to remediation_actions
            db.insert_remediation_action({
                "incident_id":    incident.id,
                "incident_name":  incident.name,
                "command":        step.command,
                "tier":           step.tier,
                "risk":           step.risk.value if step.risk else None,
                "status":         step.status,
                "rationale":      step.rationale,
                "params":         step.params,
                "result_message": step.result_message,
                "executed_at":    step.executed_at.isoformat() if step.executed_at else None,
                "actor":          "system",
            })

            # If pending approval → also write to approval_queue
            if step.status == "pending_approval":
                db.upsert_approval_queue_item({
                    "incident_id":   incident.id,
                    "incident_name": incident.name,
                    "command":       step.command,
                    "rationale":     step.rationale,
                    "params":        step.params,
                    "risk":          step.risk.value if step.risk else "medium",
                })

        except Exception as e:
            logger.debug("log_remediation_step failed: %s", e)

    def log_human_action(
        self,
        incident_id: str,
        incident_name: str,
        command: str,
        action: str,  # 'approved' | 'rejected'
        actor: str = "operator",
        queue_id: int | None = None,
    ) -> None:
        """Log a human approval or rejection action."""
        try:
            from audit_logs import db
            db.insert_remediation_action({
                "incident_id":    incident_id,
                "incident_name":  incident_name,
                "command":        command,
                "tier":           "approval",
                "risk":           "medium",
                "status":         action,
                "rationale":      f"Human {action} via dashboard.",
                "params":         {},
                "result_message": f"Operator decision: {action}.",
                "executed_at":    datetime.now(timezone.utc).isoformat(),
                "actor":          actor,
            })
            if queue_id is not None:
                db.resolve_approval_queue_item(queue_id, action, actor)
        except Exception as e:
            logger.debug("log_human_action failed: %s", e)
