"""
MavFix Genesis — Alert Scenario Generators
Each scenario function returns a list of correlated Alert objects that
simulate a realistic incident burst. Metric values include seeded noise
so no two triggers look identical.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from simulator.models import Alert, Severity


# ── Helper ─────────────────────────────────────────────────────────────────

def _ts(offset_sec: float = 0.0) -> datetime:
    """Return a UTC datetime offset_sec seconds from now."""
    return datetime.now(timezone.utc) + timedelta(seconds=offset_sec)


def _jitter(base: float, pct: float = 0.12) -> float:
    """Add ±pct% random noise to a base value."""
    spread = base * pct
    return round(base + random.uniform(-spread, spread), 2)


def _uid() -> str:
    return str(uuid.uuid4())


# ── Scenario A — Database Overload ─────────────────────────────────────────

def scenario_a() -> list[Alert]:
    """
    Scenario A: Database Overload
    Trigger chain: CPU spike → slow queries → connection pool exhaustion → app timeouts
    Services involved: postgres-primary, app-server, pgbouncer
    """
    cpu = _jitter(94.7)
    slow_q = _jitter(1380, 0.20)
    conn_used = _jitter(198, 0.05)
    conn_max = 200
    wait_ms = _jitter(4200, 0.25)
    app_err = _jitter(23.4, 0.30)

    return [
        Alert(
            id=_uid(), timestamp=_ts(-18),
            service="postgres-primary", severity=Severity.P1,
            metric="cpu_utilization", value=cpu, unit="%",
            message=f"postgres-primary CPU at {cpu:.1f}% — sustained for 5 min, approaching saturation.",
            scenario_tag="A",
            labels={"team": "data", "env": "prod", "region": "us-east-1"},
            runbook_url="https://runbooks.internal/db-cpu-spike",
        ),
        Alert(
            id=_uid(), timestamp=_ts(-15),
            service="postgres-primary", severity=Severity.P2,
            metric="slow_query_count", value=slow_q, unit="queries/min",
            message=f"Slow query rate at {slow_q:.0f}/min (threshold: 500). Index scan regression detected.",
            scenario_tag="A",
            labels={"team": "data", "env": "prod", "region": "us-east-1"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-12),
            service="pgbouncer", severity=Severity.P1,
            metric="active_connections", value=conn_used, unit="connections",
            message=f"PgBouncer pool at {conn_used:.0f}/{conn_max} connections — {((conn_used/conn_max)*100):.0f}% exhausted.",
            scenario_tag="A",
            labels={"team": "data", "env": "prod"},
            runbook_url="https://runbooks.internal/conn-pool-exhaustion",
        ),
        Alert(
            id=_uid(), timestamp=_ts(-9),
            service="app-server", severity=Severity.P2,
            metric="db_query_wait_ms", value=wait_ms, unit="ms",
            message=f"App-server DB query wait time at {wait_ms:.0f}ms (SLA: 200ms). Upstream pool contention.",
            scenario_tag="A",
            labels={"team": "backend", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-6),
            service="app-server", severity=Severity.P2,
            metric="error_rate_pct", value=app_err, unit="%",
            message=f"App-server error rate {app_err:.1f}% — 503s from DB timeout propagation.",
            scenario_tag="A",
            labels={"team": "backend", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-3),
            service="postgres-primary", severity=Severity.P3,
            metric="replication_lag_sec", value=_jitter(42), unit="s",
            message="Replication lag rising — replica falling behind primary under write pressure.",
            scenario_tag="A",
            labels={"team": "data", "env": "prod"},
        ),
    ]


# ── Scenario B — Memory Leak Cascade ───────────────────────────────────────

def scenario_b() -> list[Alert]:
    """
    Scenario B: Memory Leak Cascade
    Trigger chain: RSS growth → OOM kill → pod restart loop → latency spikes → SLO breach
    Services involved: ml-inference, api-gateway, redis-cache
    """
    rss_pct = _jitter(97.2, 0.03)
    restart_count = int(_jitter(8, 0.25))
    p99_lat = _jitter(3800, 0.20)
    cache_miss = _jitter(78.4, 0.15)
    err_rate = _jitter(11.2, 0.30)

    return [
        Alert(
            id=_uid(), timestamp=_ts(-22),
            service="ml-inference", severity=Severity.P2,
            metric="memory_rss_pct", value=rss_pct, unit="%",
            message=f"ml-inference RSS at {rss_pct:.1f}% of limit — memory growth rate 2.1MB/min.",
            scenario_tag="B",
            labels={"team": "ml", "env": "prod", "pod": "ml-inference-7d4b9"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-18),
            service="ml-inference", severity=Severity.P1,
            metric="oom_kill_count", value=float(restart_count), unit="kills",
            message=f"OOMKilled {restart_count}x in last 15 min. Container repeatedly restarting.",
            scenario_tag="B",
            labels={"team": "ml", "env": "prod"},
            runbook_url="https://runbooks.internal/oom-cascade",
        ),
        Alert(
            id=_uid(), timestamp=_ts(-14),
            service="ml-inference", severity=Severity.P1,
            metric="pod_restart_count", value=float(restart_count), unit="restarts",
            message=f"CrashLoopBackOff detected — {restart_count} restarts. Back-off interval now 5min.",
            scenario_tag="B",
            labels={"team": "ml", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-11),
            service="api-gateway", severity=Severity.P2,
            metric="p99_latency_ms", value=p99_lat, unit="ms",
            message=f"API Gateway p99 latency {p99_lat:.0f}ms (SLO: 500ms). ml-inference timeouts propagating.",
            scenario_tag="B",
            labels={"team": "platform", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-8),
            service="redis-cache", severity=Severity.P3,
            metric="cache_miss_rate_pct", value=cache_miss, unit="%",
            message=f"Redis cache miss rate {cache_miss:.1f}% — cold start from pod restarts flushing in-process cache.",
            scenario_tag="B",
            labels={"team": "platform", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-5),
            service="api-gateway", severity=Severity.P2,
            metric="error_rate_pct", value=err_rate, unit="%",
            message=f"API error rate {err_rate:.1f}% — SLO burn rate critical. User-facing impact confirmed.",
            scenario_tag="B",
            labels={"team": "platform", "env": "prod"},
            runbook_url="https://runbooks.internal/api-slo-breach",
        ),
        Alert(
            id=_uid(), timestamp=_ts(-2),
            service="ml-inference", severity=Severity.P1,
            metric="availability_pct", value=_jitter(12.3, 0.20), unit="%",
            message="ml-inference availability dropped below 15%. Service effectively down.",
            scenario_tag="B",
            labels={"team": "ml", "env": "prod"},
        ),
    ]


# ── Scenario C — Network Partition ─────────────────────────────────────────

def scenario_c() -> list[Alert]:
    """
    Scenario C: Network Partition
    Trigger chain: packet loss → TCP retransmits → service timeouts → circuit breaker → degraded mesh
    Services involved: order-service, payment-service, mesh-proxy, notification-service
    """
    pkt_loss = _jitter(18.7, 0.25)
    retransmit_rate = _jitter(34.2, 0.20)
    timeout_rate = _jitter(67.8, 0.15)
    cb_open_count = int(_jitter(5, 0.20))

    return [
        Alert(
            id=_uid(), timestamp=_ts(-20),
            service="mesh-proxy", severity=Severity.P2,
            metric="packet_loss_pct", value=pkt_loss, unit="%",
            message=f"Envoy sidecar packet loss {pkt_loss:.1f}% on us-east-1b ↔ us-east-1c lane.",
            scenario_tag="C",
            labels={"team": "infra", "env": "prod", "az": "us-east-1b"},
            runbook_url="https://runbooks.internal/network-partition",
        ),
        Alert(
            id=_uid(), timestamp=_ts(-17),
            service="mesh-proxy", severity=Severity.P2,
            metric="tcp_retransmit_rate", value=retransmit_rate, unit="%",
            message=f"TCP retransmit rate {retransmit_rate:.1f}% — kernel network stack under stress.",
            scenario_tag="C",
            labels={"team": "infra", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-14),
            service="order-service", severity=Severity.P1,
            metric="request_timeout_rate", value=timeout_rate, unit="%",
            message=f"order-service timeout rate {timeout_rate:.1f}% on calls to payment-service.",
            scenario_tag="C",
            labels={"team": "commerce", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-11),
            service="payment-service", severity=Severity.P1,
            metric="circuit_breaker_open", value=float(cb_open_count), unit="circuits",
            message=f"Circuit breaker OPEN on {cb_open_count} downstream routes. Traffic shedding active.",
            scenario_tag="C",
            labels={"team": "commerce", "env": "prod"},
            runbook_url="https://runbooks.internal/circuit-breaker",
        ),
        Alert(
            id=_uid(), timestamp=_ts(-8),
            service="notification-service", severity=Severity.P3,
            metric="queue_depth", value=_jitter(14200, 0.15), unit="messages",
            message="Notification queue backing up — downstream delivery paused by partition.",
            scenario_tag="C",
            labels={"team": "comms", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-5),
            service="order-service", severity=Severity.P1,
            metric="checkout_success_rate_pct", value=_jitter(34.1, 0.20), unit="%",
            message="Checkout success rate dropped to ~34%. Revenue impact in progress.",
            scenario_tag="C",
            labels={"team": "commerce", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-3),
            service="mesh-proxy", severity=Severity.P2,
            metric="health_check_failures", value=_jitter(23, 0.20), unit="failures/min",
            message="Envoy health checks failing across 3 availability zones. AZ isolation may be needed.",
            scenario_tag="C",
            labels={"team": "infra", "env": "prod"},
        ),
    ]


# ── Scenario D — Disk I/O Saturation ───────────────────────────────────────

def scenario_d() -> list[Alert]:
    """
    Scenario D: Disk I/O Saturation
    Trigger chain: disk usage → write failures → I/O wait → pipeline stalls → data loss risk
    Services involved: kafka-broker, data-pipeline, elasticsearch, log-aggregator
    """
    disk_pct = _jitter(96.8, 0.03)
    io_wait = _jitter(78.3, 0.10)
    write_err = _jitter(312, 0.25)
    lag_sec = _jitter(890, 0.20)

    return [
        Alert(
            id=_uid(), timestamp=_ts(-25),
            service="kafka-broker", severity=Severity.P2,
            metric="disk_usage_pct", value=disk_pct, unit="%",
            message=f"kafka-broker disk at {disk_pct:.1f}% — estimated full in 47 minutes.",
            scenario_tag="D",
            labels={"team": "data", "env": "prod", "broker": "kafka-0"},
            runbook_url="https://runbooks.internal/disk-saturation",
        ),
        Alert(
            id=_uid(), timestamp=_ts(-20),
            service="kafka-broker", severity=Severity.P1,
            metric="write_error_rate", value=write_err, unit="errors/min",
            message=f"Kafka broker rejecting writes — {write_err:.0f} errors/min. Producers backing off.",
            scenario_tag="D",
            labels={"team": "data", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-16),
            service="data-pipeline", severity=Severity.P1,
            metric="consumer_lag_sec", value=lag_sec, unit="s",
            message=f"Data pipeline consumer lag {lag_sec:.0f}s — SLA breach imminent (threshold: 300s).",
            scenario_tag="D",
            labels={"team": "data-eng", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-13),
            service="elasticsearch", severity=Severity.P2,
            metric="disk_io_wait_pct", value=io_wait, unit="%",
            message=f"Elasticsearch I/O wait {io_wait:.1f}% — indexing throughput degraded 85%.",
            scenario_tag="D",
            labels={"team": "search", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-10),
            service="log-aggregator", severity=Severity.P3,
            metric="log_drop_rate", value=_jitter(4320, 0.20), unit="lines/min",
            message="Log aggregator dropping lines — upstream write pressure. Audit coverage reduced.",
            scenario_tag="D",
            labels={"team": "ops", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-7),
            service="kafka-broker", severity=Severity.P1,
            metric="partition_offline_count", value=_jitter(7, 0.20), unit="partitions",
            message="Kafka partitions going offline — disk full causing leader election failures.",
            scenario_tag="D",
            labels={"team": "data", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-4),
            service="data-pipeline", severity=Severity.P1,
            metric="pipeline_health_pct", value=_jitter(8.4, 0.20), unit="%",
            message="Data pipeline effectively stopped. Downstream ML features and dashboards stale.",
            scenario_tag="D",
            labels={"team": "data-eng", "env": "prod"},
        ),
    ]


# ── Scenario E — Deployment Failure ────────────────────────────────────────

def scenario_e() -> list[Alert]:
    """
    Scenario E: Deployment Failure
    Trigger chain: bad rollout → health check failures → error spike → traffic shift → rollback signal
    Services involved: checkout-service, load-balancer, feature-flags, metrics-server
    """
    err_rate = _jitter(41.7, 0.20)
    hc_fail_pct = _jitter(72.3, 0.15)
    p50_lat = _jitter(2100, 0.25)

    return [
        Alert(
            id=_uid(), timestamp=_ts(-16),
            service="checkout-service", severity=Severity.P2,
            metric="deployment_progress_pct", value=_jitter(34.2, 0.10), unit="%",
            message="Deployment of checkout-service v2.14.1 stalled at 34% rollout. New pods not becoming ready.",
            scenario_tag="E",
            labels={"team": "checkout", "env": "prod", "version": "v2.14.1"},
            runbook_url="https://runbooks.internal/deployment-failure",
        ),
        Alert(
            id=_uid(), timestamp=_ts(-13),
            service="checkout-service", severity=Severity.P1,
            metric="health_check_fail_pct", value=hc_fail_pct, unit="%",
            message=f"{hc_fail_pct:.0f}% of checkout-service v2.14.1 pods failing /healthz. Readiness probe rejecting.",
            scenario_tag="E",
            labels={"team": "checkout", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-10),
            service="load-balancer", severity=Severity.P1,
            metric="backend_error_rate_pct", value=err_rate, unit="%",
            message=f"Load balancer reporting {err_rate:.1f}% error rate — new pods returning HTTP 500.",
            scenario_tag="E",
            labels={"team": "platform", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-8),
            service="checkout-service", severity=Severity.P2,
            metric="p50_latency_ms", value=p50_lat, unit="ms",
            message=f"Checkout service p50 latency {p50_lat:.0f}ms (normal: 120ms). Cold-start penalty from restarts.",
            scenario_tag="E",
            labels={"team": "checkout", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-6),
            service="feature-flags", severity=Severity.P3,
            metric="sdk_error_count", value=_jitter(234, 0.20), unit="errors",
            message="Feature-flag SDK errors spiking — app init failure in new version touching flags service.",
            scenario_tag="E",
            labels={"team": "platform", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-4),
            service="metrics-server", severity=Severity.P3,
            metric="scrape_error_count", value=_jitter(18, 0.30), unit="errors/min",
            message="Metrics server scrape errors — new pods missing /metrics endpoint (startup crash before bind).",
            scenario_tag="E",
            labels={"team": "ops", "env": "prod"},
        ),
        Alert(
            id=_uid(), timestamp=_ts(-2),
            service="checkout-service", severity=Severity.P1,
            metric="rollback_recommended", value=1.0, unit="boolean",
            message="AUTO-SIGNAL: Deployment success criteria not met. Rollback to v2.13.9 recommended.",
            scenario_tag="E",
            labels={"team": "checkout", "env": "prod"},
        ),
    ]


# ── Ambient noise — random low-severity single alerts ──────────────────────

_AMBIENT_POOL: list[tuple[str, str, str, float, str, str]] = [
    # (service, metric, unit, base_value, message_template, severity)
    ("api-gateway",       "p95_latency_ms",       "ms",      145.0, "API Gateway p95 slightly elevated.", "P3"),
    ("postgres-replica",  "replication_lag_sec",  "s",         2.1, "Minor replication lag on replica.", "P4"),
    ("redis-cache",       "eviction_rate",         "keys/min", 18.0, "Redis eviction rate marginally above baseline.", "P4"),
    ("worker-pool",       "queue_depth",           "jobs",    320.0, "Background worker queue depth elevated.", "P3"),
    ("cdn",               "cache_hit_rate_pct",   "%",         88.0, "CDN cache hit rate slightly below target.", "P4"),
    ("auth-service",      "token_validation_ms",  "ms",        28.0, "Auth token validation latency minor uptick.", "P4"),
    ("email-sender",      "delivery_delay_sec",   "s",         12.0, "Email delivery slightly delayed.", "P4"),
    ("object-store",      "request_latency_ms",   "ms",        62.0, "Object store GET latency minor increase.", "P3"),
    ("load-balancer",     "connection_count",     "conns",   1240.0, "Load balancer active connections trending up.", "P3"),
    ("cron-scheduler",    "missed_jobs",          "jobs",       1.0, "1 scheduled job missed SLA by <30s.", "P4"),
]


def ambient_alert() -> Alert:
    """Generate a single random low-severity ambient alert for background noise."""
    svc, metric, unit, base, msg_tpl, sev_str = random.choice(_AMBIENT_POOL)
    value = _jitter(base, 0.15)
    return Alert(
        id=_uid(),
        timestamp=_ts(),
        service=svc,
        severity=Severity(sev_str),
        metric=metric,
        value=value,
        unit=unit,
        message=msg_tpl,
        scenario_tag=None,
        labels={"team": "ops", "env": "prod"},
    )


# ── Registry ───────────────────────────────────────────────────────────────

SCENARIO_REGISTRY: dict[str, Callable[[], list[Alert]]] = {
    "A": scenario_a,
    "B": scenario_b,
    "C": scenario_c,
    "D": scenario_d,
    "E": scenario_e,
}


def trigger_scenario(tag: str) -> list[Alert]:
    """Trigger a named scenario by tag letter (A–E)."""
    fn = SCENARIO_REGISTRY.get(tag.upper())
    if fn is None:
        raise ValueError(f"Unknown scenario tag '{tag}'. Valid tags: {list(SCENARIO_REGISTRY)}")
    return fn()
