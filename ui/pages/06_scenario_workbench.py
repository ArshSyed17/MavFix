"""
MavFix Genesis — Page 6: Scenario Execution Workbench
Enterprise Datadog/Grafana Grade (Zero Emojis, Strict Proper/Uppercase).
Interactive chaos engineering lab and infrastructure context panel.
"""

from __future__ import annotations

import sys
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(
    page_title="SCENARIO WORKBENCH · MAVFIX GENESIS",
    layout="wide",
    initial_sidebar_state="expanded",
)

from config.settings import settings
from ui.components.alert_card import render_page_header

# Inject CSS
css_path = Path(__file__).parents[1] / "style.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text('utf-8')}</style>", unsafe_allow_html=True)

# Session state bootstrap
if "manager" not in st.session_state:
    from core.incident_manager import IncidentManager
    mgr = IncidentManager(enable_llm=True, enable_remediation=True)
    mgr.start()
    st.session_state["manager"] = mgr

manager = st.session_state["manager"]

render_page_header(
    "LAB",
    "SCENARIO EXECUTION WORKBENCH",
    "ENTERPRISE CHAOS SIMULATION, TOPOLOGY CONTEXT, AND AUTONOMOUS PIPELINE GATING",
)

st.markdown(
    """
    <div style="background:#161B22;border:1px solid #30363D;border-radius:6px;padding:1.1rem 1.4rem;margin-bottom:1.5rem">
      <div style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;color:#58A6FF;font-weight:700;letter-spacing:0.08em;margin-bottom:0.35rem">
        [EVALUATOR BENCHMARK DIRECTIVE]
      </div>
      <div style="color:#8B949E;font-size:0.84rem;line-height:1.6">
        Select any production failure scenario below to trigger a synthetic alert burst.
        Observe the full autonomous lifecycle: <strong>Telemetry Ingestion</strong> →
        <strong>Windowed Alert Clustering</strong> → <strong>LLM Root Cause Reasoning</strong> →
        <strong>Safe Auto-Execution & Approval Gating</strong> → <strong>Closed-Loop Health Verification (5s Probe)</strong> →
        <strong>Automated SRE Post-Mortem Generation</strong>.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Scenario Metadata Catalog ──────────────────────────────────────
SCENARIOS = [
    {
        "tag": "A",
        "title": "SCENARIO A: DATABASE CONNECTION POOL EXHAUSTION",
        "severity": "P1 - CRITICAL",
        "sev_color": "#FF5252",
        "topology": "app-server:8080 ➔ pgbouncer:6432 ➔ postgres-primary:5432 (us-east-1)",
        "root_cause": (
            "Unindexed query scan regression in customer lookup combined with connection leak "
            "exhausting PgBouncer connection pool (198/200 active connections)."
        ),
        "telemetry": [
            "postgres-primary cpu_utilization: 94.7% (saturation threshold: 85%)",
            "pgbouncer active_connections: 198/200 (99% capacity exhausted)",
            "app-server db_query_wait_ms: 4,200ms (SLA: 200ms)",
            "app-server error_rate_pct: 23.4% HTTP 503 errors",
        ],
        "auto_action": "flush_connection_pool (TIER: AUTO / SAFE)",
        "approval_action": "scale_db_replicas (TIER: APPROVAL REQUIRED / HIGH RISK)",
        "verification_target": "postgres-primary (Port 5432 Connection Probe)",
    },
    {
        "tag": "B",
        "title": "SCENARIO B: MEMORY LEAK CASCADE & OOM CRASH",
        "severity": "P1 - CRITICAL",
        "sev_color": "#FF5252",
        "topology": "worker-pool ➔ ml-inference:8000 ➔ redis-broker:6379",
        "root_cause": (
            "PyTorch tensor retention in batch inference loop accumulating uncollected GPU/RAM buffers, "
            "triggering Linux kernel OOM-killer termination."
        ),
        "telemetry": [
            "ml-inference memory_usage_pct: 96.8% (OOM threshold: 90%)",
            "ml-inference oom_kill_events: 4 terminated worker processes",
            "worker-pool queue_depth: 480 pending jobs backed up",
            "api-gateway p99_latency_ms: 8,400ms timeout cascade",
        ],
        "auto_action": "adjust_memory_limit (TIER: AUTO / SAFE)",
        "approval_action": "rollback_deployment (TIER: APPROVAL REQUIRED / DESTRUCTIVE)",
        "verification_target": "ml-inference (Healthz Heap Probe)",
    },
    {
        "tag": "C",
        "title": "SCENARIO C: CROSS-REGION NETWORK PARTITION",
        "severity": "P2 - HIGH",
        "sev_color": "#FFB300",
        "topology": "checkout-api (us-east-1) ➔ transit-gateway ➔ payment-service (us-west-2)",
        "root_cause": (
            "Inter-region VPC peering packet loss spike (38%) causing bidirectional TCP reset storms "
            "and circuit breaker trips across payment gateways."
        ),
        "telemetry": [
            "transit-gateway packet_loss_pct: 38.2% (threshold: 2%)",
            "checkout-api tcp_retrans_pct: 24.1% retransmitted segments",
            "payment-service timeout_count: 312 connection aborts/min",
            "checkout-api error_rate_pct: 18.5% payment failures",
        ],
        "auto_action": "reroute_traffic (TIER: AUTO / SAFE)",
        "approval_action": "isolate_partition_zone (TIER: APPROVAL REQUIRED / NETWORK GATING)",
        "verification_target": "payment-service (Cross-Region Ping & Latency Probe)",
    },
    {
        "tag": "D",
        "title": "SCENARIO D: DISK I/O SATURATION & WRITE QUEUE SPIKE",
        "severity": "P2 - HIGH",
        "sev_color": "#FFB300",
        "topology": "fluentd-collector ➔ log-aggregator ➔ elasticsearch-data:9200",
        "root_cause": (
            "Debug-level access logging accidentally enabled in production, saturating NVMe EBS volume IOPS "
            "and stalling Elasticsearch write commits."
        ),
        "telemetry": [
            "elasticsearch-data disk_utilization_pct: 98.4% (critical threshold: 90%)",
            "elasticsearch-data write_iops: 14,200 IOPS (EBS provisioned ceiling: 12,000)",
            "log-aggregator disk_queue_depth: 82 pending I/O operations",
            "elasticsearch-data write_stall_sec: 14.5s cluster write pause",
        ],
        "auto_action": "truncate_temp_logs (TIER: AUTO / SAFE)",
        "approval_action": "expand_ebs_volume (TIER: APPROVAL REQUIRED / STORAGE CHANGE)",
        "verification_target": "elasticsearch-data (Cluster Health State: Green)",
    },
    {
        "tag": "E",
        "title": "SCENARIO E: CANARY DEPLOYMENT REGRESSION",
        "severity": "P1 - CRITICAL",
        "sev_color": "#FF5252",
        "topology": "envoy-ingress ➔ frontend-edge:v2.4.1 (Canary 10% Traffic Weight)",
        "root_cause": (
            "Uncaught JavaScript runtime exception in server-side rendering bundle executing on v2.4.1, "
            "throwing HTTP 500 internal server error for 100% of canary cohort."
        ),
        "telemetry": [
            "frontend-edge:v2.4.1 http_5xx_rate_pct: 42.6% (canary threshold: 1%)",
            "envoy-ingress upstream_reset_count: 1,480 resets/min",
            "frontend-edge canary_error_budget: 0% remaining (exhausted)",
            "user-session drop_rate_pct: 31.0% sudden dropoff",
        ],
        "auto_action": "disable_canary_routing (TIER: AUTO / SAFE)",
        "approval_action": "rollback_release (TIER: APPROVAL REQUIRED / PROD ROLLBACK)",
        "verification_target": "frontend-edge (HTTP 200 Ingress Verification Probe)",
    },
]

# ── Render Scenario Cards ──────────────────────────────────────────
for sc in SCENARIOS:
    with st.container():
        st.markdown(
            f"""
            <div class="workbench-card" style="border-left:4px solid {sc['sev_color']};">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                <div style="display:flex;align-items:center;gap:10px">
                  <span style="color:{sc['sev_color']};font-weight:700;font-family:'JetBrains Mono',monospace;font-size:0.75rem">
                    [{sc['severity']}]
                  </span>
                  <span style="font-weight:700;color:#F0F6FC;font-size:1.05rem;letter-spacing:-0.01em">
                    {sc['title']}
                  </span>
                </div>
                <span class="topology-tag">TOPOLOGY: {sc['topology']}</span>
              </div>
              <div style="color:#8B949E;font-size:0.84rem;margin-bottom:12px;line-height:1.5">
                <strong style="color:#F0F6FC">ROOT CAUSE PROFILE:</strong> {sc['root_cause']}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_left, col_right, col_btn = st.columns([4, 4, 2])

        with col_left:
            st.markdown(
                """
                <div style="font-size:0.72rem;color:#6E7681;text-transform:uppercase;
                            font-weight:700;letter-spacing:0.08em;margin-bottom:4px;font-family:'JetBrains Mono',monospace">
                  INGESTED TELEMETRY SIGNALS
                </div>
                """,
                unsafe_allow_html=True,
            )
            for t in sc["telemetry"]:
                st.markdown(
                    f"<div style='font-size:0.78rem;color:#8B949E;font-family:\"JetBrains Mono\",monospace;margin-bottom:2px'>"
                    f"• {t}</div>",
                    unsafe_allow_html=True,
                )

        with col_right:
            st.markdown(
                """
                <div style="font-size:0.72rem;color:#6E7681;text-transform:uppercase;
                            font-weight:700;letter-spacing:0.08em;margin-bottom:4px;font-family:'JetBrains Mono',monospace">
                  AUTONOMOUS REMEDIATION GATES
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                f"""
                <div style="font-size:0.78rem;margin-bottom:4px">
                  <span style="color:#00E676;font-weight:700;font-family:'JetBrains Mono',monospace">[AUTO]</span>
                  <span style="color:#F0F6FC">{sc['auto_action']}</span>
                </div>
                <div style="font-size:0.78rem;margin-bottom:4px">
                  <span style="color:#FFB300;font-weight:700;font-family:'JetBrains Mono',monospace">[GATE]</span>
                  <span style="color:#F0F6FC">{sc['approval_action']}</span>
                </div>
                <div style="font-size:0.74rem;color:#58A6FF;font-family:'JetBrains Mono',monospace;margin-top:4px">
                  PROBE: {sc['verification_target']}
                </div>
                """,
                unsafe_allow_html=True,
            )

        with col_btn:
            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            if st.button(f"EXECUTE SCENARIO {sc['tag']}", key=f"wb_trigger_{sc['tag']}", use_container_width=True):
                trigger_fn = getattr(manager, "trigger_scenario", getattr(manager, "trigger", None))
                alerts = trigger_fn(sc["tag"]) if trigger_fn else []
                st.session_state["selected_scenario"] = sc["tag"]
                st.success(f"[PIPELINE ACTIVE] Injected {len(alerts)} alerts for Scenario {sc['tag']}.")
                st.markdown(
                    """
                    <div style="margin-top:6px">
                      <a href="/incidents" target="_self" style="display:inline-block;width:100%;text-align:center;
                         background:#21262D;color:#58A6FF;border:1px solid #30363D;border-radius:4px;
                         padding:6px;font-size:0.75rem;font-weight:700;text-decoration:none;font-family:'JetBrains Mono',monospace">
                        VIEW IN ACTIVE INCIDENTS ➔
                      </a>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown("<hr style='margin:1.5rem 0;border-color:#21262D'>", unsafe_allow_html=True)
