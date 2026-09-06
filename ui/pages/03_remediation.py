"""
MavFix Genesis — Page 3: Remediation Control
Enterprise Datadog/Grafana Grade (Zero Emojis, Strict Proper/Uppercase).
Split view: auto-executed actions and pending human approvals.
Non-blocking streaming via st.fragment (zero thread freezing).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="REMEDIATION CONTROL · MAVFIX GENESIS", layout="wide")

from config.settings import settings
from core.models import Incident, RemediationStep
from ui.components.alert_card import render_page_header, render_empty_state, risk_badge_html, _strip_emojis

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
    "CTRL",
    "REMEDIATION CONTROL",
    "AUTOMATED ACTIONS AND PENDING HUMAN-IN-THE-LOOP APPROVAL GATES",
)


def _collect_steps() -> tuple[list, list, list]:
    auto_steps: list[tuple[Incident, RemediationStep, int]] = []
    pending_steps: list[tuple[Incident, RemediationStep, int]] = []
    other_steps: list[tuple[Incident, RemediationStep, int]] = []

    try:
        incidents = manager.incidents()
    except Exception:
        incidents = []

    for incident in incidents:
        if not incident.rca:
            continue
        for idx, step in enumerate(incident.rca.remediation_steps):
            entry = (incident, step, idx)
            if step.status == "pending_approval":
                pending_steps.append(entry)
            elif step.tier == "auto" and step.status in ("executed", "failed"):
                auto_steps.append(entry)
            else:
                other_steps.append(entry)

    return auto_steps, pending_steps, other_steps


@st.fragment(run_every=4)
def render_remediation_fragment() -> None:
    auto_steps, pending_steps, other_steps = _collect_steps()

    # ── Summary metrics ────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AUTO-EXECUTED", len([s for _, s, _ in auto_steps if s.status == "executed"]))
    c2.metric("PENDING APPROVAL", len(pending_steps), delta=len(pending_steps) or None)
    c3.metric("BLOCKED", len([s for _, s, _ in other_steps if s.status == "blocked"]))
    c4.metric("REJECTED", len([s for _, s, _ in other_steps if s.status == "rejected"]))

    st.divider()

    # ── Pending Approvals (AMBER) ──────────────────────────────────────
    st.markdown(
        """
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:1rem">
          <span class="badge badge-approval" style="font-size:0.75rem">GATE</span>
          <h2 style="font-size:1.05rem;font-weight:700;color:#FFB300;margin:0;letter-spacing:0.04em">
            PENDING HUMAN APPROVALS ({count})
          </h2>
        </div>
        """.format(count=len(pending_steps)),
        unsafe_allow_html=True,
    )

    if not pending_steps:
        render_empty_state("APPROVAL", "NO PENDING APPROVALS", "All high-risk actions have been actioned or queue is clear")
    else:
        for incident, step, idx in pending_steps:
            with st.container():
                col_info, col_actions = st.columns([6, 2])
                with col_info:
                    st.markdown(
                        f"""
                        <div style="background:#161B22;border:1px solid rgba(255,179,0,0.3);
                                    border-left:4px solid #FFB300;border-radius:4px;padding:1rem 1.25rem;margin-bottom:8px">
                          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                            <span style="background:#21262D;color:#FFB300;border-radius:3px;padding:2px 8px;font-size:0.68rem;
                                         font-weight:700;font-family:'JetBrains Mono',monospace">[APPROVAL REQUIRED]</span>
                            <span style="font-weight:700;color:#F0F6FC;font-family:'JetBrains Mono',monospace">{step.command}</span>
                            <span style="color:#6E7681;font-size:0.75rem">↳ {incident.name}</span>
                            {risk_badge_html(step.risk.value if step.risk else 'medium')}
                          </div>
                          <div style="color:#8B949E;font-size:0.82rem;margin-bottom:6px">{_strip_emojis(step.rationale)}</div>
                          {f'<div style="color:#6E7681;font-size:0.75rem;font-family:\'JetBrains Mono\',monospace">PARAMS: {step.params}</div>' if step.params else ''}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with col_actions:
                    st.markdown("<div style='height:0.35rem'></div>", unsafe_allow_html=True)
                    st.markdown('<div class="btn-approve">', unsafe_allow_html=True)
                    if st.button(
                        "APPROVE",
                        key=f"rem_approve_{incident.id}_{idx}",
                        width='stretch',
                    ):
                        ok = manager.approve_step(incident.id, idx)
                        if ok:
                            st.success(f"APPROVED: {step.command}")
                            st.rerun()
                    st.markdown('</div><div class="btn-danger" style="margin-top:6px">', unsafe_allow_html=True)
                    if st.button(
                        "REJECT",
                        key=f"rem_reject_{incident.id}_{idx}",
                        width='stretch',
                    ):
                        ok = manager.reject_step(incident.id, idx)
                        if ok:
                            st.warning(f"REJECTED: {step.command}")
                            st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)

    st.divider()

    # ── Auto-Executed Actions (GREEN) ──────────────────────────────────
    st.markdown(
        """
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:1rem">
          <span class="badge badge-auto" style="font-size:0.75rem">AUTO</span>
          <h2 style="font-size:1.05rem;font-weight:700;color:#00E676;margin:0;letter-spacing:0.04em">
            AUTO-EXECUTED ACTIONS ({count})
          </h2>
        </div>
        """.format(count=len(auto_steps)),
        unsafe_allow_html=True,
    )

    if not auto_steps:
        render_empty_state("AUTO", "NO AUTO-EXECUTED ACTIONS YET", "Safe tier actions automatically execute when incidents occur")
    else:
        for incident, step, idx in auto_steps[:20]:
            status_color = "#00E676" if step.status == "executed" else "#FF5252"
            st.markdown(
                f"""
                <div style="background:#161B22;border:1px solid #21262D;
                            border-left:3px solid {status_color};border-radius:0 4px 4px 0;
                            padding:0.65rem 1rem;margin-bottom:5px;display:flex;align-items:center;gap:12px">
                  <span style="color:#00E676;font-weight:700;font-family:'JetBrains Mono',monospace;
                               font-size:0.80rem;min-width:140px">{step.command}</span>
                  <span style="color:#6E7681;font-size:0.75rem;min-width:75px">{incident.name}</span>
                  <span style="color:#8B949E;font-size:0.78rem;flex:1">
                    {_strip_emojis((step.result_message or '')[:120])}
                  </span>
                  <span style="color:{status_color};font-size:0.70rem;font-weight:700;
                               font-family:'JetBrains Mono',monospace">[{step.status.upper()}]</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # ── Blocked / Other ────────────────────────────────────────────────
    blocked = [(i, s, x) for i, s, x in other_steps if s.status == "blocked"]
    if blocked:
        st.divider()
        st.markdown(
            """
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:1rem">
              <span class="badge badge-blocked" style="font-size:0.75rem">BLOCKED</span>
              <h2 style="font-size:1.05rem;font-weight:700;color:#FF5252;margin:0;letter-spacing:0.04em">
                POLICY BLOCKED COMMANDS
              </h2>
            </div>
            """,
            unsafe_allow_html=True,
        )
        for incident, step, idx in blocked:
            st.markdown(
                f"""
                <div style="background:#161B22;border:1px solid rgba(255,82,82,0.3);
                            border-left:3px solid #FF5252;border-radius:0 4px 4px 0;
                            padding:0.65rem 1rem;margin-bottom:5px">
                  <span style="color:#FF5252;font-weight:700;font-family:'JetBrains Mono',monospace;
                               font-size:0.80rem">{step.command}</span>
                  <span style="color:#6E7681;font-size:0.75rem;margin-left:12px">↳ {incident.name}</span>
                  <div style="color:#8B949E;font-size:0.76rem;margin-top:4px">{_strip_emojis(step.result_message or '')}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


render_remediation_fragment()
