"""
MavFix Genesis — Page 1: Live Alert Stream
Enterprise Datadog/Grafana Grade (Zero Emojis, Strict Proper/Uppercase).
Real-time scrolling alert stream with scenario trigger buttons.
Non-blocking streaming via st.fragment (zero thread freezing).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="LIVE ALERT STREAM · MAVFIX GENESIS", layout="wide")

from config.settings import settings
from ui.components.alert_card import render_alert_card, render_page_header, render_empty_state

# Inject CSS
css_path = Path(__file__).parents[1] / "style.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text('utf-8')}</style>", unsafe_allow_html=True)

# ── Bootstrap manager ──────────────────────────────────────────────
if "manager" not in st.session_state:
    from core.incident_manager import IncidentManager
    mgr = IncidentManager(enable_llm=True, enable_remediation=True)
    mgr.start()
    st.session_state["manager"] = mgr

manager = st.session_state["manager"]

# ── Header ─────────────────────────────────────────────────────────
render_page_header(
    "LIVE",
    "LIVE ALERT STREAM",
    "REAL-TIME SYNTHETIC ALERT TELEMETRY · TRIGGER SCENARIOS TO SIMULATE INCIDENT BURSTS",
)

# ── Scenario trigger panel ─────────────────────────────────────────
st.markdown(
    '<div style="font-size:0.72rem;color:#6E7681;text-transform:uppercase;'
    'letter-spacing:0.08em;margin-bottom:0.6rem;font-family:\'JetBrains Mono\',monospace">'
    'CHAOS SCENARIO INJECTION</div>',
    unsafe_allow_html=True,
)

SCENARIOS = {
    "A": "SCN-A: DB OVERLOAD",
    "B": "SCN-B: MEMORY LEAK",
    "C": "SCN-C: NET PARTITION",
    "D": "SCN-D: DISK SATURATION",
    "E": "SCN-E: DEPLOY FAILURE",
}

cols = st.columns(len(SCENARIOS))
for col, (tag, label) in zip(cols, SCENARIOS.items()):
    with col:
        if st.button(
            label,
            key=f"trigger_{tag}",
            help=f"Execute Scenario {tag}",
            use_container_width=True,
        ):
            alerts = manager.trigger(tag)
            st.toast(f"[PIPELINE ACTIVE] Scenario {tag} triggered — {len(alerts)} alerts ingested.")

st.divider()

# ── Controls row ───────────────────────────────────────────────────
ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([2, 2, 4, 2])
with ctrl1:
    limit = st.selectbox("SHOW LAST", [25, 50, 100, 200], index=1, key="feed_limit")
with ctrl2:
    sev_filter = st.selectbox(
        "SEVERITY", ["ALL", "P1", "P2", "P3", "P4"], index=0, key="feed_sev"
    )
with ctrl3:
    svc_search = st.text_input("FILTER SERVICE", placeholder="e.g. postgres", key="feed_svc")
with ctrl4:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if st.button("REFRESH STREAM", key="feed_manual_refresh", use_container_width=True):
        st.rerun()


# ── Live streaming fragment (auto-polls every 3s non-blockingly) ───
@st.fragment(run_every=3)
def render_live_feed_fragment() -> None:
    try:
        alerts = manager.recent_alerts(limit=int(limit))
    except Exception:
        alerts = []

    # Apply filters
    if sev_filter != "ALL":
        alerts = [a for a in alerts if a.severity.value == sev_filter]
    if svc_search.strip():
        alerts = [a for a in alerts if svc_search.lower() in a.service.lower()]

    # Live counter
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("SHOWING", len(alerts))
    col_b.metric("TOTAL EMITTED", getattr(manager, "total_alerts", len(alerts)))
    col_c.metric("QUEUE DEPTH", len(alerts))

    st.markdown("<br>", unsafe_allow_html=True)

    if not alerts:
        render_empty_state("STREAM", "NO ALERTS RECORDED", "Trigger a chaos scenario above or wait for ambient telemetry.")
    else:
        st.markdown(
            """
            <div style="
                display:flex;align-items:center;gap:12px;
                padding:0.4rem 0.85rem;
                background:#0D1117;
                border:1px solid #21262D;
                border-radius:4px 4px 0 0;
                font-size:0.68rem;
                color:#6E7681;
                font-family:'JetBrains Mono',monospace;
                text-transform:uppercase;
                letter-spacing:0.08em;
                margin-bottom:2px;
            ">
              <span style="min-width:26px">SEV</span>
              <span style="min-width:65px">TIME</span>
              <span style="min-width:130px">SERVICE</span>
              <span style="min-width:130px">METRIC</span>
              <span style="min-width:85px">VALUE</span>
              <span style="flex:1">MESSAGE</span>
              <span style="min-width:38px;text-align:right">AGE</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for alert in alerts:
            render_alert_card(alert, compact=True)


render_live_feed_fragment()
