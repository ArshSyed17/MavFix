"""
MavFix Genesis — Page 5: Executive Analytics
Enterprise Datadog/Grafana Grade (Zero Emojis, Strict Proper/Uppercase).
MTTD/MTTR charts, scenario frequency, remediation success rate — all via Plotly.
Resilient chart rendering and safe data frame processing.
Non-blocking: all chart computation is wrapped in @st.fragment with run_every.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from ui.components.alert_card import render_page_header, render_empty_state

css_path = Path(__file__).parents[1] / "style.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text('utf-8')}</style>", unsafe_allow_html=True)

# ── Session state bootstrap ────────────────────────────────────────
if "manager" not in st.session_state:
    from core.incident_manager import IncidentManager
    mgr = IncidentManager(enable_llm=True, enable_remediation=True)
    mgr.start()
    st.session_state["manager"] = mgr

manager = st.session_state["manager"]

render_page_header("SYS", "EXECUTIVE ANALYTICS", "MTTD, MTTR, SCENARIO BREAKDOWN, AND REMEDIATION METRICS")

# ── Plotly enterprise dark theme ───────────────────────────────────
DARK_LAYOUT = dict(
    paper_bgcolor="#0B0E14",
    plot_bgcolor="#161B22",
    font=dict(family="Inter, sans-serif", color="#8B949E", size=11),
    title_font=dict(family="JetBrains Mono, monospace", color="#F0F6FC", size=13),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#30363D", font=dict(size=10)),
    margin=dict(l=40, r=20, t=45, b=40),
    colorway=["#00E676", "#58A6FF", "#BC8CFF", "#FFB300", "#FF5252", "#E3B341"],
    xaxis=dict(gridcolor="#21262D", linecolor="#30363D"),
    yaxis=dict(gridcolor="#21262D", linecolor="#30363D"),
)


def _apply_dark(fig: go.Figure) -> go.Figure:
    fig.update_layout(**DARK_LAYOUT)
    return fig


def _display_chart(fig: go.Figure) -> None:
    try:
        st.plotly_chart(_apply_dark(fig), use_container_width=True)
    except Exception as e:
        st.error(f"Chart error: {e}")


# ─────────────────────────────────────────────────────────────────
# ALL DATA FETCHING AND CHART RENDERING IS INSIDE @st.fragment
# This prevents the page from blocking/hanging on navigation.
# The fragment auto-refreshes every 30s in the background.
# ─────────────────────────────────────────────────────────────────
@st.fragment(run_every=30)
def _render_analytics() -> None:
    # ── Collect data safely ────────────────────────────────────────
    try:
        incidents = manager.incidents()
    except Exception:
        incidents = []

    try:
        recent_alerts = manager.recent_alerts(200)  # 200 is sufficient; 500 was slow
    except Exception:
        recent_alerts = []

    # ── Summary KPIs ───────────────────────────────────────────────
    resolved = [i for i in incidents if getattr(i, "resolved_at", None)]
    mttd_vals: list[float] = []
    mttr_vals: list[float] = []

    for inc in resolved:
        try:
            if inc.alerts:
                first_alert_ts = min(a.timestamp for a in inc.alerts)
                mttd = (inc.opened_at - first_alert_ts).total_seconds()
                mttd_vals.append(max(0.0, mttd))
            mttr_vals.append(float(inc.duration_sec))
        except Exception:
            pass

    avg_mttd = sum(mttd_vals) / len(mttd_vals) if mttd_vals else 0.0
    avg_mttr = sum(mttr_vals) / len(mttr_vals) if mttr_vals else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AVG MTTD", f"{avg_mttd:.0f}S" if avg_mttd else "\u2014")
    c2.metric("AVG MTTR", f"{avg_mttr:.0f}S" if avg_mttr else "\u2014")
    c3.metric("INCIDENTS RESOLVED", len(resolved))

    all_steps = [
        s for inc in incidents if inc.rca
        for s in inc.rca.remediation_steps
    ]
    executed = [s for s in all_steps if s.status == "executed"]
    success_rate = (len(executed) / len(all_steps) * 100) if all_steps else 0
    c4.metric("REMEDIATION SUCCESS", f"{success_rate:.0f}%")

    st.divider()

    # ── Row 1: Alert volume timeline + Scenario breakdown ──────────
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("##### ALERT VOLUME OVER TIME")
        if recent_alerts:
            try:
                rows = [
                    {
                        "timestamp": a.timestamp,
                        "severity": a.severity.value,
                        "scenario": a.scenario_tag or "Ambient",
                    }
                    for a in recent_alerts
                ]
                alert_df = pd.DataFrame(rows)
                alert_df["timestamp"] = pd.to_datetime(alert_df["timestamp"], utc=True)
                alert_df["minute"] = alert_df["timestamp"].dt.floor("1min")
                vol_df = (
                    alert_df.groupby(["minute", "severity"])
                    .size()
                    .reset_index(name="count")
                )
                SEV_COLORS = {"P1": "#FF5252", "P2": "#FFB300", "P3": "#F0883E", "P4": "#8B949E"}
                fig_vol = px.area(
                    vol_df, x="minute", y="count", color="severity",
                    color_discrete_map=SEV_COLORS,
                    title="ALERTS PER MINUTE BY SEVERITY",
                )
                fig_vol.update_traces(line_width=1.5)
                _display_chart(fig_vol)
            except Exception:
                render_empty_state("DATA", "TIMELINE PENDING", "More telemetry events required")
        else:
            render_empty_state("STREAM", "NO ALERT TELEMETRY AVAILABLE", "Trigger scenarios to populate timeline")

    with col_right:
        st.markdown("##### SCENARIO DISTRIBUTION")
        if recent_alerts:
            try:
                scenario_counts: dict[str, int] = {}
                for a in recent_alerts:
                    tag = a.scenario_tag or "Ambient"
                    label = settings.SCENARIO_LABELS.get(tag, tag) if tag != "Ambient" else "Ambient"
                    scenario_counts[label] = scenario_counts.get(label, 0) + 1

                sc_df = pd.DataFrame(list(scenario_counts.items()), columns=["Scenario", "Alerts"])
                fig_pie = px.pie(
                    sc_df, names="Scenario", values="Alerts",
                    title="ALERT DISTRIBUTION BY SCENARIO",
                    hole=0.55,
                )
                fig_pie.update_traces(textposition="outside", textfont_size=11)
                _display_chart(fig_pie)
            except Exception:
                render_empty_state("DIST", "DISTRIBUTION PENDING", "Waiting for multi-scenario event clusters")
        else:
            render_empty_state("DIST", "NO SCENARIO DATA YET", "Run a scenario to view alert breakdown")

    st.divider()

    # ── Row 2: Remediation tier breakdown + Incident severity ──────
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("##### REMEDIATION ACTION BREAKDOWN")
        if all_steps:
            try:
                tier_status: dict[str, int] = {}
                for s in all_steps:
                    key = f"{s.tier or 'unknown'}/{s.status}"
                    tier_status[key] = tier_status.get(key, 0) + 1

                ts_df = pd.DataFrame(
                    [(k.split("/")[0].upper(), k.split("/")[1].upper(), v) for k, v in tier_status.items()],
                    columns=["tier", "status", "count"],
                )
                TIER_COLORS = {"AUTO": "#00E676", "APPROVAL": "#FFB300", "BLOCKED": "#FF5252", "UNKNOWN": "#8B949E"}
                fig_bar = px.bar(
                    ts_df, x="tier", y="count", color="tier",
                    color_discrete_map=TIER_COLORS,
                    barmode="group", text_auto=True,
                    title="REMEDIATION STEPS BY TIER",
                )
                _display_chart(fig_bar)
            except Exception:
                render_empty_state("REMED", "REMEDIATION METRICS PENDING", "Waiting for executed actions")
        else:
            render_empty_state("REMED", "NO REMEDIATION ACTIONS RECORDED", "Actions execute when incidents are opened")

    with col_b:
        st.markdown("##### INCIDENT SEVERITY DISTRIBUTION")
        if incidents:
            try:
                sev_counts: dict[str, int] = {}
                for inc in incidents:
                    sev_counts[inc.severity.value] = sev_counts.get(inc.severity.value, 0) + 1

                sev_df = pd.DataFrame(list(sev_counts.items()), columns=["Severity", "Count"])
                SEV_COLORS_2 = {"P1": "#FF5252", "P2": "#FFB300", "P3": "#F0883E", "P4": "#8B949E"}
                fig_sev = px.bar(
                    sev_df, x="Severity", y="Count",
                    color="Severity", color_discrete_map=SEV_COLORS_2,
                    text_auto=True, title="INCIDENTS BY SEVERITY",
                )
                _display_chart(fig_sev)
            except Exception:
                render_empty_state("INC", "SEVERITY DATA PENDING", "Waiting for incident correlation")
        else:
            render_empty_state("INC", "NO INCIDENTS REGISTERED", "Incidents populate when alert thresholds trigger")

    st.divider()

    # ── Row 3: MTTR by scenario ────────────────────────────────────
    st.markdown("##### MEAN TIME TO RESOLVE (MTTR) BY SCENARIO")
    if resolved:
        try:
            mttr_rows = []
            for inc in resolved:
                mttr_rows.append({
                    "incident": inc.name,
                    "scenario": settings.SCENARIO_LABELS.get(inc.scenario_tag, inc.scenario_tag or "Ambient"),
                    "mttr_min": inc.duration_sec / 60,
                    "severity": inc.severity.value,
                })
            mttr_df = pd.DataFrame(mttr_rows)
            fig_mttr = px.scatter(
                mttr_df, x="incident", y="mttr_min",
                color="scenario", size=[12] * len(mttr_df),
                symbol="severity",
                title="MTTR PER INCIDENT (MINUTES)",
                labels={"mttr_min": "Minutes", "incident": "Incident"},
            )
            mean_val = float(mttr_df["mttr_min"].mean())
            fig_mttr.add_hline(
                y=mean_val,
                line_dash="dash",
                line_color="#58A6FF",
                annotation_text=f"AVG {mean_val:.1f}M",
                annotation_position="top right",
                annotation_font_color="#58A6FF",
            )
            _display_chart(fig_mttr)
        except Exception:
            render_empty_state("MTTR", "MTTR CALCULATION PENDING", "Resolved incident history required")
    else:
        render_empty_state("MTTR", "NO RESOLVED INCIDENTS RECORDED", "MTTR scatter plot generates once incidents reach [RESOLVED]")

    # ── RCA Confidence distribution ────────────────────────────────
    rca_confs = [i.rca.confidence for i in incidents if i.rca]
    if rca_confs:
        st.divider()
        st.markdown("##### ROOT CAUSE ANALYSIS CONFIDENCE DISTRIBUTION")
        try:
            conf_df = pd.DataFrame({"confidence": rca_confs})
            fig_hist = px.histogram(
                conf_df, x="confidence", nbins=10,
                title="DISTRIBUTION OF RCA CONFIDENCE SCORES",
                color_discrete_sequence=["#00E676"],
            )
            avg_conf = sum(rca_confs) / len(rca_confs)
            fig_hist.add_vline(
                x=avg_conf,
                line_dash="dash", line_color="#58A6FF",
                annotation_text=f"AVG {avg_conf:.2f}",
                annotation_font_color="#58A6FF",
            )
            _display_chart(fig_hist)
        except Exception:
            render_empty_state("CONF", "CONFIDENCE CALCULATION PENDING", "RCA scoring in progress")

    # ── Footer ─────────────────────────────────────────────────────
    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    st.markdown(
        f"<div style='text-align:right;color:#6E7681;font-size:0.72rem;"
        f"font-family:JetBrains Mono,monospace;margin-top:1rem'>"
        f"LAST REFRESHED: {now_str} \u00b7 AUTO-REFRESH EVERY 30S</div>",
        unsafe_allow_html=True,
    )


# Invoke the non-blocking fragment
_render_analytics()
