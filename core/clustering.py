"""
MavFix Genesis — Incident Clusterer
Groups incoming Alert objects into named Incidents using three signals:

  1. Time windowing   — alerts within CLUSTER_WINDOW_SEC of the oldest alert
  2. Scenario tagging — alerts sharing a scenario_tag always cluster together
  3. TF-IDF cosine    — semantically similar messages cluster even without a tag

Design notes:
  • This clusterer is intentionally simple and stateful (in-memory).
  • The IncidentManager owns the single Clusterer instance and calls
    `ingest(alert)` for every new alert from the stream.
  • `flush_stale()` should be called periodically to close old open windows.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config.settings import settings
from core.models import Incident, IncidentStatus
from simulator.models import Alert, Severity

logger = logging.getLogger(__name__)

_INCIDENT_COUNTER: list[int] = [0]  # module-level counter for INC-NNNN names
_COUNTER_LOCK = threading.Lock()


def _next_incident_name() -> str:
    with _COUNTER_LOCK:
        _INCIDENT_COUNTER[0] += 1
        return f"INC-{_INCIDENT_COUNTER[0]:04d}"


class IncidentClusterer:
    """
    Stateful alert-to-incident clusterer.

    Thread-safety: all public methods acquire `_lock`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Open incidents that are still accepting new alerts
        self._open_incidents: dict[str, Incident] = {}

        # scenario_tag → incident_id for fast tag-based lookup
        self._tag_to_incident: dict[str, str] = {}

        # Recent alert messages for TF-IDF (last N messages per incident)
        self._incident_messages: dict[str, list[str]] = defaultdict(list)

        # Settings
        self._window_sec   = settings.cluster_window_sec
        self._min_alerts   = settings.cluster_min_alerts
        self._sim_thresh   = settings.cluster_similarity_threshold

        # Completed incidents (promoted after window closes)
        self._closed_incidents: list[Incident] = []

    # ── Public API ─────────────────────────────────────────────────────────

    def ingest(self, alert: Alert) -> Optional[Incident]:
        """
        Ingest one alert.

        Returns the Incident it was added to once the minimum alert count
        is reached (i.e., when a new named incident is 'promoted').
        Returns None if the alert was absorbed into an existing incident
        or is still accumulating.
        """
        with self._lock:
            incident = self._find_or_create_incident(alert)
            incident.add_alert(alert)
            self._incident_messages[incident.id].append(alert.message)

            # Promote to OPEN once min threshold met
            newly_promoted = (
                incident.alert_count == self._min_alerts
                and incident.status == IncidentStatus.OPEN
            )
            logger.debug(
                "Alert %s → %s (total alerts: %d)",
                alert.id[:8], incident.name, incident.alert_count,
            )
            return incident if newly_promoted else None

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        with self._lock:
            return self._open_incidents.get(incident_id)

    def all_open_incidents(self) -> list[Incident]:
        """Return a snapshot of all currently open incidents."""
        with self._lock:
            return list(self._open_incidents.values())

    def all_incidents(self) -> list[Incident]:
        """Return open + closed incidents, newest first."""
        with self._lock:
            combined = list(self._open_incidents.values()) + self._closed_incidents
            return sorted(combined, key=lambda i: i.opened_at, reverse=True)

    def close_incident(self, incident_id: str) -> Optional[Incident]:
        """Manually close an incident (e.g. after remediation)."""
        with self._lock:
            incident = self._open_incidents.pop(incident_id, None)
            if incident:
                incident.status = IncidentStatus.RESOLVED
                incident.resolved_at = datetime.now(timezone.utc)
                self._closed_incidents.append(incident)
                # Clean up tag mapping
                if incident.scenario_tag:
                    self._tag_to_incident.pop(incident.scenario_tag, None)
                logger.info("Incident %s closed.", incident.name)
            return incident

    def flush_stale(self) -> list[Incident]:
        """
        Close any open incidents whose time window has expired.
        Call this periodically (e.g. every 60s) from IncidentManager.
        Returns the list of newly closed incidents.
        """
        now = datetime.now(timezone.utc)
        stale_ids: list[str] = []

        with self._lock:
            for inc_id, incident in self._open_incidents.items():
                age = (now - incident.opened_at).total_seconds()
                if age > self._window_sec * 2:  # 2× window = definitely stale
                    stale_ids.append(inc_id)

        closed: list[Incident] = []
        for inc_id in stale_ids:
            inc = self.close_incident(inc_id)
            if inc:
                closed.append(inc)
                logger.info("Flushed stale incident %s (age > %ds)", inc.name, self._window_sec * 2)
        return closed

    # ── Internal clustering logic ───────────────────────────────────────────

    def _find_or_create_incident(self, alert: Alert) -> Incident:
        """
        Find an existing open incident for this alert or create a new one.
        Priority order:
          1. Matching scenario_tag
          2. TF-IDF cosine similarity against recent incident messages
          3. Create new incident
        """
        # 1. Scenario-tag match
        if alert.scenario_tag:
            inc_id = self._tag_to_incident.get(alert.scenario_tag)
            if inc_id and inc_id in self._open_incidents:
                return self._open_incidents[inc_id]

        # 2. TF-IDF similarity match (only if we have open incidents)
        if self._open_incidents:
            match = self._find_by_similarity(alert)
            if match:
                return match

        # 3. Create new incident
        return self._create_incident(alert)

    def _find_by_similarity(self, alert: Alert) -> Optional[Incident]:
        """
        Use TF-IDF cosine similarity to find an open incident whose recent
        messages are semantically related to the incoming alert message.
        """
        candidates: list[tuple[str, list[str]]] = [
            (inc_id, msgs)
            for inc_id, msgs in self._incident_messages.items()
            if inc_id in self._open_incidents and msgs
        ]
        if not candidates:
            return None

        # Build corpus: one "document" per incident (concatenate recent messages)
        incident_ids  = [c[0] for c in candidates]
        incident_docs = [" ".join(c[1][-6:]) for c in candidates]  # last 6 messages
        query_doc     = alert.message

        corpus = incident_docs + [query_doc]
        try:
            vectorizer = TfidfVectorizer(
                stop_words="english",
                max_features=512,
                ngram_range=(1, 2),
            )
            tfidf_matrix = vectorizer.fit_transform(corpus)
        except ValueError:
            # Corpus too sparse / single token — skip similarity check
            return None

        query_vec  = tfidf_matrix[-1]
        corpus_vec = tfidf_matrix[:-1]
        sims       = cosine_similarity(query_vec, corpus_vec).flatten()

        best_idx  = int(np.argmax(sims))
        best_sim  = float(sims[best_idx])

        if best_sim >= self._sim_thresh:
            inc_id = incident_ids[best_idx]
            logger.debug(
                "Alert '%s…' matched %s via TF-IDF (sim=%.3f)",
                alert.message[:40], self._open_incidents[inc_id].name, best_sim,
            )
            return self._open_incidents[inc_id]

        return None

    def _create_incident(self, alert: Alert) -> Incident:
        """Instantiate a fresh Incident and register it."""
        name = _next_incident_name()
        scenario_label = ""
        if alert.scenario_tag:
            from config.settings import settings as s
            scenario_label = s.SCENARIO_LABELS.get(alert.scenario_tag, "")

        incident = Incident(
            name=name,
            scenario_tag=alert.scenario_tag,
            status=IncidentStatus.OPEN,
            severity=alert.severity,
            notes=[f"Incident created from alert on {alert.service}."],
        )
        if scenario_label:
            incident.notes.append(f"Scenario: {scenario_label}")

        self._open_incidents[incident.id] = incident

        if alert.scenario_tag:
            self._tag_to_incident[alert.scenario_tag] = incident.id

        logger.info(
            "New incident %s created (trigger: %s / %s)",
            name, alert.service, alert.scenario_tag or "ambient",
        )
        return incident
