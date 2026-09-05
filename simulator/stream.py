"""
MavFix Genesis — Alert Stream
Background alert producer that continuously emits ambient alerts on a ticker
and allows on-demand scenario bursts. Thread-safe via queue.Queue.
Uses standard library threading (no asyncio / event-loop dependencies).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from config.settings import settings
from simulator.models import Alert
from simulator.scenarios import ambient_alert, trigger_scenario

logger = logging.getLogger(__name__)


class AlertStream:
    """
    Thread-safe alert producer.

    - Emits one ambient alert every `ambient_interval_sec` seconds via background thread.
    - Exposes `trigger(tag)` for on-demand scenario bursts.
    - Consumers read from `queue` (blocking) or call `drain()` for all pending alerts.
    - All emitted alerts are also dispatched to registered callbacks (e.g. DB writer).
    """

    def __init__(self, ambient_interval_sec: Optional[int] = None) -> None:
        self._interval = ambient_interval_sec or settings.ambient_interval_sec
        self._queue: queue.Queue[Alert] = queue.Queue(maxsize=2048)
        self._callbacks: list = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._total_emitted = 0

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> "AlertStream":
        """Start the background ambient ticker. Idempotent."""
        if self._started:
            return self
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_ticker,
            daemon=True,
            name="AmbientAlertTicker",
        )
        self._thread.start()
        self._started = True
        logger.info(
            "AlertStream started — ambient interval=%ds", self._interval
        )
        return self

    def stop(self) -> None:
        """Gracefully stop the background ticker."""
        if self._started:
            self._stop_event.set()
            self._started = False
            logger.info("AlertStream stopped.")

    def _run_ticker(self) -> None:
        """Background loop emitting ambient alerts at regular intervals."""
        while not self._stop_event.wait(timeout=self._interval):
            try:
                self._emit_ambient()
            except Exception as e:
                logger.error("Error emitting ambient alert: %s", e)

    def __enter__(self) -> "AlertStream":
        return self.start()

    def __exit__(self, *args) -> None:
        self.stop()

    # ── Callbacks ──────────────────────────────────────────────────────────

    def register_callback(self, fn) -> None:
        """Register a callable(alert: Alert) invoked on every emitted alert."""
        with self._lock:
            self._callbacks.append(fn)

    # ── Emission ───────────────────────────────────────────────────────────

    def _emit(self, alert: Alert) -> None:
        """Internal: put alert on queue and fire callbacks."""
        try:
            self._queue.put_nowait(alert)
        except queue.Full:
            logger.warning("Alert queue full — dropping alert %s", alert.id[:8])
            return

        with self._lock:
            self._total_emitted += 1
            callbacks = list(self._callbacks)

        for cb in callbacks:
            try:
                cb(alert)
            except Exception as exc:
                logger.error("Callback %s raised: %s", cb, exc)

    def _emit_ambient(self) -> None:
        """Scheduled job: emit one random ambient alert."""
        alert = ambient_alert()
        logger.debug("Ambient alert: %s [%s]", alert.metric, alert.service)
        self._emit(alert)

    def trigger(self, tag: str) -> list[Alert]:
        """
        Manually trigger a named scenario burst (A–E).
        Alerts are emitted with small inter-alert delays to simulate realism.
        Returns the list of alerts that were emitted.
        """
        alerts = trigger_scenario(tag)
        logger.info(
            "Scenario %s triggered — emitting %d alerts", tag.upper(), len(alerts)
        )

        def _burst():
            for i, alert in enumerate(alerts):
                self._emit(alert)
                if i < len(alerts) - 1:
                    time.sleep(0.8)  # 800ms between burst alerts

        threading.Thread(target=_burst, daemon=True, name=f"burst-{tag}").start()
        return alerts

    # ── Consumption ────────────────────────────────────────────────────────

    def drain(self, max_items: int = 256) -> list[Alert]:
        """
        Non-blocking drain: return up to `max_items` alerts currently in queue.
        Suitable for Streamlit polling loops.
        """
        items: list[Alert] = []
        while len(items) < max_items:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    def get_blocking(self, timeout: float = 5.0) -> Optional[Alert]:
        """Blocking get with timeout. Returns None on timeout."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── Stats ──────────────────────────────────────────────────────────────

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def total_emitted(self) -> int:
        return self._total_emitted

    @property
    def is_running(self) -> bool:
        return self._started


# ── Module-level singleton ─────────────────────────────────────────────────
# Shared across the app via Streamlit session state initialisation in ui/app.py.
# Do NOT import at module level from UI pages — use st.session_state["stream"].

def create_stream() -> AlertStream:
    """Factory that creates and starts a fresh AlertStream."""
    stream = AlertStream()
    stream.start()
    return stream
