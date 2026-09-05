# ⚡ MavFix Genesis

> **Full SRE Copilot** — Real-time incident clustering, LLM root-cause analysis via Claude, and semi-autonomous remediation with a dark-themed operations dashboard.

![Python](https://img.shields.io/badge/Python-3.11+-4da6ff?style=flat-square&logo=python)
![Streamlit](https://img.shields.io/badge/Streamlit-1.38+-00ff88?style=flat-square&logo=streamlit)
![Claude](https://img.shields.io/badge/Claude-3.5_Haiku-9b59ff?style=flat-square)
![SQLite](https://img.shields.io/badge/SQLite-audit_log-ffa502?style=flat-square)

---

## Architecture

```
simulator/ ──► core/ ──────────────────► ui/
  (5 alert      │                         │
   scenarios    ├── clustering.py         ├── 01_live_feed.py
   + ambient)   ├── llm_engine.py         ├── 02_incidents.py
                ├── remediator.py         ├── 03_remediation.py
                └── incident_manager.py   ├── 04_audit_log.py
                         │               └── 05_analytics.py
                         ▼
                   audit_logs/
                   (SQLite WAL)
                         │
                   config/
                   (allow_list.yaml)
```

### Data Flow

1. **`AlertStream`** (APScheduler) emits ambient alerts every 8s
2. **Scenario triggers** fire correlated bursts of 6–7 realistic alerts
3. **`IncidentClusterer`** groups alerts via scenario-tag + TF-IDF cosine similarity
4. **`ClaudeRCAEngine`** calls `claude-3-5-haiku-20241022` with structured JSON schema prompt
5. **`RemediationEngine`** gates every step through `allow_list.yaml`:
   - `auto` → simulated/live execution immediately
   - `approval` → queued in UI for human sign-off
   - `blocked` → logged as rejected
6. Everything persisted to **SQLite** and surfaced in the dashboard

---

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Anthropic API key → [console.anthropic.com](https://console.anthropic.com)

### 2. Install dependencies
```bash
cd "e:/Career Projects/MavFix Genesis"
pip install -r requirements.txt
```

### 3. Configure environment
```bash
copy .env.example .env
# Edit .env and set your ANTHROPIC_API_KEY
```

### 4. Run the dashboard
```bash
streamlit run ui/app.py
```

The app opens at **http://localhost:8501**

---

## Project Structure

```
MavFix Genesis/
├── config/
│   ├── __init__.py
│   ├── settings.py          # Pydantic settings singleton (all env vars)
│   ├── allow_list.yaml      # 15 commands across auto/approval/blocked tiers
│   └── loader.py            # Typed YAML loader with validation
│
├── simulator/
│   ├── __init__.py
│   ├── models.py            # Alert Pydantic model (P1–P4 severity)
│   ├── scenarios.py         # 5 scenario generators + ambient pool
│   └── stream.py            # AlertStream with APScheduler + drain()
│
├── core/
│   ├── __init__.py
│   ├── models.py            # Incident, RCAResult, RemediationStep models
│   ├── clustering.py        # Scenario-tag + TF-IDF cosine clusterer
│   ├── llm_engine.py        # ClaudeRCAEngine — structured prompt + JSON parse
│   ├── remediator.py        # Semi-autonomous executor (simulated + live)
│   └── incident_manager.py  # Top-level orchestrator
│
├── audit_logs/
│   ├── __init__.py
│   ├── db.py                # SQLite schema + CRUD (WAL mode)
│   └── logger.py            # Domain-aware AuditLogger
│
├── ui/
│   ├── app.py               # Entry point, session-state bootstrap
│   ├── style.css            # Dark theme (Inter font, neon-green accent)
│   ├── components/
│   │   ├── alert_card.py    # Alert card + KPI row + badge helpers
│   │   └── incident_panel.py# RCA panel + approve/reject buttons
│   └── pages/
│       ├── 01_live_feed.py  # Real-time alert stream + scenario triggers
│       ├── 02_incidents.py  # Incident cards with RCA drill-down
│       ├── 03_remediation.py# Approval queue + auto-exec log
│       ├── 04_audit_log.py  # Filterable audit history + CSV export
│       └── 05_analytics.py  # MTTD/MTTR, Plotly charts
│
├── .env.example             # Environment variable template
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

---

## Alert Scenarios

| Tag | Name | Services | Alerts | Key Metrics |
|-----|------|----------|--------|-------------|
| **A** | Database Overload | postgres-primary, pgbouncer, app-server | 6 | CPU 94%+, conn pool 99%, slow queries 1300/min |
| **B** | Memory Leak Cascade | ml-inference, api-gateway, redis-cache | 7 | OOM kills, CrashLoopBackOff, p99 3800ms |
| **C** | Network Partition | mesh-proxy, order-service, payment-service | 7 | 18% packet loss, circuit breaker open, 34% checkout success |
| **D** | Disk I/O Saturation | kafka-broker, data-pipeline, elasticsearch | 7 | 97% disk, 312 write errors/min, 890s pipeline lag |
| **E** | Deployment Failure | checkout-service, load-balancer, feature-flags | 7 | 41% error rate, 72% health check failures, rollback signal |

All scenarios include ±12% metric jitter so no two triggers look identical.

---

## Remediation Allow-List

Defined in `config/allow_list.yaml`. Three tiers:

### AUTO — Execute immediately
| Command | Scenario | What it does |
|---------|----------|-------------|
| `restart_pod` | B, E | Restart a deployment |
| `flush_connection_pool` | A | Clear stale DB connections |
| `scale_replicas` | A, B, E | Horizontal scale-out |
| `enable_circuit_breaker` | C | Force-open circuit on degraded route |
| `rotate_log_files` | D | Reclaim log disk space |
| `clear_temp_files` | D | Delete stale temp/cache files |
| `adjust_memory_limit` | B | Increase pod memory headroom |

### APPROVAL — Human sign-off required
| Command | Scenario | Risk |
|---------|----------|------|
| `rollback_deployment` | E | Brief downtime |
| `drain_node` | C, D | Evicts all pods — high blast radius |
| `resize_persistent_volume` | D | Storage expansion |
| `kill_long_running_queries` | A | Terminates DB sessions |
| `isolate_service` | C | Applies NetworkPolicy |

### BLOCKED — Never execute
`delete_persistent_volume`, `drop_database`, `force_delete_namespace`

---

## Configuration

All settings live in `.env` (copy from `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(required)* | Your Anthropic API key |
| `MAVFIX_LLM_MODEL` | `claude-3-5-haiku-20241022` | Claude model ID |
| `MAVFIX_LIVE_MODE` | `false` | Enable real subprocess execution |
| `MAVFIX_DB_PATH` | `audit_logs/mavfix.db` | SQLite database path |
| `MAVFIX_AMBIENT_INTERVAL_SEC` | `8` | Background alert tick rate |
| `MAVFIX_CLUSTER_WINDOW_SEC` | `300` | Alert clustering time window |
| `MAVFIX_CLUSTER_MIN_ALERTS` | `2` | Minimum alerts to form an incident |
| `MAVFIX_UI_REFRESH_SEC` | `3` | Dashboard auto-refresh interval |

---

## LIVE_MODE

When `MAVFIX_LIVE_MODE=true`, the remediator executes real shell commands using the `live_cmd` templates in `allow_list.yaml`. Parameters are interpolated from the LLM-generated remediation step.

> ⚠️ **Use with extreme caution.** Only enable in environments where you have explicit permission to run kubectl/Docker commands. Default is `false` (simulated).

---

## Dashboard Pages

| Page | URL | Description |
|------|-----|-------------|
| 🏠 Home | `/` | KPI overview |
| 🔴 Live Feed | `/live_feed` | Real-time alerts + scenario triggers |
| 🔥 Incidents | `/incidents` | Clustered incidents with RCA |
| ⚙️ Remediation | `/remediation` | Approval queue + auto-exec log |
| 📋 Audit Log | `/audit_log` | Full event history + CSV export |
| 📊 Analytics | `/analytics` | MTTD, MTTR, Plotly charts |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Dashboard | Streamlit 1.38+ |
| LLM | Anthropic Claude (claude-3-5-haiku-20241022) |
| Data validation | Pydantic v2 + pydantic-settings |
| Alert clustering | scikit-learn TF-IDF + cosine similarity |
| Scheduling | APScheduler 3.x |
| Persistence | SQLite (WAL mode) |
| Charts | Plotly Express |
| Console output | Rich |
| Config | python-dotenv + PyYAML |

---

## License

MIT — Built as a portfolio project demonstrating autonomous SRE tooling with LLM integration.
