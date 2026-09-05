"""
MavFix Genesis — SQLite Audit Database
Schema creation, connection management, and CRUD helpers for all audit tables.

Tables:
  alerts              — raw alert stream
  incidents           — clustered incidents + RCA results (JSON blob)
  remediation_actions — per-step execution records
  approval_queue      — pending human approval items

All writes use parameterised queries. The module exposes a single
`get_connection()` helper that creates the DB file and schema on first call.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

# One connection per thread (SQLite is not thread-safe by default)
_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """
    Return the per-thread SQLite connection, creating the DB file and
    initialising the schema if needed.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        db_path = settings.db_abs_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")  # better concurrent read perf
        conn.execute("PRAGMA foreign_keys=ON;")
        _initialise_schema(conn)
        _local.conn = conn
        logger.debug("SQLite connection opened: %s", db_path)
    return _local.conn


def _initialise_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't already exist."""
    conn.executescript("""
        -- ── Alerts ──────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS alerts (
            id            TEXT PRIMARY KEY,
            timestamp     TEXT NOT NULL,
            service       TEXT NOT NULL,
            severity      TEXT NOT NULL,
            metric        TEXT NOT NULL,
            value         REAL NOT NULL,
            unit          TEXT,
            message       TEXT,
            scenario_tag  TEXT,
            status        TEXT DEFAULT 'firing',
            labels_json   TEXT,
            runbook_url   TEXT,
            created_at    TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_timestamp    ON alerts(timestamp);
        CREATE INDEX IF NOT EXISTS idx_alerts_service      ON alerts(service);
        CREATE INDEX IF NOT EXISTS idx_alerts_scenario_tag ON alerts(scenario_tag);
        CREATE INDEX IF NOT EXISTS idx_alerts_severity     ON alerts(severity);

        -- ── Incidents ────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS incidents (
            id               TEXT PRIMARY KEY,
            name             TEXT NOT NULL UNIQUE,
            scenario_tag     TEXT,
            status           TEXT NOT NULL DEFAULT 'open',
            severity         TEXT NOT NULL,
            services_json    TEXT,
            alert_ids_json   TEXT,
            rca_json         TEXT,          -- full RCAResult serialised as JSON
            opened_at        TEXT NOT NULL,
            resolved_at      TEXT,
            updated_at       TEXT,
            notes_json       TEXT,
            created_at       TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_incidents_status   ON incidents(status);
        CREATE INDEX IF NOT EXISTS idx_incidents_opened   ON incidents(opened_at);
        CREATE INDEX IF NOT EXISTS idx_incidents_scenario ON incidents(scenario_tag);

        -- ── Remediation Actions ──────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS remediation_actions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id    TEXT NOT NULL REFERENCES incidents(id),
            incident_name  TEXT NOT NULL,
            command        TEXT NOT NULL,
            tier           TEXT,           -- auto | approval | blocked
            risk           TEXT,
            status         TEXT NOT NULL,  -- pending | executed | pending_approval | approved | rejected | blocked | failed
            rationale      TEXT,
            params_json    TEXT,
            result_message TEXT,
            executed_at    TEXT,
            actor          TEXT DEFAULT 'system',
            created_at     TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_actions_incident ON remediation_actions(incident_id);
        CREATE INDEX IF NOT EXISTS idx_actions_status   ON remediation_actions(status);
        CREATE INDEX IF NOT EXISTS idx_actions_tier     ON remediation_actions(tier);

        -- ── Approval Queue ───────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS approval_queue (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id    TEXT NOT NULL REFERENCES incidents(id),
            incident_name  TEXT NOT NULL,
            command        TEXT NOT NULL,
            rationale      TEXT,
            params_json    TEXT,
            risk           TEXT,
            status         TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
            requested_at   TEXT DEFAULT (datetime('now')),
            resolved_at    TEXT,
            resolved_by    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_queue_status ON approval_queue(status);
    """)
    conn.commit()
    logger.debug("SQLite schema initialised.")


# ── Generic helpers ────────────────────────────────────────────────────────

def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    conn = get_connection()
    cur  = conn.execute(sql, params)
    conn.commit()
    return cur


def fetchall(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = get_connection()
    return conn.execute(sql, params).fetchall()


def fetchone(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    conn = get_connection()
    return conn.execute(sql, params).fetchone()


# ── Domain-specific write helpers ──────────────────────────────────────────

def upsert_alert(alert_dict: dict) -> None:
    execute(
        """
        INSERT OR REPLACE INTO alerts
            (id, timestamp, service, severity, metric, value, unit,
             message, scenario_tag, status, labels_json, runbook_url)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            alert_dict["id"],
            alert_dict["timestamp"],
            alert_dict["service"],
            alert_dict["severity"],
            alert_dict["metric"],
            alert_dict["value"],
            alert_dict.get("unit", ""),
            alert_dict.get("message", ""),
            alert_dict.get("scenario_tag"),
            alert_dict.get("status", "firing"),
            json.dumps(alert_dict.get("labels", {})),
            alert_dict.get("runbook_url"),
        ),
    )


def upsert_incident(incident_dict: dict) -> None:
    execute(
        """
        INSERT OR REPLACE INTO incidents
            (id, name, scenario_tag, status, severity, services_json,
             alert_ids_json, rca_json, opened_at, resolved_at, updated_at, notes_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            incident_dict["id"],
            incident_dict["name"],
            incident_dict.get("scenario_tag"),
            incident_dict["status"],
            incident_dict["severity"],
            json.dumps(incident_dict.get("services", [])),
            json.dumps(incident_dict.get("alert_ids", [])),
            incident_dict.get("rca_json"),
            incident_dict["opened_at"],
            incident_dict.get("resolved_at"),
            incident_dict.get("updated_at"),
            json.dumps(incident_dict.get("notes", [])),
        ),
    )


def insert_remediation_action(action_dict: dict) -> int:
    cur = execute(
        """
        INSERT INTO remediation_actions
            (incident_id, incident_name, command, tier, risk, status,
             rationale, params_json, result_message, executed_at, actor)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            action_dict["incident_id"],
            action_dict["incident_name"],
            action_dict["command"],
            action_dict.get("tier"),
            action_dict.get("risk"),
            action_dict["status"],
            action_dict.get("rationale", ""),
            json.dumps(action_dict.get("params", {})),
            action_dict.get("result_message"),
            action_dict.get("executed_at"),
            action_dict.get("actor", "system"),
        ),
    )
    return cur.lastrowid


def upsert_approval_queue_item(item_dict: dict) -> int:
    # Check if entry already exists for this incident+command
    existing = fetchone(
        "SELECT id FROM approval_queue WHERE incident_id=? AND command=? AND status='pending'",
        (item_dict["incident_id"], item_dict["command"]),
    )
    if existing:
        return existing["id"]

    cur = execute(
        """
        INSERT INTO approval_queue
            (incident_id, incident_name, command, rationale, params_json, risk, status)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            item_dict["incident_id"],
            item_dict["incident_name"],
            item_dict["command"],
            item_dict.get("rationale", ""),
            json.dumps(item_dict.get("params", {})),
            item_dict.get("risk", "medium"),
            "pending",
        ),
    )
    return cur.lastrowid


def resolve_approval_queue_item(queue_id: int, status: str, resolved_by: str = "operator") -> None:
    from datetime import datetime, timezone
    execute(
        """
        UPDATE approval_queue
        SET status=?, resolved_at=?, resolved_by=?
        WHERE id=?
        """,
        (status, datetime.now(timezone.utc).isoformat(), resolved_by, queue_id),
    )


# ── Read helpers for UI ────────────────────────────────────────────────────

def get_recent_alerts(limit: int = 200) -> list[sqlite3.Row]:
    return fetchall(
        "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)
    )


def get_incidents(status_filter: Optional[str] = None, limit: int = 100) -> list[sqlite3.Row]:
    if status_filter:
        return fetchall(
            "SELECT * FROM incidents WHERE status=? ORDER BY opened_at DESC LIMIT ?",
            (status_filter, limit),
        )
    return fetchall("SELECT * FROM incidents ORDER BY opened_at DESC LIMIT ?", (limit,))


def get_remediation_actions(incident_id: Optional[str] = None, limit: int = 200) -> list[sqlite3.Row]:
    if incident_id:
        return fetchall(
            "SELECT * FROM remediation_actions WHERE incident_id=? ORDER BY created_at DESC LIMIT ?",
            (incident_id, limit),
        )
    return fetchall("SELECT * FROM remediation_actions ORDER BY created_at DESC LIMIT ?", (limit,))


def get_pending_approvals() -> list[sqlite3.Row]:
    return fetchall(
        "SELECT * FROM approval_queue WHERE status='pending' ORDER BY requested_at ASC"
    )


def get_stats() -> dict:
    """Aggregate statistics for the Analytics dashboard page."""
    total_alerts    = (fetchone("SELECT COUNT(*) as c FROM alerts") or {}).get("c", 0)
    total_incidents = (fetchone("SELECT COUNT(*) as c FROM incidents") or {}).get("c", 0)
    open_incidents  = (fetchone("SELECT COUNT(*) as c FROM incidents WHERE status != 'resolved'") or {}).get("c", 0)
    auto_executed   = (fetchone("SELECT COUNT(*) as c FROM remediation_actions WHERE tier='auto' AND status='executed'") or {}).get("c", 0)
    pending_approv  = (fetchone("SELECT COUNT(*) as c FROM approval_queue WHERE status='pending'") or {}).get("c", 0)

    return {
        "total_alerts":     total_alerts,
        "total_incidents":  total_incidents,
        "open_incidents":   open_incidents,
        "auto_executed":    auto_executed,
        "pending_approval": pending_approv,
    }
