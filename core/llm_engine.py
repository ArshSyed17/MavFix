"""
MavFix Genesis — Claude RCA Engine
Formats incident context into a structured prompt, calls the Anthropic API,
and parses the JSON response into a typed RCAResult.

Prompt design:
  • System prompt establishes the SRE-copilot role and output schema.
  • User message injects the full incident context (alerts, services, metrics).
  • Response is expected as a single JSON object — parsed with json.loads().
  • On parse failure we retry once with an explicit "JSON only" nudge.
"""

from __future__ import annotations

import json
import logging
import re
import textwrap
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import anthropic
from pydantic import ValidationError

from config.settings import settings
from core.models import Incident, RCAResult, RemediationStep, RiskLevel
from simulator.models import Alert

logger = logging.getLogger(__name__)

# ── Prompt templates ───────────────────────────────────────────────────────

_SYSTEM_PROMPT = textwrap.dedent("""
    You are MavFix, an expert Site Reliability Engineering (SRE) copilot.
    Your role is to analyse incident data, identify the most probable root cause,
    assess impact, and propose a prioritised remediation plan.

    You MUST respond with a single, valid JSON object matching EXACTLY this schema
    (no markdown fences, no extra text — raw JSON only):

    {
      "root_cause": "<concise 1-2 sentence root cause statement>",
      "confidence": <float 0.0-1.0>,
      "impact_summary": "<user-facing impact description, 1-2 sentences>",
      "risk_level": "<low|medium|high>",
      "estimated_resolution_min": <integer minutes or null>,
      "remediation_steps": [
        {
          "command": "<allow-list command key>",
          "rationale": "<why this step helps>",
          "params": { "<key>": "<value>" },
          "risk": "<low|medium|high>"
        }
      ]
    }

    Available allow-list command keys (use ONLY these):
      AUTO (execute immediately):
        - restart_pod           params: deployment, namespace
        - flush_connection_pool params: container
        - scale_replicas        params: deployment, count, namespace
        - enable_circuit_breaker params: host
        - rotate_log_files      params: service
        - clear_temp_files      params: path
        - adjust_memory_limit   params: deployment, limit, namespace

      APPROVAL (human sign-off required):
        - rollback_deployment   params: deployment, namespace
        - drain_node            params: node
        - resize_persistent_volume params: pvc, size, namespace
        - kill_long_running_queries params: container, user, threshold
        - isolate_service       params: service

      BLOCKED (never suggest these):
        - delete_persistent_volume
        - drop_database
        - force_delete_namespace

    Rules:
      1. Suggest 2-5 remediation steps in priority order.
      2. Prefer AUTO-tier steps for immediate stabilisation.
      3. Include an APPROVAL-tier step only if AUTO steps are insufficient.
      4. NEVER suggest BLOCKED commands.
      5. Fill params with realistic values inferred from the incident context.
      6. If confidence < 0.5, set risk_level to "high".
      7. Respond with raw JSON only — absolutely no markdown, no explanation.
""").strip()


def _build_user_message(incident: Incident) -> str:
    """Construct the user-turn message with full incident context."""
    lines: list[str] = [
        f"## Incident: {incident.name}",
        f"Status: {incident.status.value}",
        f"Severity: {incident.severity.value}",
        f"Scenario: {incident.scenario_tag or 'Unknown / Ambient'}",
        f"Services affected: {', '.join(incident.services) or 'unknown'}",
        f"Alert count: {incident.alert_count}",
        f"Duration: {incident.duration_sec:.0f}s",
        "",
        "### Alert Timeline (oldest → newest):",
    ]

    sorted_alerts = sorted(incident.alerts, key=lambda a: a.timestamp)
    for a in sorted_alerts:
        ts = a.timestamp.strftime("%H:%M:%S")
        lines.append(
            f"  [{ts}] [{a.severity.value}] {a.service} | "
            f"{a.metric}={a.value}{a.unit} — {a.message}"
        )

    lines += [
        "",
        "### Context:",
        f"  Most severe alert: {incident.severity.value} on {incident.services[0] if incident.services else 'unknown'}",
        "",
        "Analyse this incident and return your JSON response.",
    ]

    return "\n".join(lines)


def _extract_json(text: str) -> str:
    """
    Strip any markdown fences or leading/trailing prose from LLM output
    and return the raw JSON string.
    """
    # Remove ```json ... ``` fences if present
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)

    # Find the first { and last } to extract the JSON object
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return text.strip()
    return text[start : end + 1].strip()


# ── Engine class ───────────────────────────────────────────────────────────

class ClaudeRCAEngine:
    """
    Root-cause analysis engine powered by Anthropic Claude.

    Usage:
        engine = ClaudeRCAEngine()
        rca    = engine.analyse(incident)
    """

    def __init__(self) -> None:
        # 1. Google Gemini configuration
        self._gemini_key = settings.gemini_api_key
        self._gemini_model = settings.gemini_model
        self._has_gemini = bool(
            self._gemini_key
            and not self._gemini_key.startswith("your-gemini")
            and not self._gemini_key.startswith("dummy")
        )

        # 2. Anthropic Claude configuration
        api_key = settings.anthropic_api_key
        self._model = settings.llm_model
        self._max_tokens = settings.llm_max_tokens
        self._has_claude = bool(
            api_key
            and not api_key.startswith("sk-ant-your")
            and not api_key.startswith("dummy")
        )
        self._client = None
        if self._has_claude:
            try:
                self._client = anthropic.Anthropic(api_key=api_key)
            except Exception as e:
                logger.warning("Failed to initialize Anthropic client: %s", e)

        # Active provider determination
        if self._has_gemini:
            self.provider_name = f"Google Gemini ({self._gemini_model})"
            logger.info("Google Gemini engine active (model=%s).", self._gemini_model)
        elif self._client is not None:
            self.provider_name = f"Anthropic Claude ({self._model})"
            logger.info("Claude engine active (model=%s).", self._model)
        else:
            self.provider_name = "Deterministic Demo Fallback"
            logger.info("No live LLM key detected — running in demo/mock fallback mode.")

    def _call_gemini(self, prompt: str, as_json: bool = False) -> str:
        """Execute a request against Google Generative Language API via standard REST."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._gemini_model}:generateContent?key={self._gemini_key}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2 if as_json else 0.3,
            },
        }
        if as_json:
            body["generationConfig"]["responseMimeType"] = "application/json"

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=35) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            candidates = payload.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned empty candidate list.")
            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return text

    def analyse(self, incident: Incident) -> RCAResult:
        """
        Run RCA on the incident using Gemini, Claude, or deterministic fallback.
        """
        user_msg = _build_user_message(incident)

        # 1. Primary: Google Gemini
        if self._has_gemini:
            try:
                logger.info("Running Gemini RCA for %s via %s …", incident.name, self._gemini_model)
                full_prompt = (
                    f"{_SYSTEM_PROMPT}\n\n"
                    f"Incident Telemetry Data:\n{user_msg}\n\n"
                    "Respond with a single valid raw JSON object matching the schema."
                )
                raw = self._call_gemini(full_prompt, as_json=True)
                result = self._parse_response(raw)
                logger.info(
                    "Gemini RCA complete for %s — root_cause='%s…' confidence=%.2f",
                    incident.name, result.root_cause[:60], result.confidence,
                )
                return result
            except Exception as exc:
                logger.warning("Gemini RCA call failed for %s (%s). Falling back.", incident.name, exc)

        # 2. Secondary: Anthropic Claude
        if self._client is not None:
            try:
                logger.info("Running Claude RCA for %s via %s …", incident.name, self._model)
                raw = self._call_llm(user_msg)
                try:
                    result = self._parse_response(raw)
                    return result
                except (json.JSONDecodeError, ValidationError, KeyError) as e:
                    logger.warning("First parse attempt failed: %s — retrying with nudge.", e)
                    nudge = f"{user_msg}\n\nIMPORTANT: Return ONLY a valid JSON object."
                    raw2 = self._call_llm(nudge)
                    return self._parse_response(raw2)
            except Exception as exc:
                logger.warning("Claude RCA call failed for %s (%s). Falling back.", incident.name, exc)

        # 3. Fallback: Scenario RCA
        return self._generate_fallback_rca(incident)

    def analyse_safe(self, incident: Incident) -> RCAResult:
        """
        Like `analyse()` but safely returns fallback RCA on any unexpected error.
        """
        try:
            return self.analyse(incident)
        except Exception as exc:
            logger.error("RCA failed for %s: %s — falling back to deterministic RCA.", incident.name, exc)
            return self._generate_fallback_rca(incident)

    def _generate_fallback_rca(self, incident: Incident) -> RCAResult:
        """
        Generates realistic, scenario-appropriate SRE root cause analysis
        and remediation steps when live Claude API is unavailable or in demo mode.
        """
        tags = [a.scenario_tag for a in incident.alerts if a.scenario_tag]
        tag = tags[0] if tags else None

        if tag == "A":
            root_cause = (
                "PostgreSQL connection pool exhaustion caused by high unindexed query load "
                "and sustained CPU saturation on postgres-primary."
            )
            confidence = 0.94
            impact = "Elevated API response times and intermittent 504 gateway timeouts on dependent backend services."
            risk = RiskLevel.MEDIUM
            resolution_min = 5
            steps = [
                RemediationStep(
                    command="flush_connection_pool",
                    rationale="Flush idle and leaked connections in pgbouncer pool to restore connectivity.",
                    params={"container": "pgbouncer"},
                    risk=RiskLevel.LOW,
                ),
                RemediationStep(
                    command="kill_long_running_queries",
                    rationale="Terminate long-running unindexed queries (>60s) consuming CPU and locking tables.",
                    params={"container": "postgres-primary", "user": "app", "threshold": "60s"},
                    risk=RiskLevel.MEDIUM,
                ),
                RemediationStep(
                    command="scale_replicas",
                    rationale="Scale app-server pods to distribute read traffic and relieve connection pressure.",
                    params={"deployment": "app-server", "count": 3, "namespace": "prod"},
                    risk=RiskLevel.LOW,
                ),
            ]
        elif tag == "B":
            root_cause = (
                "Memory leak in checkout-service worker pool leading to Out-Of-Memory (OOM) "
                "container evictions and restart cascade."
            )
            confidence = 0.92
            impact = "High 5xx error rates and elevated latency impacting active user checkout flows."
            risk = RiskLevel.MEDIUM
            resolution_min = 8
            steps = [
                RemediationStep(
                    command="adjust_memory_limit",
                    rationale="Temporarily raise container memory limit to 2Gi to give buffer while investigating.",
                    params={"deployment": "checkout-service", "limit": "2Gi", "namespace": "prod"},
                    risk=RiskLevel.LOW,
                ),
                RemediationStep(
                    command="restart_pod",
                    rationale="Perform graceful rolling restart of crashed pods to reclaim leaked memory.",
                    params={"deployment": "checkout-service", "namespace": "prod"},
                    risk=RiskLevel.LOW,
                ),
                RemediationStep(
                    command="rollback_deployment",
                    rationale="Roll back checkout-service to stable release v2.13.9 if memory leak persists.",
                    params={"deployment": "checkout-service", "namespace": "prod"},
                    risk=RiskLevel.HIGH,
                ),
            ]
        elif tag == "C":
            root_cause = (
                "Network partition and elevated cross-AZ packet loss between api-gateway and auth-service."
            )
            confidence = 0.89
            impact = "Cascading request timeouts and authentication failures across public API gateways."
            risk = RiskLevel.MEDIUM
            resolution_min = 10
            steps = [
                RemediationStep(
                    command="enable_circuit_breaker",
                    rationale="Trip circuit breaker to fail fast and protect thread pools from connection exhaustion.",
                    params={"host": "auth-service.prod.svc.cluster.local"},
                    risk=RiskLevel.LOW,
                ),
                RemediationStep(
                    command="isolate_service",
                    rationale="Temporarily isolate unhealthy availability zone routing to divert traffic to healthy zone.",
                    params={"service": "auth-service"},
                    risk=RiskLevel.HIGH,
                ),
            ]
        elif tag == "D":
            root_cause = (
                "Persistent volume disk exhaustion (98% capacity) due to unarchived database WAL logs."
            )
            confidence = 0.95
            impact = "Database write stalls and ingest pipeline transaction log commit failures."
            risk = RiskLevel.HIGH
            resolution_min = 6
            steps = [
                RemediationStep(
                    command="clear_temp_files",
                    rationale="Purge temporary transaction logs and crash dumps to free immediate buffer space.",
                    params={"path": "/var/tmp/data"},
                    risk=RiskLevel.LOW,
                ),
                RemediationStep(
                    command="rotate_log_files",
                    rationale="Force log rotation and archive aged write-ahead transaction logs.",
                    params={"service": "postgres-primary"},
                    risk=RiskLevel.LOW,
                ),
                RemediationStep(
                    command="resize_persistent_volume",
                    rationale="Expand persistent volume claim from 100Gi to 250Gi to accommodate write volume.",
                    params={"pvc": "data-postgres-primary-0", "size": "250Gi", "namespace": "prod"},
                    risk=RiskLevel.HIGH,
                ),
            ]
        elif tag == "E":
            root_cause = (
                "Defective application release v2.14.0 crashing on initialization due to missing runtime dependency."
            )
            confidence = 0.97
            impact = "Critical service outage on checkout-service with 0 healthy replicas passing readiness probes."
            risk = RiskLevel.HIGH
            resolution_min = 4
            steps = [
                RemediationStep(
                    command="rollback_deployment",
                    rationale="Execute immediate emergency rollback to previous stable release v2.13.9.",
                    params={"deployment": "checkout-service", "namespace": "prod"},
                    risk=RiskLevel.HIGH,
                ),
                RemediationStep(
                    command="restart_pod",
                    rationale="Restart affected deployment pods to ensure clean state on rolled-back image.",
                    params={"deployment": "checkout-service", "namespace": "prod"},
                    risk=RiskLevel.LOW,
                ),
            ]
        else:
            svc = incident.primary_service or "backend-service"
            root_cause = f"System metric anomaly detected on service '{svc}'. Elevated error threshold breached."
            confidence = 0.78
            impact = "Transient performance degradation and localized latency increase."
            risk = RiskLevel.LOW
            resolution_min = 12
            steps = [
                RemediationStep(
                    command="restart_pod",
                    rationale=f"Perform graceful restart of {svc} to restore stable baseline.",
                    params={"deployment": svc, "namespace": "prod"},
                    risk=RiskLevel.LOW,
                ),
            ]

        return RCAResult(
            root_cause=root_cause,
            confidence=confidence,
            impact_summary=impact,
            risk_level=risk,
            estimated_resolution_min=resolution_min,
            remediation_steps=steps,
            llm_raw_response=f"[Deterministic SRE Fallback / Demo RCA for Scenario {tag or 'Ambient'}]",
            analysed_at=datetime.now(timezone.utc),
        )

    # ── Private helpers ────────────────────────────────────────────────────

    def _call_llm(self, user_message: str) -> str:
        """Make the Anthropic API call and return the raw text response."""
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    def _parse_response(self, raw: str) -> RCAResult:
        """Parse raw LLM text into a typed RCAResult."""
        json_str = _extract_json(raw)
        data: dict = json.loads(json_str)

        steps: list[RemediationStep] = []
        for step_data in data.get("remediation_steps", []):
            steps.append(
                RemediationStep(
                    command=step_data.get("command", "unknown"),
                    rationale=step_data.get("rationale", ""),
                    params=step_data.get("params", {}),
                    risk=RiskLevel(step_data.get("risk", "low")),
                )
            )

        return RCAResult(
            root_cause=data["root_cause"],
            confidence=float(data.get("confidence", 0.5)),
            impact_summary=data.get("impact_summary", ""),
            risk_level=RiskLevel(data.get("risk_level", "medium")),
            estimated_resolution_min=data.get("estimated_resolution_min"),
            remediation_steps=steps,
            llm_raw_response=raw,
            analysed_at=datetime.now(timezone.utc),
        )

    # ── Post-Mortem Generator ──────────────────────────────────────────────

    def generate_post_mortem(self, incident: Incident) -> str:
        """
        Generate a comprehensive, structured Markdown Post-Mortem report
        for a resolved incident using Gemini, Claude, or fallback generator.
        """
        logger.info("Generating Post-Mortem report for %s …", incident.name)

        # 1. Primary: Google Gemini
        if self._has_gemini:
            try:
                report = self._call_gemini_post_mortem(incident)
                if report and len(report.strip()) > 100:
                    logger.info("Gemini Post-Mortem generation succeeded for %s.", incident.name)
                    return report.strip()
            except Exception as e:
                logger.warning("Gemini Post-Mortem call failed for %s: %s. Trying alternative.", incident.name, e)

        # 2. Secondary: Anthropic Claude
        if self._client is not None:
            try:
                report = self._call_post_mortem_llm(incident)
                if report and len(report.strip()) > 100:
                    logger.info("Claude Post-Mortem generation succeeded for %s.", incident.name)
                    return report.strip()
            except Exception as e:
                logger.warning(
                    "Claude Post-Mortem LLM call failed for %s: %s. Falling back to deterministic generator.",
                    incident.name, e,
                )

        # 3. Fallback: Scenario generator
        return self._generate_fallback_post_mortem(incident)

    def _call_gemini_post_mortem(self, incident: Incident) -> str:
        """Prompt Gemini to generate a structured markdown post-mortem."""
        alerts_summary = "\n".join([
            f"- [{a.timestamp.strftime('%H:%M:%S')}] {a.service} ({a.severity.value}): {a.metric}={a.value} {a.unit} — {a.message}"
            for a in incident.alerts[:15]
        ])
        steps_summary = "\n".join([
            f"- [{s.tier or 'action'}] {s.command}: status={s.status}, result={s.result_message or 'completed'}"
            for s in (incident.rca.remediation_steps if incident.rca else [])
        ])

        system_prompt = (
            "You are MavFix, an expert Principal Site Reliability Engineer (SRE).\n"
            "Generate an exhaustive, professional, blameless Markdown Post-Mortem report for a resolved production incident.\n\n"
            "The report MUST contain these exact sections:\n"
            "# 📋 Incident Post-Mortem: <Incident Name> — <Short Descriptive Title>\n"
            "## 1. Executive Summary\n"
            "## 2. Root Cause Analysis\n"
            "## 3. Incident Timeline\n"
            "## 4. Remediation & Recovery Actions\n"
            "## 5. Preventative Recommendations\n\n"
            "Formatting requirements: GitHub-flavored Markdown, timeline table, root cause 5-whys breakdown, action items table."
        )

        user_prompt = (
            f"Incident Details:\n"
            f"- Incident Name: {incident.name}\n"
            f"- Severity: {incident.severity.value}\n"
            f"- Primary Service: {incident.primary_service or 'backend'}\n"
            f"- Services Affected: {', '.join(incident.services)}\n"
            f"- Scenario Tag: {incident.scenario_tag or 'Unclassified'}\n"
            f"- Opened At: {incident.opened_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"- Resolved At: {incident.resolved_at.strftime('%Y-%m-%d %H:%M:%S UTC') if incident.resolved_at else 'Recently'}\n"
            f"- Duration: {incident.duration_sec:.0f}s\n"
            f"- Closed-Loop Health Verification: PASSED\n\n"
            f"Root Cause (from RCA Engine):\n"
            f"- Root Cause: {incident.rca.root_cause if incident.rca else 'Unknown'}\n"
            f"- Impact: {incident.rca.impact_summary if incident.rca else 'Degradation'}\n\n"
            f"Remediation Steps Executed:\n{steps_summary}\n\n"
            f"Alerts Captured:\n{alerts_summary}"
        )

        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        return self._call_gemini(full_prompt, as_json=False)

    def _call_post_mortem_llm(self, incident: Incident) -> str:
        """Prompt Claude to generate a structured markdown post-mortem."""
        alerts_summary = "\n".join([
            f"- [{a.timestamp.strftime('%H:%M:%S')}] {a.service} ({a.severity.value}): {a.metric}={a.value} {a.unit} — {a.message}"
            for a in incident.alerts[:15]
        ])
        steps_summary = "\n".join([
            f"- [{s.tier or 'action'}] {s.command}: status={s.status}, result={s.result_message or 'completed'}"
            for s in (incident.rca.remediation_steps if incident.rca else [])
        ])

        system_prompt = textwrap.dedent("""
            You are MavFix, an expert Principal Site Reliability Engineer (SRE).
            Generate an exhaustive, professional, blameless Markdown Post-Mortem report
            for a resolved production incident.

            The report MUST contain these exact sections:
            # 📋 Incident Post-Mortem: <Incident Name> — <Short Descriptive Title>
            ## 1. Executive Summary
            ## 2. Root Cause Analysis
            ## 3. Incident Timeline
            ## 4. Remediation & Recovery Actions
            ## 5. Preventative Recommendations

            Formatting requirements:
            - Professional GitHub-flavored Markdown.
            - Timeline must be formatted as a detailed Markdown table with columns: Time (UTC), Phase, Event Description, Impact.
            - Root Cause Analysis must detail the trigger, propagation chain, and 5-whys breakdown.
            - Preventative Recommendations must be a table with columns: Priority (P0-P2), Action Item, Owner Team, Target Completion.
            - Blameless, analytical, and actionable tone.
        """).strip()

        user_prompt = textwrap.dedent(f"""
            Incident Details:
            - Incident Name: {incident.name}
            - Severity: {incident.severity.value}
            - Primary Service: {incident.primary_service or 'backend'}
            - Services Affected: {', '.join(incident.services)}
            - Scenario Tag: {incident.scenario_tag or 'Unclassified'}
            - Opened At: {incident.opened_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
            - Resolved At: {incident.resolved_at.strftime('%Y-%m-%d %H:%M:%S UTC') if incident.resolved_at else 'Recently'}
            - Total Duration: {incident.duration_sec:.0f} seconds
            - Closed-Loop Health Verification: PASSED (service telemetry nominal)

            Root Cause Analysis (from RCA Engine):
            - Root Cause: {incident.rca.root_cause if incident.rca else 'Unknown'}
            - Impact Summary: {incident.rca.impact_summary if incident.rca else 'Transient service disruption'}
            - Confidence: {f'{incident.rca.confidence*100:.0f}%' if incident.rca else 'N/A'}
            - Risk Level: {incident.rca.risk_level.value if incident.rca else 'medium'}

            Remediation Steps Executed:
            {steps_summary}

            Raw Alerts Captured:
            {alerts_summary}
        """).strip()

        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    def _generate_fallback_post_mortem(self, incident: Incident) -> str:
        """Deterministic scenario-tailored Post-Mortem generator for demo/offline mode."""
        tag = incident.scenario_tag
        opened = incident.opened_at.strftime("%H:%M:%S UTC")
        resolved = (
            incident.resolved_at.strftime("%H:%M:%S UTC")
            if incident.resolved_at
            else datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        )
        dur = f"{incident.duration_sec:.0f}s"
        primary = incident.primary_service or "core-service"
        all_services = ", ".join(incident.services) if incident.services else primary

        titles = {
            "A": "PostgreSQL Connection Saturation & Query Backlog",
            "B": "Memory Leak & Cascading Container Eviction in Worker Fleet",
            "C": "Cross-AZ Network Partition & Circuit Breaker Cascades",
            "D": "Database Persistent Volume Exhaustion via Unarchived WAL Chunks",
            "E": "Canary Rollout Crash Loop & Service Ingress Outage",
        }
        title = titles.get(tag, f"Transient Performance Degradation in {primary}")

        rc = (
            incident.rca.root_cause
            if incident.rca
            else f"Telemetry threshold violations detected on {primary}."
        )
        impact = (
            incident.rca.impact_summary
            if incident.rca
            else "Elevated latencies and temporary SLA degradation for downstream services."
        )

        steps_executed = ""
        if incident.rca and incident.rca.remediation_steps:
            for s in incident.rca.remediation_steps:
                status_symbol = "✅" if s.status == "executed" else "ℹ️"
                steps_executed += (
                    f"- {status_symbol} **`{s.command}`** ({s.tier or 'auto'}): {s.rationale}\n"
                    f"  - *Outcome:* {s.result_message or 'Successfully executed and validated.'}\n"
                )
        else:
            steps_executed = "- ✅ **`restart_pod`** (auto): Restored container health baseline.\n"

        timeline_rows = ""
        for i, a in enumerate(incident.alerts[:6]):
            t_str = a.timestamp.strftime("%H:%M:%S")
            timeline_rows += (
                f"| `{t_str}` | Detection | Alert fired: `{a.service}` - `{a.metric}={a.value}{a.unit}` | {a.severity.value} |\n"
            )
        timeline_rows += (
            f"| `{opened}` | Triage | Incident `{incident.name}` clustered and RCA triggered | P1/P2 |\n"
            f"| `{opened}` | Mitigation | Remediation plan executed via safety allow-list | Active |\n"
            f"| `{resolved}` | Verification | Closed-loop 5s telemetry health check PASSED | Nominal |\n"
            f"| `{resolved}` | Resolution | Incident closed; Post-Mortem generated | RESOLVED |\n"
        )

        recommendations = {
            "A": [
                ("P0", "Implement aggressive idle connection reaper timeout in PgBouncer pool", "Data Infra", "Sprint +1"),
                ("P1", "Deploy composite database indexes on slow query path detected in query logs", "Database Team", "Sprint +1"),
                ("P2", "Establish Prometheus alerts for DB connection utilization > 80%", "SRE Platform", "Sprint +2"),
            ],
            "B": [
                ("P0", "Inspect heap snapshot and patch V8 closure leak in checkout worker pipeline", "App Engineering", "Sprint +1"),
                ("P1", "Enforce horizontal pod autoscaler (HPA) scale triggers on memory RSS rate-of-rise", "Platform Team", "Sprint +1"),
                ("P2", "Add automated canary soak test stages in CI/CD pipeline prior to production release", "Release Ops", "Sprint +2"),
            ],
            "C": [
                ("P0", "Tune circuit breaker retry jitter and exponential backoff parameters", "Core Gateway Team", "Sprint +1"),
                ("P1", "Verify multi-AZ cross-connect routing redundancy with cloud infrastructure provider", "Network Ops", "Sprint +2"),
                ("P2", "Add synthetic canary traffic probes across all regional endpoints", "SRE Monitoring", "Sprint +2"),
            ],
            "D": [
                ("P0", "Configure automated PVC volume auto-expansion policies in Kubernetes storage class", "Platform Infra", "Sprint +1"),
                ("P1", "Shorten WAL archive retention window and enable continuous zstd log compression", "Database Team", "Sprint +1"),
                ("P2", "Implement low-disk watermarking alarms at 75% and 85% thresholds", "SRE Team", "Sprint +2"),
            ],
            "E": [
                ("P0", "Introduce automated rollback gate if canary error rate exceeds 0.5% during first 3 minutes", "Release Eng", "Sprint +1"),
                ("P1", "Audit deployment environment secrets schema to prevent missing configuration crashes", "Security & DevOps", "Sprint +1"),
                ("P2", "Add pre-flight health probe verification tests before traffic cutover", "QA / SRE", "Sprint +2"),
            ],
        }.get(tag, [
            ("P1", f"Audit baseline operational metrics and alerts for {primary}", "Service Team", "Sprint +1"),
            ("P2", "Review automated runbooks and allow-list safety constraints", "SRE Team", "Sprint +2"),
        ])

        rec_table = "| Priority | Preventative Action Item | Owner | Target Completion |\n|---|---|---|---|\n"
        for pri, item, owner, target in recommendations:
            rec_table += f"| **{pri}** | {item} | {owner} | {target} |\n"

        return textwrap.dedent(f"""
            # 📋 Incident Post-Mortem: {incident.name} — {title}

            **Incident ID:** `{incident.id}` &nbsp;|&nbsp; **Severity:** `{incident.severity.value}` &nbsp;|&nbsp; **Scenario:** `SCN-{tag or 'Ambient'}` &nbsp;|&nbsp; **Status:** `RESOLVED ✅`  
            **Services Affected:** `{all_services}` &nbsp;|&nbsp; **TTR (Time-to-Resolution):** `{dur}` &nbsp;|&nbsp; **Engine:** `MavFix SRE Copilot`

            ---

            ## 1. Executive Summary

            On `{incident.opened_at.strftime('%Y-%m-%d')}`, an incident was detected impacting **{primary}** and associated services ({all_services}).
            The incident began at **{opened}** and was successfully mitigated and verified resolved by **{resolved}** with a total duration of **{dur}**.

            - **Customer Impact:** {impact}
            - **Detection:** Automated anomaly detection fired `{incident.alert_count}` alerts which were clustered by the MavFix ML topology clusterer within seconds.
            - **Resolution:** Semi-autonomous remediation plan was enacted, executing automated safety actions and human-approved mitigations, followed by a 5-second closed-loop health verification window verifying metric stabilization.

            ---

            ## 2. Root Cause Analysis

            ### Technical Root Cause
            > {rc}

            ### 5-Whys Failure Analysis
            1. **Why did the service fail?** Downstream request timeouts and error rate spikes occurred across `{primary}`.
            2. **Why were requests timing out?** Processing threads and connection queues were exhausted waiting for backend dependencies.
            3. **Why were backend dependencies exhausted?** Saturated resource constraints (CPU/Memory/Connections/Disk) exceeded configured thresholds.
            4. **Why did resource consumption spike suddenly?** The workload burst or code regression triggered an unindexed path or resource leakage.
            5. **Why was this not mitigated earlier?** Pre-emptive throttling and circuit breaking limits were insufficiently tuned for burst capacity.

            ---

            ## 3. Incident Timeline

            | Time (UTC) | Phase | Event Description | Severity / Status |
            |---|---|---|---|
            {timeline_rows.strip()}

            ---

            ## 4. Remediation & Recovery Actions

            The SRE Copilot evaluated the incident context against the safety allow-list (`config/allow_list.yaml`) and executed the following mitigation plan:

            {steps_executed.strip()}

            ### Closed-Loop Health Verification
            - **Probe Executed:** `check_service_health('{primary}')`
            - **Verification Duration:** `5.0 seconds`
            - **Result:** `PASS` — All service telemetry returned within nominal operating bounds. Incident state automatically transitioned to `RESOLVED`.

            ---

            ## 5. Preventative Recommendations

            To prevent recurrence of this incident and improve MTTR, the following corrective actions have been assigned:

            {rec_table.strip()}

            ---
            *Report generated automatically by MavFix Genesis SRE Copilot on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}.*
        """).strip()
