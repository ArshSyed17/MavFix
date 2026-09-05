"""simulator package — MavFix Genesis synthetic alert stream."""

from simulator.models import Alert, Severity, AlertStatus
from simulator.scenarios import trigger_scenario, ambient_alert, SCENARIO_REGISTRY
from simulator.stream import AlertStream, create_stream

__all__ = [
    "Alert",
    "Severity",
    "AlertStatus",
    "trigger_scenario",
    "ambient_alert",
    "SCENARIO_REGISTRY",
    "AlertStream",
    "create_stream",
]
