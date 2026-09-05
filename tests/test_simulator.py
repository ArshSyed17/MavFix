"""
MavFix Genesis — Simulator Tests
"""

import pytest
from simulator.models import Alert, Severity
from simulator.scenarios import SCENARIO_REGISTRY, trigger_scenario, ambient_alert


def test_scenario_registry():
    assert set(SCENARIO_REGISTRY.keys()) == {"A", "B", "C", "D", "E"}


@pytest.mark.parametrize("tag", ["A", "B", "C", "D", "E"])
def test_trigger_scenarios(tag):
    alerts = trigger_scenario(tag)
    assert len(alerts) >= 3
    assert all(isinstance(a, Alert) for a in alerts)
    assert all(a.scenario_tag == tag for a in alerts)
    assert any(a.severity in (Severity.P1, Severity.P2) for a in alerts)


def test_ambient_alert():
    alert = ambient_alert()
    assert isinstance(alert, Alert)
    assert alert.severity in (Severity.P3, Severity.P4)
    assert alert.scenario_tag is None
    assert alert.service != ""
