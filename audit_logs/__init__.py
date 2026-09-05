"""audit_logs package — MavFix Genesis SQLite persistence layer."""

from audit_logs.db import (
    get_connection,
    get_recent_alerts,
    get_incidents,
    get_remediation_actions,
    get_pending_approvals,
    get_stats,
)
from audit_logs.logger import AuditLogger

__all__ = [
    "get_connection",
    "get_recent_alerts",
    "get_incidents",
    "get_remediation_actions",
    "get_pending_approvals",
    "get_stats",
    "AuditLogger",
]
