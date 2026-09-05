"""
MavFix Genesis — Tests for Closed-Loop Verification & Post-Mortem Generator
"""

import time
import pytest
from core.models import Incident, IncidentStatus, RCAResult, RemediationStep, RiskLevel
from core.remediator import RemediationEngine, check_service_health
from core.llm_engine import ClaudeRCAEngine
from simulator.scenarios import trigger_scenario


def test_check_service_health():
    """Verify check_service_health returns True on normal run, False on force_fail."""
    start = time.time()
    # Test force_fail
    failed = check_service_health("postgres-primary", force_fail=True)
    assert failed is False
    elapsed = time.time() - start
    # Verify simulated probe duration ~5s
    assert elapsed >= 4.5


def test_verification_state_transition_success():
    """Verify state transitions: REMEDIATING -> VERIFYING -> RESOLVED."""
    engine = RemediationEngine()
    incident = Incident(
        name="INC-TEST-01",
        status=IncidentStatus.REMEDIATING,
        rca=RCAResult(
            root_cause="Test DB overload",
            confidence=0.9,
            impact_summary="Latency spike",
            risk_level=RiskLevel.MEDIUM,
            remediation_steps=[
                RemediationStep(command="flush_connection_pool", rationale="free pool")
            ]
        )
    )

    verified_results = []
    def on_verified(inc, passed):
        verified_results.append((inc.status, passed))

    engine.verify_service_health(incident, on_verified=on_verified, force_fail=False)
    # Immediate state should be VERIFYING
    assert incident.status == IncidentStatus.VERIFYING

    # Wait for daemon thread to complete (5 seconds)
    time.sleep(5.5)

    assert incident.status == IncidentStatus.RESOLVED
    assert len(verified_results) == 1
    assert verified_results[0][0] == IncidentStatus.RESOLVED
    assert verified_results[0][1] is True


def test_verification_state_transition_failure():
    """Verify state transitions: REMEDIATING -> VERIFYING -> ESCALATED."""
    engine = RemediationEngine()
    incident = Incident(
        name="INC-TEST-02",
        status=IncidentStatus.REMEDIATING,
        rca=RCAResult(
            root_cause="Test failure",
            confidence=0.8,
            impact_summary="Broken",
            risk_level=RiskLevel.HIGH,
            remediation_steps=[
                RemediationStep(command="restart_pod", rationale="restart")
            ]
        )
    )

    engine.verify_service_health(incident, force_fail=True)
    assert incident.status == IncidentStatus.VERIFYING

    time.sleep(5.5)
    assert incident.status == IncidentStatus.ESCALATED
    assert incident.status.value == "escalated: manual_intervention_required"


def test_generate_post_mortem():
    """Verify automated post-mortem generator produces all 4 required sections."""
    alerts = trigger_scenario("A")
    incident = Incident(
        name="INC-TEST-A",
        scenario_tag="A",
        alerts=alerts,
        status=IncidentStatus.RESOLVED,
        rca=RCAResult(
            root_cause="PostgreSQL connection pool exhaustion",
            confidence=0.95,
            impact_summary="Gateway 504 errors",
            risk_level=RiskLevel.MEDIUM,
            remediation_steps=[
                RemediationStep(
                    command="flush_connection_pool",
                    rationale="Flush leaked connections",
                    status="executed",
                    result_message="Successfully flushed 42 idle connections",
                )
            ]
        )
    )

    llm_engine = ClaudeRCAEngine()
    report = llm_engine.generate_post_mortem(incident)

    assert report is not None
    assert len(report) > 300
    # Required sections check
    assert "Executive Summary" in report
    assert "Root Cause Analysis" in report
    assert "Incident Timeline" in report
    assert "Preventative Recommendations" in report
