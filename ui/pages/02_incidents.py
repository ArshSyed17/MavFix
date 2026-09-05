"""
MavFix Genesis — Page 2: Active Incidents
Enterprise Datadog/Grafana Grade (Zero Emojis, Strict Proper/Uppercase).
Incident cards with LLM root-cause analysis, confidence, and remediation steps.
Non-blocking streaming via st.fragment (zero thread freezing).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="ACTIVE INCIDENTS · MAVFIX GENESIS", layout="wide")

from config.settings import settings
from ui.components.alert_card import render_page_header, render_empty_state
from ui.components.incident_panel import render_incident_card

css_path = Path(__file__).parents[1] / "style.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text('utf-8')}</style>", unsafe_allow_html=True)

if "manager" not in st.session_state:
    from core.incident_manager import IncidentManager
    mgr = IncidentManager(enable_llm=True, enable_remediation=True)
    mgr.start()
    st.session_state["manager"] = mgr

manager = st.session_state["manager"]

render_page_header(
    "INC",
    "ACTIVE INCIDENTS",
    "CLUSTERED INCIDENTS WITH LLM ROOT-CAUSE ANALYSIS, HEALTH PROBES, AND REMEDIATION PLANS",
)

# ── Filter controls ────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns([2, 2, 4, 2])
with col1:
    status_filter = st.selectbox(
        "STATUS", ["ALL", "OPEN", "INVESTIGATING", "REMEDIATING", "VERIFYING", "RESOLVED", "ESCALATED"],
        index=0, key="inc_status"
    )
with col2:
    sev_filter = st.selectbox(
        "SEVERITY", ["ALL", "P1", "P2", "P3", "P4"], index=0, key="inc_sev"
    )
with col3:
    scenario_filter = st.selectbox(
        "SCENARIO", ["ALL", "A", "B", "C", "D", "E", "AMBIENT"], index=0, key="inc_scenario"
    )
with col4:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if st.button("REFRESH INCIDENTS", key="inc_manual_refresh", use_container_width=True):
        st.rerun()


# ── Fragment for non-blocking auto-refresh ─────────────────────────
@st.fragment(run_every=4)
def render_incidents_fragment() -> None:
    try:
        all_incidents = manager.incidents()
    except Exception:
        all_incidents = []

    if status_filter != "ALL":
        all_incidents = [i for i in all_incidents if i.status.value.upper() == status_filter]
    if sev_filter != "ALL":
        all_incidents = [i for i in all_incidents if i.severity.value == sev_filter]
    if scenario_filter == "AMBIENT":
        all_incidents = [i for i in all_incidents if not i.scenario_tag]
    elif scenario_filter != "ALL":
        all_incidents = [i for i in all_incidents if i.scenario_tag == scenario_filter]

    # ── Summary metrics ────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("TOTAL INCIDENTS", len(all_incidents))
    c2.metric("OPEN / ACTIVE", sum(1 for i in all_incidents if i.is_active))
    c3.metric("WITH RCA", sum(1 for i in all_incidents if i.rca))
    c4.metric("RESOLVED", sum(1 for i in all_incidents if not i.is_active))

    st.divider()

    # ── Incident list ──────────────────────────────────────────────────
    if not all_incidents:
        render_empty_state(
            "EMPTY",
            "NO INCIDENTS MATCH ACTIVE FILTERS",
            "Trigger a scenario from the Scenario Workbench or Live Alert Stream",
        )
    else:
        for incident in all_incidents:
            auto_expand = incident.severity.value == "P1" and incident.is_active
            render_incident_card(incident, expanded=auto_expand)


render_incidents_fragment()
