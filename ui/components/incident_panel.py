"""
MavFix Genesis — Incident Detail Panel Component
Enterprise Datadog/Grafana Grade (Zero Emojis, Strict Proper/Uppercase).
Renders a full incident card with RCA results, confidence meter,
remediation steps, and approve/reject controls.
"""

from __future__ import annotations

import streamlit as st

from config.settings import settings
from core.models import Incident, RemediationStep, RiskLevel
from ui.components.alert_card import severity_badge_html, risk_badge_html, status_html, _fmt_age, _strip_emojis


def render_incident_card(incident: Incident, expanded: bool = False) -> None:
    """
    Render an incident summary card. Clicking expands to full RCA panel.
    """
    sev_color = settings.SEVERITY_COLORS.get(incident.severity.value, "#8B949E")
    dur_str = _fmt_age(incident.duration_sec)

    header_html = f"""
    <div style="display:flex;align-items:center;justify-content:space-between">
      <div style="display:flex;align-items:center;gap:10px">
        {severity_badge_html(incident.severity.value)}
        <span style="font-weight:700;color:#F0F6FC;font-size:1rem;letter-spacing:0.02em">{incident.name}</span>
        {f'<span style="background:#21262D;color:#58A6FF;border:1px solid #30363D;border-radius:3px;padding:2px 6px;font-size:0.68rem;font-weight:600;font-family:\'JetBrains Mono\',monospace">SCN-{incident.scenario_tag}</span>' if incident.scenario_tag else ""}
      </div>
      <div style="display:flex;align-items:center;gap:12px">
        {status_html(incident.status.value)}
        <span style="color:#6E7681;font-size:0.75rem;font-family:'JetBrains Mono',monospace">{dur_str}</span>
      </div>
    </div>
    <div style="margin-top:8px;color:#8B949E;font-size:0.80rem;font-family:'JetBrains Mono',monospace">
      SERVICES: {', '.join(incident.services[:4])}{' +MORE' if len(incident.services) > 4 else ''}
      &nbsp;·&nbsp; ALERTS: {incident.alert_count}
    </div>
    """

    with st.expander(
        label=f"{incident.severity.value} · {incident.name} · [{incident.status.value.upper()}]",
        expanded=expanded,
    ):
        st.markdown(header_html, unsafe_allow_html=True)
        tabs = st.tabs(["RCA & REMEDIATION", "POST-MORTEM REPORT", "ALERT TIMELINE"])
        with tabs[0]:
            if incident.rca:
                _render_rca(incident)
            else:
                st.markdown(
                    '<div style="color:#8B949E;font-size:0.85rem;padding:1rem 0;font-family:\'JetBrains Mono\',monospace">'
                    '[STATUS: ROOT-CAUSE ANALYSIS IN PROGRESS...]</div>',
                    unsafe_allow_html=True,
                )
        with tabs[1]:
            _render_post_mortem_tab(incident)
        with tabs[2]:
            _render_alerts_tab(incident)


def _render_post_mortem_tab(incident: Incident) -> None:
    """Render the automated Markdown Post-Mortem report with download controls."""
    status_str = incident.status.value.lower()

    if status_str == "verifying":
        st.markdown(
            f"""
            <div style="background:rgba(255,179,0,0.08);border:1px solid rgba(255,179,0,0.35);
                        border-radius:4px;padding:1.1rem 1.25rem;margin:1rem 0">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
                <span style="font-weight:700;color:#FFB300;font-size:0.85rem;text-transform:uppercase;letter-spacing:0.06em">
                  [CLOSED-LOOP HEALTH VERIFICATION IN PROGRESS]
                </span>
              </div>
              <div style="color:#8B949E;font-size:0.82rem;line-height:1.6">
                Executing <code>check_service_health('{incident.primary_service or "system"}')</code>
                telemetry probe window (5 seconds).<br>
                Once health verification passes, state transitions to
                <strong style="color:#00E676">[RESOLVED]</strong> and the SRE Post-Mortem generates automatically.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    if "escalated" in status_str:
        st.markdown(
            """
            <div style="background:rgba(255,82,82,0.1);border:1px solid rgba(255,82,82,0.4);
                        border-radius:4px;padding:1.1rem 1.25rem;margin:1rem 0">
              <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
                <span style="font-weight:700;color:#FF5252;font-size:0.85rem;text-transform:uppercase;letter-spacing:0.06em">
                  [INCIDENT ESCALATED: MANUAL INTERVENTION REQUIRED]
                </span>
              </div>
              <div style="color:#8B949E;font-size:0.82rem;line-height:1.6">
                Closed-loop health verification failed to confirm service stabilization.
                Automated Post-Mortem generation is suspended pending on-call human remediation.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    if incident.post_mortem:
        st.markdown(
            """
            <div style="display:flex;align-items:center;justify-content:space-between;
                        margin:0.5rem 0 0.75rem;padding-bottom:0.5rem;border-bottom:1px solid #30363D">
              <div style="font-size:0.75rem;color:#00E676;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;font-family:'JetBrains Mono',monospace">
                [AUTOMATED POST-MORTEM GENERATED BY SRE COPILOT]
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_dl, _ = st.columns([3, 7])
        with col_dl:
            st.download_button(
                label="DOWNLOAD POST-MORTEM (.MD)",
                data=incident.post_mortem,
                file_name=f"post_mortem_{incident.name}.md",
                mime="text/markdown",
                key=f"dl_pm_{incident.id}",
                help="Download full Markdown Post-Mortem report",
            )

        # Render Markdown Report
        st.markdown(incident.post_mortem)

        # Raw Markdown viewer
        with st.expander("VIEW RAW MARKDOWN (COPYABLE)"):
            st.code(incident.post_mortem, language="markdown")
    else:
        st.info(
            "POST-MORTEM REPORT WILL AUTOMATICALLY GENERATE ONCE ALL REMEDIATION ACTIONS "
            "COMPLETE AND CLOSED-LOOP HEALTH VERIFICATION PASSES (STATUS: RESOLVED)."
        )
        if incident.status.value == "resolved" and "manager" in st.session_state:
            if st.button("GENERATE POST-MORTEM NOW", key=f"force_pm_{incident.id}"):
                with st.spinner("Generating Post-Mortem report via SRE Copilot…"):
                    st.session_state["manager"]._trigger_post_mortem(incident)
                    st.rerun()


def _render_alerts_tab(incident: Incident) -> None:
    """Render the list of correlated alerts for this incident."""
    if not incident.alerts:
        st.caption("No alerts attached to this incident.")
        return

    from ui.components.alert_card import render_alert_card
    st.markdown(
        f"<div style='font-size:0.72rem;color:#6E7681;text-transform:uppercase;"
        f"letter-spacing:0.08em;margin-bottom:8px;font-family:\'JetBrains Mono\',monospace'>CORRELATED ALERTS ({incident.alert_count})</div>",
        unsafe_allow_html=True,
    )
    for alert in incident.alerts:
        render_alert_card(alert, compact=True)


def _render_rca(incident: Incident) -> None:
    """Render the full RCA result with confidence meter and steps."""
    rca = incident.rca
    if not rca:
        return

    # ── Root cause ────────────────────────────────────────────────
    st.markdown(
        f"""
        <div class="rca-root-cause">
          <div style="font-size:0.68rem;color:#6E7681;text-transform:uppercase;
                      letter-spacing:0.08em;margin-bottom:4px;font-family:'JetBrains Mono',monospace">DIAGNOSED ROOT CAUSE</div>
          <div style="font-size:0.90rem;font-weight:500;color:#F0F6FC">{_strip_emojis(rca.root_cause)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Impact ────────────────────────────────────────────────────
    st.markdown(
        f"""
        <div class="rca-impact">
          <div style="font-size:0.68rem;color:#6E7681;text-transform:uppercase;
                      letter-spacing:0.08em;margin-bottom:4px;font-family:'JetBrains Mono',monospace">IMPACT SUMMARY</div>
          <div style="font-size:0.85rem;color:#8B949E">{_strip_emojis(rca.impact_summary)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Metadata row ──────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        conf_pct = int(rca.confidence * 100)
        conf_color = "#00E676" if conf_pct >= 70 else "#FFB300" if conf_pct >= 40 else "#FF5252"
        st.markdown(
            f"""
            <div class="kpi-tile" style="text-align:left;padding:0.75rem">
              <div class="kpi-label">CONFIDENCE</div>
              <div class="kpi-value" style="font-size:1.35rem;color:{conf_color}">{conf_pct}%</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
            <div class="kpi-tile" style="text-align:left;padding:0.75rem">
              <div class="kpi-label">RISK LEVEL</div>
              <div style="margin-top:4px">{risk_badge_html(rca.risk_level.value)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col3:
        eta = f"~{rca.estimated_resolution_min}M" if rca.estimated_resolution_min else "UNKNOWN"
        st.markdown(
            f"""
            <div class="kpi-tile" style="text-align:left;padding:0.75rem">
              <div class="kpi-label">EST. TTR</div>
              <div class="kpi-value" style="font-size:1.25rem;color:#58A6FF">{eta}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col4:
        step_count = len(rca.remediation_steps)
        auto_count = sum(1 for s in rca.remediation_steps if s.tier == "auto")
        st.markdown(
            f"""
            <div class="kpi-tile" style="text-align:left;padding:0.75rem">
              <div class="kpi-label">STEPS</div>
              <div class="kpi-value" style="font-size:1.25rem;color:#F0F6FC">
                {step_count} <span style="font-size:0.75rem;color:#00E676">({auto_count} AUTO)</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── Remediation steps ─────────────────────────────────────────
    if rca.remediation_steps:
        st.markdown(
            "<div style='margin-top:1rem;font-size:0.72rem;color:#6E7681;"
            "text-transform:uppercase;letter-spacing:0.08em;font-family:\'JetBrains Mono\',monospace'>REMEDIATION EXECUTION PLAN</div>",
            unsafe_allow_html=True,
        )
        for i, step in enumerate(rca.remediation_steps):
            _render_step_row(incident, step, i)


def _render_step_row(incident: Incident, step: RemediationStep, idx: int) -> None:
    """Render one remediation step with tier badge, status, and action buttons."""
    tier = step.tier or "unknown"
    status = step.status

    tier_colors = {
        "auto":     ("#00E676", "rgba(0,230,118,0.06)", "AUTO"),
        "approval": ("#FFB300", "rgba(255,179,0,0.06)", "APPROVAL REQUIRED"),
        "blocked":  ("#FF5252", "rgba(255,82,82,0.06)", "BLOCKED"),
        "unknown":  ("#8B949E", "rgba(139,148,158,0.06)", "UNKNOWN"),
    }
    border_color, bg_color, tier_label = tier_colors.get(tier, tier_colors["unknown"])

    st.markdown(
        f"""
        <div style="
            background:{bg_color};
            border-left:3px solid {border_color};
            border-top:1px solid #21262D;
            border-right:1px solid #21262D;
            border-bottom:1px solid #21262D;
            border-radius:0 4px 4px 0;
            padding:0.7rem 1rem;
            margin-bottom:6px;
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:12px;
        ">
          <div style="flex:1">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
              <span style="color:{border_color};font-weight:700;font-size:0.68rem;
                           font-family:'JetBrains Mono',monospace;
                           background:#21262D;padding:2px 6px;border-radius:3px">
                [{tier_label}]
              </span>
              <span style="font-weight:600;color:#F0F6FC;font-family:'JetBrains Mono',monospace;
                           font-size:0.84rem">{step.command}</span>
              <span style="font-size:0.70rem;color:#8B949E;font-family:'JetBrains Mono',monospace">[{status.upper()}]</span>
            </div>
            <div style="color:#8B949E;font-size:0.80rem;margin-bottom:4px">{_strip_emojis(step.rationale)}</div>
            {f'<div style="color:#6E7681;font-size:0.74rem;font-family:\'JetBrains Mono\',monospace">{step.params}</div>' if step.params else ""}
            {f'<div style="color:#58A6FF;font-size:0.74rem;margin-top:4px;font-family:\'JetBrains Mono\',monospace">{_strip_emojis(step.result_message or "")}</div>' if step.result_message else ""}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Approve/Reject buttons for pending_approval steps
    if status == "pending_approval" and "manager" in st.session_state:
        col_a, col_b, _ = st.columns([1.2, 1.2, 5])
        with col_a:
            st.markdown('<div class="btn-approve">', unsafe_allow_html=True)
            if st.button(
                "APPROVE",
                key=f"approve_{incident.id}_{idx}",
                help=f"Execute {step.command} now",
            ):
                ok = st.session_state["manager"].approve_step(incident.id, idx)
                if ok:
                    st.success(f"APPROVED: {step.command}")
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        with col_b:
            st.markdown('<div class="btn-danger">', unsafe_allow_html=True)
            if st.button(
                "REJECT",
                key=f"reject_{incident.id}_{idx}",
                help=f"Reject {step.command}",
            ):
                ok = st.session_state["manager"].reject_step(incident.id, idx)
                if ok:
                    st.warning(f"REJECTED: {step.command}")
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
