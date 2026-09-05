"""
MavFix Genesis — Enterprise SRE Command Center Entry Point
Run with: streamlit run ui/app.py

Initialises the shared IncidentManager in session_state so all
multi-page views share a single pipeline instance.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

# ── Path bootstrap (allow `from core import …` etc.) ──────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ── Page config (must be first Streamlit call) ─────────────────────
st.set_page_config(
    page_title="MAVFIX GENESIS · SRE COPILOT",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "MavFix Genesis — Enterprise SRE Copilot powered by Gemini & Claude",
    },
)

from config.settings import settings
from ui.components.alert_card import render_page_header, render_kpi_row

# ── Inject global CSS ──────────────────────────────────────────────
def _inject_css() -> None:
    css_path = Path(__file__).parent / "style.css"
    if css_path.exists():
        css = css_path.read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

_inject_css()


# ── Session-state bootstrap ────────────────────────────────────────
def init_session_state() -> None:
    """Initialize shared state across all dashboard pages."""
    if "manager" not in st.session_state:
        from core.incident_manager import IncidentManager
        from config.settings import settings

        has_key = bool(settings.anthropic_api_key and
                       not settings.anthropic_api_key.startswith("sk-ant-your") and
                       not settings.anthropic_api_key.startswith("dummy"))

        mgr = IncidentManager(enable_llm=True, enable_remediation=True)
        mgr.start()
        st.session_state["manager"] = mgr
        st.session_state["llm_ready"] = has_key
        st.session_state["alerts_snapshot"] = []
    
    if "live_stream_active" not in st.session_state:
        st.session_state["live_stream_active"] = True

init_session_state()
manager = st.session_state["manager"]


# ── Sidebar ────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            MAVFIX GENESIS
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='font-size:0.75rem;color:#8B949E;margin-top:4px;letter-spacing:0.04em;text-transform:uppercase'>"
        "AUTONOMOUS SRE COPILOT</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    # Live status indicator
    col1, col2 = st.columns(2)
    with col1:
        st.metric("TOTAL ALERTS", manager.total_alerts)
    with col2:
        active = len(manager.active_incidents())
        st.metric("ACTIVE INCIDENTS", active, delta=None)

    st.markdown("---")

    # LLM status
    has_gemini = bool(settings.gemini_api_key and not settings.gemini_api_key.startswith("your-gemini"))
    has_claude = bool(settings.anthropic_api_key and not settings.anthropic_api_key.startswith("sk-ant-your"))

    if has_gemini:
        st.markdown(
            '<div style="font-size:0.75rem;font-family:\'JetBrains Mono\',monospace">'
            '<span class="live-dot" style="background:#00E676;box-shadow:0 0 8px #00E676"></span> '
            '<strong>GEMINI SRE COPILOT</strong> · ONLINE</div>',
            unsafe_allow_html=True,
        )
        st.caption(f"MODEL: `{settings.gemini_model}`")
    elif has_claude:
        st.markdown(
            '<div style="font-size:0.75rem;font-family:\'JetBrains Mono\',monospace">'
            '<span class="live-dot" style="background:#00E676;box-shadow:0 0 8px #00E676"></span> '
            '<strong>CLAUDE RCA ENGINE</strong> · ONLINE</div>',
            unsafe_allow_html=True,
        )
        st.caption(f"MODEL: `{settings.llm_model}`")
    else:
        st.markdown(
            '<div style="font-size:0.75rem;font-family:\'JetBrains Mono\',monospace">'
            '<span class="live-dot" style="background:#FFB300;box-shadow:0 0 8px #FFB300"></span> '
            '<strong>SRE COPILOT</strong> · DEMO ENGINE</div>',
            unsafe_allow_html=True,
        )
        st.caption("INTERNAL RCA ACTIVE. ADD GEMINI_API_KEY FOR CLOUD API.")

    live_mode = settings.live_mode
    if live_mode:
        st.error("LIVE_MODE ENABLED (PRODUCTION SYSTEM)")
    else:
        st.info("SIMULATED SAFETY MODE (DRY RUN)")

    st.divider()

    # Navigation hint
    st.markdown(
        """
        <div style="font-size:0.72rem;color:#6E7681;line-height:1.7;font-family:'JetBrains Mono',monospace">
        NAVIGATION:<br>
        • LIVE ALERT STREAM<br>
        • ACTIVE INCIDENTS<br>
        • REMEDIATION CONTROL<br>
        • SYSTEM AUDIT LOG<br>
        • EXECUTIVE ANALYTICS<br>
        • SCENARIO WORKBENCH
        </div>
        """,
        unsafe_allow_html=True,
    )

# ── Home splash ────────────────────────────────────────────────────
st.markdown(
    """
    <div style="text-align:left;padding:1.5rem 0 1.5rem;border-bottom:1px solid #21262D;margin-bottom:1.5rem">
      <div style="font-family:'JetBrains Mono',monospace;font-size:0.80rem;color:#58A6FF;font-weight:700;letter-spacing:0.08em;margin-bottom:0.35rem">
        ENTERPRISE OBSERVABILITY & AUTOMATED REMEDIATION
      </div>
      <h1 style="font-size:2.0rem;font-weight:800;letter-spacing:-0.03em;color:#F0F6FC;margin-bottom:0.4rem">
        MAVFIX GENESIS
      </h1>
      <p style="color:#8B949E;font-size:0.92rem;max-width:760px;margin:0;line-height:1.6">
        Autonomous SRE Copilot for real-time incident clustering, LLM root-cause analysis,
        closed-loop health verification, and semi-autonomous remediation with human-in-the-loop guardrails.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# KPI row
from audit_logs.db import get_stats
try:
    stats = get_stats()
except Exception:
    stats = {
        "total_alerts": manager.total_alerts,
        "total_incidents": len(manager.incidents()),
        "open_incidents": len(manager.active_incidents()),
        "auto_executed": 0,
        "pending_approval": 0,
    }

render_kpi_row(stats)

st.markdown("<br>", unsafe_allow_html=True)

# ── Architecture Workflow Guide ────────────────────────────────────
st.markdown(
    """
    <div class="mavfix-card" style="margin-top:1rem">
      <div style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;color:#58A6FF;font-weight:700;letter-spacing:0.08em;margin-bottom:0.5rem">
        [OPERATIONAL PIPELINE OVERVIEW]
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:16px;margin-top:10px">
        <div style="background:#0D1117;border:1px solid #21262D;border-radius:4px;padding:12px">
          <div style="color:#00E676;font-family:'JetBrains Mono',monospace;font-size:0.72rem;font-weight:700">01 / INGESTION</div>
          <div style="color:#F0F6FC;font-size:0.82rem;font-weight:600;margin:4px 0">Telemetry & Noise Stream</div>
          <div style="color:#8B949E;font-size:0.76rem">High-frequency synthetic alert stream with background ambient jitter.</div>
        </div>
        <div style="background:#0D1117;border:1px solid #21262D;border-radius:4px;padding:12px">
          <div style="color:#58A6FF;font-family:'JetBrains Mono',monospace;font-size:0.72rem;font-weight:700">02 / CORRELATION</div>
          <div style="color:#F0F6FC;font-size:0.82rem;font-weight:600;margin:4px 0">Windowed Clustering</div>
          <div style="color:#8B949E;font-size:0.76rem">Reduces 100+ cascading alerts into 1 clean Correlated Incident ticket.</div>
        </div>
        <div style="background:#0D1117;border:1px solid #21262D;border-radius:4px;padding:12px">
          <div style="color:#BC8CFF;font-family:'JetBrains Mono',monospace;font-size:0.72rem;font-weight:700">03 / REASONING</div>
          <div style="color:#F0F6FC;font-size:0.82rem;font-weight:600;margin:4px 0">LLM Root Cause Analysis</div>
          <div style="color:#8B949E;font-size:0.76rem">Gemini / Claude diagnoses root cause and prepares tiered runbook actions.</div>
        </div>
        <div style="background:#0D1117;border:1px solid #21262D;border-radius:4px;padding:12px">
          <div style="color:#FFB300;font-family:'JetBrains Mono',monospace;font-size:0.72rem;font-weight:700">04 / EXECUTION</div>
          <div style="color:#F0F6FC;font-size:0.82rem;font-weight:600;margin:4px 0">Closed-Loop Verification</div>
          <div style="color:#8B949E;font-size:0.76rem">Safe actions auto-execute; risky actions require approval + 5s health probe.</div>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style="text-align:center;color:#6E7681;font-size:0.80rem;margin-top:2rem;font-family:'JetBrains Mono',monospace">
      SELECT [SCENARIO WORKBENCH] OR [LIVE ALERT STREAM] TO INITIATE SYSTEM CHAOS SIMULATION
    </div>
    """,
    unsafe_allow_html=True,
)
