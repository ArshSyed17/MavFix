"""
MavFix Genesis — Alert Data Model
The `Alert` Pydantic model is the atomic unit flowing through the entire system.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Severity(str, Enum):
    P1 = "P1"  # Critical — immediate action required
    P2 = "P2"  # High — action within 15 minutes
    P3 = "P3"  # Medium — action within 1 hour
    P4 = "P4"  # Low — informational / watch


class AlertStatus(str, Enum):
    FIRING = "firing"
    RESOLVED = "resolved"
    ACKNOWLEDGED = "acknowledged"


class Alert(BaseModel):
    """A single monitoring alert emitted by the simulator or a real alerting system."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique alert identifier.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the alert fired.",
    )
    service: str = Field(description="Originating service name (e.g. 'postgres-primary').")
    severity: Severity = Field(description="Alert severity (P1–P4).")
    metric: str = Field(description="Metric name that triggered the alert.")
    value: float = Field(description="Observed metric value at alert time.")
    unit: str = Field(default="", description="Metric unit (%, ms, MB/s, etc.).")
    message: str = Field(description="Human-readable alert description.")
    scenario_tag: Optional[str] = Field(
        default=None,
        description="Scenario identifier (A–E) if part of a simulated burst; None for ambient.",
    )
    status: AlertStatus = Field(default=AlertStatus.FIRING)
    labels: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value labels (environment, region, team, etc.).",
    )
    runbook_url: Optional[str] = Field(
        default=None,
        description="Link to the runbook for this alert type.",
    )

    @field_validator("service")
    @classmethod
    def service_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("service must not be empty")
        return v.strip()

    @property
    def age_seconds(self) -> float:
        """Seconds since this alert fired."""
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()

    def to_display_dict(self) -> dict[str, Any]:
        """Flat dict suitable for Streamlit DataFrames."""
        return {
            "id":           self.id[:8],
            "time":         self.timestamp.strftime("%H:%M:%S"),
            "service":      self.service,
            "severity":     self.severity.value,
            "metric":       self.metric,
            "value":        f"{self.value:.1f} {self.unit}".strip(),
            "message":      self.message,
            "scenario":     self.scenario_tag or "—",
            "status":       self.status.value,
        }

    model_config = ConfigDict(use_enum_values=False)
