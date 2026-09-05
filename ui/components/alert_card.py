"""
MavFix Genesis — Shared UI Components
Reusable HTML/Streamlit rendering helpers used across all pages.
Enterprise Datadog/Grafana Grade (Zero Emojis, Strict Proper/Uppercase).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
import streamlit as st

from config.settings import settings
from simulator.models import Alert

# Strip any residual emojis from strings
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA70-\U0001FAFF"
    "]+",
    flags=re.UNICODE,
)


def _strip_emojis(text: str) -> str:
    if not text:
        return ""
    cleaned = _EMOJI_PATTERN.sub("", text).strip()
    return cleaned


def render_alert_card(alert: Alert, compact: bool = False) -> None:
    """
    Render a single alert as a styled HTML card.
    `compact=True` renders a tighter one-liner suitable for lists.
    """
    sev = alert.severity.value
    color = settings.SEVERITY_COLORS.get(sev, "#8B949E")
    age = alert.age_seconds
    age_str = _fmt_age(age)
    scenario_badge = (
        f'<span style="background:#21262D;color:#58A6FF;'
        f'border:1px solid #30363D;border-radius:3px;'
        f'padding:2px 6px;font-size:0.68rem;font-weight:600;'
        f'font-family:\'JetBrains Mono\',monospace;margin-left:6px">'
        f'SCN-{alert.scenario_tag}</span>'
        if alert.scenario_tag else ""
    )

    if compact:
        html = f"""
        <div style="
            display:flex;align-items:center;gap:12px;
            padding:0.5rem 0.85rem;
            border-left:3px solid {color};
            background:#161B22;
            border-top:1px solid #21262D;
            border-right:1px solid #21262D;
            border-bottom:1px solid #21262D;
            border-radius:0 4px 4px 0;
            margin-bottom:4px;
            font-size:0.80rem;
        ">
          <span style="color:{color};font-weight:700;font-family:'JetBrains Mono',monospace;
                       min-width:26px">{sev}</span>
          <span style="color:#8B949E;min-width:65px;font-family:'JetBrains Mono',monospace;
                       font-size:0.75rem">{alert.timestamp.strftime('%H:%M:%S')}</span>
          <span style="color:#58A6FF;min-width:130px;font-weight:600;font-size:0.78rem">{alert.service}</span>
          <span style="color:#8B949E;min-width:130px;font-family:'JetBrains Mono',monospace;
                       font-size:0.75rem">{alert.metric}</span>
          <span style="color:#F0F6FC;font-weight:600;min-width:85px;
                       font-family:'JetBrains Mono',monospace">{alert.value:.1f} {alert.unit}</span>
          <span style="color:#8B949E;flex:1;font-size:0.76rem;
                       overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{_strip_emojis(alert.message)}</span>
          {scenario_badge}
          <span style="color:#6E7681;font-size:0.72rem;min-width:38px;text-align:right">{age_str}</span>
        </div>
        """
    else:
        runbook_html = (
            f'<a href="{alert.runbook_url}" target="_blank" style="color:#58A6FF;font-size:0.75rem;text-decoration:none;font-weight:600">'
            f'RUNBOOK [LINK]</a>'
            if alert.runbook_url else ""
        )
        html = f"""
        <div class="mavfix-card" style="border-left:4px solid {color};margin-bottom:8px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
            <div style="display:flex;align-items:center;gap:10px">
              <span class="badge badge-{sev.lower()}">{sev}</span>
              <span style="font-weight:600;color:#F0F6FC">{alert.service}</span>
              {scenario_badge}
            </div>
            <span style="color:#6E7681;font-size:0.74rem;font-family:'JetBrains Mono',monospace">
              {alert.timestamp.strftime('%H:%M:%S UTC')} · {age_str} ago
            </span>
          </div>
          <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:6px">
            <span style="color:#8B949E;font-size:0.78rem;text-transform:uppercase">{alert.metric}</span>
            <span style="color:{color};font-size:1.35rem;font-weight:700;
                         font-family:'JetBrains Mono',monospace">{alert.value:.1f}</span>
            <span style="color:#6E7681;font-size:0.78rem">{alert.unit}</span>
          </div>
          <p style="color:#8B949E;font-size:0.82rem;margin:0 0 6px">{_strip_emojis(alert.message)}</p>
          {runbook_html}
        </div>
        """
    st.markdown(html, unsafe_allow_html=True)


def render_kpi_row(stats: dict) -> None:
    """Render a row of KPI metric tiles."""
    cols = st.columns(5)
    items = [
        ("TOTAL ALERTS",     stats.get("total_alerts", 0),    "#F0F6FC"),
        ("TOTAL INCIDENTS",  stats.get("total_incidents", 0), "#58A6FF"),
        ("OPEN INCIDENTS",   stats.get("open_incidents", 0),  "#FFB300"),
        ("AUTO-EXECUTED",    stats.get("auto_executed", 0),   "#00E676"),
        ("PENDING APPROVAL", stats.get("pending_approval", 0),"#FF5252"),
    ]
    for col, (label, value, color) in zip(cols, items):
        with col:
            st.markdown(
                f"""
                <div class="kpi-tile">
                  <div class="kpi-value" style="color:{color}">{value}</div>
                  <div class="kpi-label">{label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def severity_badge_html(severity: str) -> str:
    sev = severity.upper()
    return f'<span class="badge badge-{sev.lower()}">{sev}</span>'


def risk_badge_html(risk: str) -> str:
    r = risk.lower()
    return f'<span class="badge badge-risk-{r}">RISK: {risk.upper()}</span>'


def status_html(status: str) -> str:
    s_clean = _strip_emojis(status).strip()
    s_upper = s_clean.upper()
    s_lower = s_clean.lower()

    if "escalated" in s_lower:
        return f'<span class="status-escalated">[ESCALATED: {s_upper}]</span>'
    if s_lower == "verifying":
        return '<span class="status-verifying">[VERIFYING]</span>'
    if s_lower == "resolved":
        return '<span class="status-resolved">[RESOLVED]</span>'

    return f'<span class="status-{s_lower}">[{s_upper}]</span>'


def render_page_header(icon_or_tag: str, title: str, subtitle: str = "") -> None:
    """Consistent page header across all dashboard pages (zero emojis, uppercase)."""
    clean_title = _strip_emojis(title).upper()
    tag = _strip_emojis(icon_or_tag).upper()
    tag_html = (
        f'<span style="background:#21262D;color:#58A6FF;border:1px solid #30363D;'
        f'padding:2px 8px;border-radius:3px;font-size:0.75rem;font-weight:700;'
        f'letter-spacing:0.06em;font-family:\'JetBrains Mono\',monospace;margin-right:8px">{tag}</span>'
        if tag and len(tag) <= 12 else ""
    )

    st.markdown(
        f"""
        <div style="margin-bottom:1.5rem;padding-bottom:0.75rem;border-bottom:1px solid #21262D">
          <h1 style="font-size:1.45rem;font-weight:700;margin-bottom:0.25rem;letter-spacing:-0.02em">
            {tag_html}{clean_title}
          </h1>
          {f'<p style="color:#8B949E;font-size:0.85rem;margin:0">{subtitle}</p>' if subtitle else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(icon_or_tag: str, message: str, hint: str = "") -> None:
    """Enterprise empty state (no cartoon emojis)."""
    st.markdown(
        f"""
        <div style="text-align:center;padding:2.5rem 1rem;background:#161B22;border:1px dashed #30363D;border-radius:6px;margin:1rem 0">
          <div style="font-family:'JetBrains Mono',monospace;font-size:0.78rem;color:#58A6FF;font-weight:700;margin-bottom:0.4rem">[SYSTEM STATUS: EMPTY]</div>
          <div style="font-size:0.95rem;color:#F0F6FC;font-weight:600;margin-bottom:0.3rem">{message}</div>
          {f'<div style="font-size:0.78rem;color:#8B949E">{hint}</div>' if hint else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _fmt_age(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds/60:.0f}m"
    return f"{seconds/3600:.1f}h"
