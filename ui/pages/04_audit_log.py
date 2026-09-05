"""
MavFix Genesis — Page 4: System Audit Log
Enterprise Datadog/Grafana Grade (Zero Emojis, Strict Proper/Uppercase).
Chronological history of all system events — filterable, exportable to CSV.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="SYSTEM AUDIT LOG · MAVFIX GENESIS", layout="wide")

from config.settings import settings
from ui.components.alert_card import render_page_header, render_empty_state

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
    "AUDIT",
    "SYSTEM AUDIT LOG",
    "IMMUTABLE CHRONOLOGICAL AUDIT TRAIL OF TELEMETRY, AI DECISIONS, AND HUMAN APPROVALS",
)

# ── Source toggle ──────────────────────────────────────────────────
source = st.radio(
    "DATA SOURCE",
    ["IN-MEMORY (LIVE STREAM)", "SQLITE (PERSISTED DATABASE)"],
    horizontal=True,
    key="audit_source",
)

# ── Fetch data ─────────────────────────────────────────────────────
rows: list[dict] = []

if source == "IN-MEMORY (LIVE STREAM)":
    rows = manager.audit_log(limit=500)
else:
    try:
        from audit_logs import db
        alert_rows = db.get_recent_alerts(200)
        for r in alert_rows:
            rows.append({
                "timestamp": r["timestamp"],
                "event":     "alert_received",
                "actor":     "simulator",
                "service":   r["service"],
                "severity":  r["severity"],
                "metric":    r["metric"],
                "detail":    r["message"],
            })

        action_rows = db.get_remediation_actions(limit=200)
        for r in action_rows:
            rows.append({
                "timestamp": r["created_at"],
                "event":     f"remediation_{r['status']}",
                "actor":     r["actor"] or "system",
                "incident":  r["incident_name"],
                "command":   r["command"],
                "tier":      r["tier"],
                "detail":    r["result_message"] or "",
            })

        rows.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    except Exception as e:
        st.warning(f"SQLITE UNAVAILABLE: {e} — SHOWING IN-MEMORY LOG.")
        rows = manager.audit_log(limit=500)

# ── Filters ────────────────────────────────────────────────────────
if rows:
    df = pd.DataFrame(rows)

    col1, col2, col3 = st.columns(3)
    with col1:
        all_events = ["ALL"] + sorted([str(x).upper() for x in df["event"].dropna().unique().tolist()])
        evt_filter = st.selectbox("EVENT TYPE", all_events, key="audit_event")
    with col2:
        actors_raw = [str(x).upper() for x in df["actor"].dropna().unique().tolist()] if "actor" in df.columns else []
        all_actors = ["ALL"] + sorted(actors_raw)
        actor_filter = st.selectbox("ACTOR", all_actors, key="audit_actor")
    with col3:
        search = st.text_input("SEARCH", placeholder="incident name, command…", key="audit_search")

    # Apply filters
    if evt_filter != "ALL":
        df = df[df["event"].str.upper() == evt_filter]
    if actor_filter != "ALL" and "actor" in df.columns:
        df = df[df["actor"].str.upper() == actor_filter]
    if search.strip():
        mask = df.apply(lambda row: search.lower() in str(row).lower(), axis=1)
        df = df[mask]

    st.markdown(
        f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.75rem;color:#8B949E;margin:6px 0'>"
        f"FILTERED: <strong>{len(df):,}</strong> AUDIT EVENTS</div>",
        unsafe_allow_html=True,
    )

    EVENT_COLORS = {
        "alert_received":    "#8B949E",
        "incident_opened":   "#58A6FF",
        "rca_complete":      "#BC8CFF",
        "remediation_step":  "#00E676",
        "incident_resolved": "#00E676",
        "remediation_auto":  "#00E676",
        "remediation_blocked":"#FF5252",
    }

    def _style_event(val: str) -> str:
        color = EVENT_COLORS.get(str(val).lower(), "#8B949E")
        return f"color:{color};font-weight:600;font-family:'JetBrains Mono',monospace;font-size:0.75rem"

    display_cols = [c for c in ["timestamp", "event", "actor", "incident", "command",
                                "tier", "service", "severity", "metric", "detail"] if c in df.columns]
    display_df = df[display_cols].head(300)

    # Backwards/forwards compatible Styler
    styler = display_df.style
    subset = ["event"] if "event" in display_df.columns else []
    if hasattr(styler, "map"):
        styled_df = styler.map(_style_event, subset=subset)
    elif hasattr(styler, "applymap"):
        styled_df = styler.applymap(_style_event, subset=subset)
    else:
        styled_df = styler

    st.dataframe(
        styled_df,
        use_container_width=True,
        height=480,
    )

    # ── Export ─────────────────────────────────────────────────────
    csv = display_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="EXPORT AS CSV",
        data=csv,
        file_name=f"mavfix_audit_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key="audit_export",
    )

else:
    render_empty_state(
        "AUDIT",
        "NO AUDIT EVENTS RECORDED",
        "Trigger a chaos scenario and await incident processing to populate audit records",
    )
