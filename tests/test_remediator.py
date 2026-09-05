"""
MavFix Genesis — Remediation Engine Tests
"""

import pytest
from core.models import Incident, RemediationStep, RiskLevel, RCAResult
from core.remediator import RemediationEngine
from simulator.scenarios import trigger_scenario


def test_remediation_execution_and_tiers():
    engine = RemediationEngine()
    alerts = trigger_scenario("A")
    incident = Incident(
        alerts=alerts,
        rca=RCAResult(
            root_cause="High connection count on postgres pool.",
            confidence=0.95,
            impact_summary="Intermittent timeouts.",
            risk_level=RiskLevel.MEDIUM,
            remediation_steps=[
                RemediationStep(command="flush_connection_pool", rationale="Free idle conn"),
                RemediationStep(command="kill_long_running_queries", rationale="Kill slow query"),
                RemediationStep(command="delete_persistent_volume", rationale="Accidental bad cmd"),
            ]
        )
    )

    # Step 0: flush_connection_pool -> AUTO tier
    engine._classify_step(incident.rca.remediation_steps[0])
    assert incident.rca.remediation_steps[0].tier == "auto"

    # Step 1: kill_long_running_queries -> APPROVAL tier
    engine._classify_step(incident.rca.remediation_steps[1])
    assert incident.rca.remediation_steps[1].tier == "approval"

    # Step 2: delete_persistent_volume -> BLOCKED tier
    engine._classify_step(incident.rca.remediation_steps[2])
    assert incident.rca.remediation_steps[2].tier == "blocked"
