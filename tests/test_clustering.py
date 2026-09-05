"""
MavFix Genesis — Incident Clustering Tests
"""

import pytest
from core.clustering import IncidentClusterer
from simulator.scenarios import trigger_scenario


def test_clustering_scenario_a():
    clusterer = IncidentClusterer()
    alerts = trigger_scenario("A")

    promoted_incidents = []
    for alert in alerts:
        res = clusterer.ingest(alert)
        if res:
            promoted_incidents.append(res)

    # Scenario A should form at least one promoted incident
    assert len(promoted_incidents) >= 1
    incident = promoted_incidents[0]
    assert incident.alert_count >= 2
    assert "postgres" in incident.primary_service.lower() or "db" in incident.name.lower() or "inc" in incident.name.lower()
