"""
MavFix Genesis — Global Settings
All configuration is driven from environment variables (see .env.example).
Import `settings` from this module anywhere in the project.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env from project root (two levels up from config/)
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


class MavFixSettings(BaseSettings):
    """Centralised, validated settings for MavFix Genesis."""

    model_config = SettingsConfigDict(
        env_prefix="MAVFIX_",
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────────
    llm_model: str = Field(
        default="claude-3-5-haiku-20241022",
        description="Anthropic model ID used for root-cause analysis.",
    )
    llm_max_tokens: int = Field(
        default=1024,
        description="Maximum tokens returned by the LLM per RCA call.",
    )
    anthropic_api_key: str = Field(
        default="",
        alias="ANTHROPIC_API_KEY",
        description="Anthropic API key (set via ANTHROPIC_API_KEY env var).",
    )
    gemini_api_key: str = Field(
        default="",
        alias="GEMINI_API_KEY",
        description="Google Gemini API key (set via GEMINI_API_KEY env var).",
    )
    gemini_model: str = Field(
        default="gemini-flash-lite-latest",
        description="Gemini model ID used for root-cause analysis and post-mortems.",
    )

    # ── Remediation ───────────────────────────────────────────────
    live_mode: bool = Field(
        default=False,
        description=(
            "When True, remediation actions execute real subprocess/Docker commands. "
            "When False (default), actions are simulated and logged only."
        ),
    )

    # ── Database ─────────────────────────────────────────────────
    db_path: str = Field(
        default="audit_logs/mavfix.db",
        description="Path to the SQLite audit database (relative to project root).",
    )

    @property
    def db_abs_path(self) -> Path:
        """Absolute path to the SQLite database file."""
        p = Path(self.db_path)
        return p if p.is_absolute() else _ROOT / p

    # ── Allow-List ────────────────────────────────────────────────
    allow_list_path: str = Field(
        default="config/allow_list.yaml",
        description="Path to the remediation allow-list YAML.",
    )

    @property
    def allow_list_abs_path(self) -> Path:
        p = Path(self.allow_list_path)
        return p if p.is_absolute() else _ROOT / p

    # ── Simulator ─────────────────────────────────────────────────
    ambient_interval_sec: int = Field(
        default=8,
        description="Seconds between background ambient alert ticks.",
    )

    # ── Incident Clustering ───────────────────────────────────────
    cluster_window_sec: int = Field(
        default=300,
        description="Sliding time window (seconds) for alert clustering.",
    )
    cluster_min_alerts: int = Field(
        default=2,
        description="Minimum alert count to promote a cluster to a named incident.",
    )
    cluster_similarity_threshold: float = Field(
        default=0.35,
        description="Cosine-similarity threshold for message-based alert grouping.",
    )

    # ── UI ────────────────────────────────────────────────────────
    ui_refresh_sec: int = Field(
        default=3,
        description="Streamlit live-feed polling interval in seconds.",
    )

    # ── Internal constants (not env-overridable) ──────────────────
    project_root: Path = Field(default=_ROOT, exclude=True)

    # Severity → numeric priority (lower = more severe)
    SEVERITY_ORDER: dict[str, int] = Field(
        default={"P1": 1, "P2": 2, "P3": 3, "P4": 4},
        exclude=True,
    )

    # Severity → Streamlit-safe colour hex
    SEVERITY_COLORS: dict[str, str] = Field(
        default={
            "P1": "#ff4757",   # vivid red
            "P2": "#ffa502",   # amber
            "P3": "#eccc68",   # yellow
            "P4": "#747d8c",   # muted grey
        },
        exclude=True,
    )

    # Risk tier → colour
    RISK_COLORS: dict[str, str] = Field(
        default={
            "low":    "#00ff88",  # neon green
            "medium": "#ffa502",  # amber
            "high":   "#ff4757",  # red
        },
        exclude=True,
    )

    # Scenario tag → display name
    SCENARIO_LABELS: dict[str, str] = Field(
        default={
            "A": "Database Overload",
            "B": "Memory Leak Cascade",
            "C": "Network Partition",
            "D": "Disk I/O Saturation",
            "E": "Deployment Failure",
        },
        exclude=True,
    )


# ── Singleton ─────────────────────────────────────────────────────
settings = MavFixSettings()
