"""
MavFix Genesis — Incident Data Model
An Incident is a named cluster of correlated Alerts with an LLM-generated
root-cause analysis and a remediation plan attached.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from simulator.models import Alert, Severity


class IncidentStatus(str, Enum):
    OPEN          = "open"           # Detected, not yet analysed
    INVESTIGATING = "investigating"  # LLM RCA in progress
    REMEDIATING   = "remediating"    # Remediation steps executing / pending
    VERIFYING     = "verifying"      # Closed-loop health verification running
    RESOLVED      = "resolved"       # Health check passed, incident closed
    ESCALATED     = "escalated: manual_intervention_required"  # Health check failed
    WATCHLIST     = "watchlist"      # Resolved but being monitored


class RiskLevel(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class RemediationStep(BaseModel):
    """A single action item produced by the LLM root-cause engine."""

    command: str = Field(description="Allow-list command key (e.g. 'restart_pod').")
    rationale: str = Field(description="Why this step addresses the root cause.")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Runtime parameters to interpolate into live_cmd.",
    )
    risk: RiskLevel = Field(default=RiskLevel.LOW)
    # Populated after allow-list check & execution attempt
    tier: Optional[str] = Field(default=None)          # auto | approval | blocked
    status: str = Field(default="pending")              # pending | executed | approved | rejected | blocked
    executed_at: Optional[datetime] = Field(default=None)
    result_message: Optional[str] = Field(default=None)


class RCAResult(BaseModel):
    """Structured output from the Claude LLM root-cause analysis call."""

    root_cause: str = Field(description="Concise root-cause statement (1–2 sentences).")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="LLM confidence score (0.0–1.0).",
    )
    impact_summary: str = Field(description="User-facing impact description.")
    remediation_steps: list[RemediationStep] = Field(default_factory=list)
    risk_level: RiskLevel = Field(description="Overall incident risk level.")
    estimated_resolution_min: Optional[int] = Field(
        default=None,
        description="Estimated time-to-resolution in minutes.",
    )
    llm_raw_response: Optional[str] = Field(
        default=None,
        description="Raw LLM response text for audit purposes.",
    )
    analysed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class Incident(BaseModel):
    """A named cluster of correlated alerts with an attached RCA."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique incident identifier.",
    )
    name: str = Field(
        default="INC-0001",
        description="Auto-generated incident name (e.g. 'INC-0042').",
    )
    scenario_tag: Optional[str] = Field(
        default=None,
        description="Dominant scenario tag if alerts belong to a known scenario.",
    )
    alerts: list[Alert] = Field(default_factory=list)
    status: IncidentStatus = Field(default=IncidentStatus.OPEN)
    severity: Severity = Field(
        default=Severity.P3,
        description="Rolled-up severity (most severe alert wins).",
    )
    services: list[str] = Field(
        default_factory=list,
        description="Unique services involved in this incident.",
    )
    rca: Optional[RCAResult] = Field(
        default=None,
        description="LLM root-cause analysis result.",
    )
    post_mortem: Optional[str] = Field(
        default=None,
        description="Automated Markdown Post-Mortem report generated on resolution.",
    )
    opened_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    notes: list[str] = Field(default_factory=list)

    # ── Computed helpers ──────────────────────────────────────────────────

    @property
    def primary_service(self) -> Optional[str]:
        return self.services[0] if self.services else (self.alerts[0].service if self.alerts else None)

    @property
    def alert_count(self) -> int:
        return len(self.alerts)

    @property
    def duration_sec(self) -> float:
        end = self.resolved_at or datetime.now(timezone.utc)
        return (end - self.opened_at).total_seconds()

    @property
    def is_active(self) -> bool:
        return self.status not in (IncidentStatus.RESOLVED,)

    def add_alert(self, alert: Alert) -> None:
        """Add an alert and refresh severity roll-up and services list."""
        self.alerts.append(alert)
        self._refresh_severity()
        self._refresh_services()
        self.updated_at = datetime.now(timezone.utc)

    def _refresh_severity(self) -> None:
        """Roll up to the most severe (lowest P-number) alert severity."""
        from config.settings import settings
        if not self.alerts:
            return
        best = min(self.alerts, key=lambda a: settings.SEVERITY_ORDER.get(a.severity.value, 99))
        self.severity = best.severity

    def _refresh_services(self) -> None:
        seen: list[str] = []
        for a in self.alerts:
            if a.service not in seen:
                seen.append(a.service)
        self.services = seen

    def to_summary_dict(self) -> dict[str, Any]:
        """Flat dict for Streamlit DataFrames."""
        return {
            "id":        self.name,
            "status":    self.status.value,
            "severity":  self.severity.value,
            "services":  ", ".join(self.services[:3]) + ("…" if len(self.services) > 3 else ""),
            "alerts":    self.alert_count,
            "scenario":  self.scenario_tag or "—",
            "opened":    self.opened_at.strftime("%H:%M:%S"),
            "duration":  f"{self.duration_sec:.0f}s",
            "root_cause": (self.rca.root_cause[:80] + "…") if self.rca else "Analysing…",
        }
