"""Lightweight Prometheus-compatible metrics.

Exposes ``GET /api/metrics`` as a text/plain endpoint that can be scraped
by Prometheus.  No external dependencies — pure stdlib counters and histograms.

.. note::

    This is an **in-memory** implementation.  Metrics are lost on process
    restart and are not shared across worker/scheduler processes.  See
    `ai-note/METRICS_SPEC.md` for limitations and the future roadmap toward
    ``prometheus_client`` / OpenTelemetry.
"""

from __future__ import annotations

import re
from collections import defaultdict
from threading import Lock

# ---------------------------------------------------------------------------
# In-memory metric store
# ---------------------------------------------------------------------------

_lock = Lock()
_counters: dict[str, int] = defaultdict(int)
_histograms: dict[str, list[float]] = defaultdict(list)


def reset_metrics() -> None:
    """Reset all in-memory metrics.

    Clears both counters and histograms.  Primarily intended for testing;
    **not** safe to call in production while the server is serving traffic.
    """
    with _lock:
        _counters.clear()
        _histograms.clear()


def inc_counter(name: str, value: int = 1) -> None:
    """Increment a counter metric by *value*."""
    with _lock:
        _counters[name] += value


def observe_histogram(name: str, value: float) -> None:
    """Record an observation into a histogram."""
    with _lock:
        _histograms[name].append(value)


# ---------------------------------------------------------------------------
# Label escaping helpers  (Prometheus exposition format)
# ---------------------------------------------------------------------------

# Prometheus label names must match: [a-zA-Z_][a-zA-Z0-9_]*
_LABEL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _escape_label_value(value: str) -> str:
    r"""Escape a Prometheus label value.

    Per the `Prometheus exposition format specification
    <https://prometheus.io/docs/instrumenting/exposition_formats/>`_,
    backslash, double-quote, and newline characters inside label values
    must be escaped: ``\\`` → ``\\\\``, ``"`` → ``\\"``, ``\n`` → ``\\n``.

    Returns:
        Escaped string suitable for use inside double-quoted label values.
    """
    # Order matters — backslash first, then quote, then newline.
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    return value


def _fmt_metric(name: str, labels: dict[str, str] | None = None) -> str:
    """Build a fully-qualified Prometheus metric key.

    Label **names** are validated against ``[a-zA-Z_][a-zA-Z0-9_]*``.
    Label **values** are escaped via :func:`_escape_label_value` and
    always rendered inside double-quotes.

    Example::

        _fmt_metric("http_requests_total", {"method": "GET", "status": "200"})
        # → http_requests_total{method="GET",status="200"}

    Returns:
        The metric name unchanged when *labels* is empty/``None``.
    """
    if not labels:
        return name

    parts: list[str] = [name, "{"]
    first = True
    for k in sorted(labels):
        if not first:
            parts.append(",")
        first = False
        if not _LABEL_NAME_RE.match(k):
            raise ValueError(
                f"Invalid Prometheus label name: {k!r}. "
                f"Must match [a-zA-Z_][a-zA-Z0-9_]*"
            )
        parts.append(f'{k}="{_escape_label_value(str(labels[k]))}"')
    parts.append("}")
    return "".join(parts)


# ---------------------------------------------------------------------------
# HTTP request metrics
# ---------------------------------------------------------------------------


def record_request(
    method: str,
    path: str,
    status: int,
    latency_ms: float,
) -> None:
    """Record standard HTTP metrics for one request.

    Called by ``RequestTimingMiddleware`` on every request.
    """
    inc_counter(
        _fmt_metric(
            "http_requests_total",
            {"method": method, "path": path, "status": str(status)},
        )
    )
    observe_histogram(
        _fmt_metric("http_request_duration_ms", {"path": path}),
        latency_ms,
    )


# ---------------------------------------------------------------------------
# Tool / LLM / Steam API metrics
# ---------------------------------------------------------------------------


def record_tool_call(
    tool_name: str,
    status: str,
    latency_ms: float | None,
) -> None:
    """Record a tool-call metric."""
    inc_counter(
        _fmt_metric("tool_calls_total", {"tool": tool_name, "status": status})
    )
    if latency_ms is not None:
        observe_histogram(
            _fmt_metric("tool_call_duration_ms", {"tool": tool_name}),
            latency_ms,
        )


def record_llm_call(
    model: str,
    status: str,
    latency_ms: float | None,
    tokens: int = 0,
) -> None:
    """Record an LLM call metric."""
    inc_counter(
        _fmt_metric("llm_calls_total", {"model": model, "status": status})
    )
    if latency_ms is not None:
        observe_histogram(
            _fmt_metric("llm_call_duration_ms", {"model": model}),
            latency_ms,
        )
    if tokens > 0:
        inc_counter(
            _fmt_metric("llm_tokens_total", {"model": model}),
            tokens,
        )


def record_steam_api(
    endpoint: str,
    status: str,
    latency_ms: float | None,
) -> None:
    """Record a Steam API call metric."""
    inc_counter(
        _fmt_metric(
            "steam_api_calls_total", {"endpoint": endpoint, "status": status}
        )
    )
    if latency_ms is not None:
        observe_histogram(
            _fmt_metric("steam_api_duration_ms", {"endpoint": endpoint}),
            latency_ms,
        )


# ---------------------------------------------------------------------------
# New metric helpers  (not yet wired into business modules)
#
# These helpers produce valid Prometheus output and are safe to call from
# any module once integration work begins.  They deliberately do **not**
# import from services / agent / api to avoid circular imports.
# ---------------------------------------------------------------------------


def record_task_event(
    task_type: str,
    status: str,
    latency_ms: float | None = None,
) -> None:
    """Record a background task event.

    Intended for use by the task queue worker (``app/services/task_queue.py``).
    **Not yet wired in.**

    Parameters:
        task_type:
            Logical task category, e.g. ``"snapshot"``, ``"report"``,
            ``"web_sentiment"``.
        status:
            One of ``"started"``, ``"completed"``, ``"failed"``, ``"cancelled"``.
        latency_ms:
            Wall-clock duration of the task; omitted for ``"started"`` events.
    """
    inc_counter(
        _fmt_metric(
            "task_events_total", {"task_type": task_type, "status": status}
        )
    )
    if latency_ms is not None:
        observe_histogram(
            _fmt_metric(
                "task_event_duration_ms", {"task_type": task_type}
            ),
            latency_ms,
        )


def record_scheduler_event(
    job_name: str,
    status: str,
    latency_ms: float | None = None,
) -> None:
    """Record a scheduler job execution event.

    Intended for use by the APScheduler service
    (``app/services/scheduler_service.py``).  **Not yet wired in.**

    Parameters:
        job_name:
            APScheduler job id, e.g. ``"monitor_check_steam_online"``.
        status:
            One of ``"success"``, ``"error"``, ``"skipped"``.
        latency_ms:
            Wall-clock duration of the job execution.
    """
    inc_counter(
        _fmt_metric(
            "scheduler_events_total", {"job": job_name, "status": status}
        )
    )
    if latency_ms is not None:
        observe_histogram(
            _fmt_metric(
                "scheduler_event_duration_ms", {"job": job_name}
            ),
            latency_ms,
        )


def record_agent_run(
    agent_type: str,
    status: str,
    latency_ms: float | None = None,
    tokens: int = 0,
) -> None:
    """Record an agent run execution event.

    Intended for use by the agent runtime (``app/agent/runtime.py``).
    **Not yet wired in.**

    Parameters:
        agent_type:
            Agent variant, e.g. ``"chat"``, ``"review"``, ``"compare"``.
        status:
            One of ``"success"``, ``"error"``, ``"timeout"``.
        latency_ms:
            Wall-clock duration of the agent run.
        tokens:
            Total tokens consumed during the run (prompt + completion).
    """
    inc_counter(
        _fmt_metric(
            "agent_runs_total", {"agent": agent_type, "status": status}
        )
    )
    if latency_ms is not None:
        observe_histogram(
            _fmt_metric("agent_run_duration_ms", {"agent": agent_type}),
            latency_ms,
        )
    if tokens > 0:
        inc_counter(
            _fmt_metric("agent_tokens_total", {"agent": agent_type}),
            tokens,
        )


# ---------------------------------------------------------------------------
# Prometheus text format exporter
# ---------------------------------------------------------------------------


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Return the *pct*-th percentile from sorted values.

    Uses a simple rank-based (non-interpolated) approach that does not
    require ``statistics``.
    """
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    idx = int(n * pct)
    return sorted_vals[min(idx, n - 1)]


def render_metrics() -> str:
    """Render all collected metrics in Prometheus exposition format.

    Returns:
        A ``text/plain`` string suitable for ``GET /api/metrics``.
    """
    lines: list[str] = []
    with _lock:
        # ---- counters ----
        for name, value in sorted(_counters.items()):
            base = name.split("{")[0]
            lines.append(f"# TYPE {base} counter")
            lines.append(f"{name} {value}")

        # ---- histograms ----
        for name, values in sorted(_histograms.items()):
            base = name.split("{")[0]
            lines.append(f"# TYPE {base} histogram")
            if values:
                sv = sorted(values)
                n = len(sv)
                lines.append(f"{name}_count {n}")
                lines.append(f"{name}_sum {sum(sv):.2f}")
                lines.append(f"{name}_min {sv[0]:.2f}")
                lines.append(f"{name}_max {sv[-1]:.2f}")
                lines.append(f"{name}_p50 {_percentile(sv, 0.50):.2f}")
                lines.append(f"{name}_p95 {_percentile(sv, 0.95):.2f}")
                lines.append(f"{name}_p99 {_percentile(sv, 0.99):.2f}")
            else:
                # Prometheus best-practice: always emit _count and _sum
                # even for empty histograms so scrapers see a stable series.
                lines.append(f"{name}_count 0")
                lines.append(f"{name}_sum 0.00")

    if not lines:
        # No metrics recorded — return a single newline so the output
        # is a valid (empty) Prometheus exposition document.
        return "\n"

    lines.append("")
    # Always end with LF; `"\n".join` on [..., ""] produces a trailing newline.
    return "\n".join(lines)


def render_metrics_html() -> str:
    """Render a simple HTML dashboard showing current metrics."""
    with _lock:
        counters = dict(_counters)
        histograms = dict(_histograms)

    counter_rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>"
        for k, v in sorted(counters.items())
    )
    histogram_rows = "".join(
        "<tr>"
        f"<td>{k.split('{')[0]}</td>"
        f"<td>{len(v)}</td>"
        f"<td>{sum(v) / len(v):.1f}" if v else "<td>-"
        "</td></tr>"
        for k, v in sorted(histograms.items())
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Metrics</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
th, td {{ border: 1px solid #ddd; padding: 6px 12px; text-align: left; }}
th {{ background: #f5f5f5; }}
h2 {{ margin-top: 2rem; }}
</style>
</head>
<body>
<h1>SteamAnalysis Metrics</h1>
<h2>Counters</h2>
<table><tr><th>Name</th><th>Value</th></tr>{counter_rows or '<tr><td colspan="2">No data</td></tr>'}</table>
<h2>Histograms</h2>
<table><tr><th>Name</th><th>Count</th><th>Avg (ms)</th></tr>{histogram_rows or '<tr><td colspan="3">No data</td></tr>'}</table>
</body>
</html>"""
