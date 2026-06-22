"""Tests for the in-memory Prometheus metrics module.

Covers:
- Label value escaping
- Metric name formatting
- Counter / histogram recording and rendering
- Empty-metrics output
- Existing record_* helpers (API compatibility)
- New record_* helpers (task / scheduler / agent)
- reset_metrics
- Basic thread safety
- HTML dashboard rendering
"""

import re
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from app.core.metrics import (
    _escape_label_value,
    _fmt_metric,
    inc_counter,
    observe_histogram,
    record_agent_run,
    record_llm_call,
    record_request,
    record_scheduler_event,
    record_steam_api,
    record_task_event,
    record_tool_call,
    render_metrics,
    render_metrics_html,
    reset_metrics,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_metrics() -> Generator[None, None, None]:
    """Reset in-memory metrics before and after every test."""
    reset_metrics()
    yield
    reset_metrics()


# ---------------------------------------------------------------------------
# Label escaping
# ---------------------------------------------------------------------------


class TestLabelEscape:
    """Prometheus label value escaping rules."""

    def test_passthrough_plain_string(self) -> None:
        """Plain ASCII strings should be returned unchanged."""
        assert _escape_label_value("GET") == "GET"
        assert _escape_label_value("search_games") == "search_games"
        assert _escape_label_value("200") == "200"

    def test_escape_backslash(self) -> None:
        r"""Backslash must be doubled: \ → \\."""
        assert _escape_label_value(r"a\b") == r"a\\b"
        assert _escape_label_value(r"C:\path\to\file") == r"C:\\path\\to\\file"

    def test_escape_double_quote(self) -> None:
        """Double-quote must be escaped: " → \\"."""
        assert _escape_label_value('hello"world') == 'hello\\"world'
        assert _escape_label_value('"quoted"') == '\\"quoted\\"'

    def test_escape_newline(self) -> None:
        r"""Newline must be escaped: \n → \\n."""
        assert _escape_label_value("line1\nline2") == "line1\\nline2"

    def test_escape_combined(self) -> None:
        """All three escape sequences combined."""
        original = 'path\\to\n"file"'
        expected = 'path\\\\to\\n\\"file\\"'
        assert _escape_label_value(original) == expected

    def test_unicode_passthrough(self) -> None:
        """Unicode characters (non-control) should pass through unmodified."""
        assert _escape_label_value("游戏") == "游戏"
        assert _escape_label_value("résumé") == "résumé"
        assert _escape_label_value("/api/games/730") == "/api/games/730"


class TestFmtMetric:
    """Metric string formatting with labels."""

    def test_no_labels(self) -> None:
        """A metric without labels is returned verbatim."""
        assert _fmt_metric("my_counter") == "my_counter"
        assert _fmt_metric("my_counter", {}) == "my_counter"

    def test_single_label(self) -> None:
        result = _fmt_metric("http_requests_total", {"method": "GET"})
        assert result == 'http_requests_total{method="GET"}'

    def test_multiple_labels_sorted(self) -> None:
        """Labels must be sorted alphabetically for deterministic output."""
        result = _fmt_metric(
            "http_requests_total",
            {"status": "200", "method": "GET", "path": "/api/games"},
        )
        assert result == (
            'http_requests_total{'
            'method="GET",'
            'path="/api/games",'
            'status="200"'
            '}'
        )

    def test_labels_with_special_chars_escaped(self) -> None:
        """Label values containing dangerous chars are escaped."""
        result = _fmt_metric(
            "test_metric",
            {"key": 'has"quote', "path": r"C:\dir"},
        )
        assert '\\"' in result
        assert "\\\\" in result

    def test_invalid_label_name_raises(self) -> None:
        """Label names that don't match [a-zA-Z_][a-zA-Z0-9_]* must raise."""
        with pytest.raises(ValueError, match="Invalid Prometheus label name"):
            _fmt_metric("test", {"1invalid": "val"})

        with pytest.raises(ValueError, match="Invalid Prometheus label name"):
            _fmt_metric("test", {"has-dash": "val"})

        with pytest.raises(ValueError, match="Invalid Prometheus label name"):
            _fmt_metric("test", {"": "val"})


# ---------------------------------------------------------------------------
# Counter operations
# ---------------------------------------------------------------------------


class TestCounter:
    """Counter recording and rendering."""

    def test_basic_inc(self) -> None:
        inc_counter("test_total")
        output = render_metrics()
        assert "test_total 1" in output
        assert "# TYPE test_total counter" in output

    def test_multiple_inc(self) -> None:
        for _ in range(3):
            inc_counter("test_total")
        output = render_metrics()
        assert "test_total 3" in output

    def test_inc_with_value(self) -> None:
        inc_counter("test_total", value=5)
        inc_counter("test_total", value=3)
        output = render_metrics()
        assert "test_total 8" in output

    def test_counter_with_labels(self) -> None:
        inc_counter(_fmt_metric("http_requests_total", {"method": "GET", "status": "200"}))
        inc_counter(_fmt_metric("http_requests_total", {"method": "GET", "status": "200"}))
        inc_counter(_fmt_metric("http_requests_total", {"method": "POST", "status": "201"}))
        output = render_metrics()

        assert 'http_requests_total{method="GET",status="200"} 2' in output
        assert 'http_requests_total{method="POST",status="201"} 1' in output

    def test_multiple_counters_rendered(self) -> None:
        inc_counter("counter_a", 1)
        inc_counter("counter_b", 10)
        output = render_metrics()

        assert "counter_a 1" in output
        assert "counter_b 10" in output
        assert "# TYPE counter_a counter" in output
        assert "# TYPE counter_b counter" in output

    def test_counter_output_ends_with_newline(self) -> None:
        """Prometheus exposition format requires a trailing newline."""
        inc_counter("test_total")
        output = render_metrics()
        assert output.endswith("\n")


# ---------------------------------------------------------------------------
# Histogram operations
# ---------------------------------------------------------------------------


class TestHistogram:
    """Histogram recording and rendering."""

    def test_observe_single(self) -> None:
        observe_histogram("test_latency", 42.0)
        output = render_metrics()

        assert "# TYPE test_latency histogram" in output
        assert "test_latency_count 1" in output
        assert "test_latency_sum 42.00" in output
        assert "test_latency_min 42.00" in output
        assert "test_latency_max 42.00" in output

    def test_observe_multiple_percentiles(self) -> None:
        """Verify p50 / p95 / p99 percentiles with a known distribution."""
        values = list(range(1, 101))  # 1..100
        for v in values:
            observe_histogram("test_latency", float(v))
        output = render_metrics()

        assert "test_latency_count 100" in output
        assert "test_latency_sum 5050.00" in output  # sum(1..100) = 5050
        assert "test_latency_min 1.00" in output
        assert "test_latency_max 100.00" in output
        # p50 of 1..100: index = int(100 * 0.50) = 50 → sorted_vals[50] = 51
        assert "test_latency_p50 51.00" in output
        # p95: index = int(100 * 0.95) = 95 → sorted_vals[95] = 96
        assert "test_latency_p95 96.00" in output
        # p99: index = min(int(100 * 0.99), 99) = 99 → sorted_vals[99] = 100
        assert "test_latency_p99 100.00" in output

    def test_histogram_with_labels(self) -> None:
        metric_key = _fmt_metric("http_request_duration_ms", {"path": "/api/games"})
        observe_histogram(metric_key, 10.0)
        observe_histogram(metric_key, 20.0)

        output = render_metrics()
        assert 'http_request_duration_ms{path="/api/games"}_count 2' in output
        assert 'http_request_duration_ms{path="/api/games"}_sum 30.00' in output

    def test_histogram_percentile_single_value(self) -> None:
        """With a single observation, all percentiles equal that value."""
        observe_histogram("latency", 55.5)
        output = render_metrics()
        assert "latency_p50 55.50" in output
        assert "latency_p95 55.50" in output
        assert "latency_p99 55.50" in output


# ---------------------------------------------------------------------------
# Empty metrics
# ---------------------------------------------------------------------------


class TestEmptyMetrics:
    """Rendering when no metrics have been recorded."""

    def test_empty_render_returns_trailing_newline_only(self) -> None:
        output = render_metrics()
        # Should be just a trailing newline (no TYPE lines, no data lines)
        assert output == "\n"

    def test_empty_render_is_stable(self) -> None:
        """Calling render_metrics twice with no data gives same result."""
        out1 = render_metrics()
        out2 = render_metrics()
        assert out1 == out2 == "\n"

    def test_empty_html_dashboard(self) -> None:
        html = render_metrics_html()
        assert "No data" in html
        assert "<title>Metrics</title>" in html


# ---------------------------------------------------------------------------
# Existing record_* helpers — API compatibility
# ---------------------------------------------------------------------------


class TestRecordRequest:
    """``record_request()`` integration."""

    def test_basic(self) -> None:
        record_request("GET", "/api/games", 200, 12.5)
        output = render_metrics()

        assert 'http_requests_total{method="GET",path="/api/games",status="200"} 1' in output
        assert 'http_request_duration_ms{path="/api/games"}_count 1' in output

    def test_multiple_statuses(self) -> None:
        record_request("GET", "/api/games", 200, 5.0)
        record_request("POST", "/api/games", 201, 15.0)
        record_request("GET", "/api/games", 404, 8.0)
        output = render_metrics()

        assert 'status="200"}' in output
        assert 'status="201"}' in output
        assert 'status="404"}' in output

    def test_path_with_special_chars(self) -> None:
        """Paths containing characters that need escaping should still render."""
        # A path with a backslash is unlikely in HTTP but must be handled.
        record_request("GET", "/api/games/730/details", 200, 3.0)
        output = render_metrics()
        assert "/api/games/730/details" in output


class TestRecordToolCall:
    """``record_tool_call()`` integration."""

    def test_basic(self) -> None:
        record_tool_call("search_games", "success", 45.0)
        output = render_metrics()

        # Labels are sorted alphabetically: status < tool
        assert 'tool_calls_total{status="success",tool="search_games"} 1' in output
        assert 'tool_call_duration_ms{tool="search_games"}_count 1' in output

    def test_error_status(self) -> None:
        record_tool_call("search_games", "error", None)
        output = render_metrics()

        assert 'tool_calls_total{status="error",tool="search_games"} 1' in output
        # No histogram when latency is None
        assert "tool_call_duration_ms" not in output


class TestRecordLlmCall:
    """``record_llm_call()`` integration."""

    def test_basic(self) -> None:
        record_llm_call("deepseek-v4", "success", 250.0, tokens=150)
        output = render_metrics()

        assert 'llm_calls_total{model="deepseek-v4",status="success"} 1' in output
        assert 'llm_call_duration_ms{model="deepseek-v4"}_count 1' in output
        assert 'llm_tokens_total{model="deepseek-v4"} 150' in output

    def test_no_tokens(self) -> None:
        record_llm_call("deepseek-v4", "success", 100.0)
        output = render_metrics()
        assert "llm_tokens_total" not in output

    def test_error_without_latency(self) -> None:
        record_llm_call("deepseek-v4", "error", None)
        output = render_metrics()
        assert 'status="error"' in output
        assert "llm_call_duration_ms" not in output


class TestRecordSteamApi:
    """``record_steam_api()`` integration."""

    def test_basic(self) -> None:
        record_steam_api("appdetails", "success", 320.0)
        output = render_metrics()

        assert 'steam_api_calls_total{endpoint="appdetails",status="success"} 1' in output
        assert 'steam_api_duration_ms{endpoint="appdetails"}_count 1' in output

    def test_timeout_status(self) -> None:
        record_steam_api("appdetails", "timeout", None)
        output = render_metrics()

        assert 'status="timeout"' in output
        assert "steam_api_duration_ms" not in output


# ---------------------------------------------------------------------------
# New record_* helpers — task / scheduler / agent
# ---------------------------------------------------------------------------


class TestRecordTaskEvent:
    """``record_task_event()`` — not yet wired in."""

    def test_started_event(self) -> None:
        record_task_event("snapshot", "started")
        output = render_metrics()

        assert 'task_events_total{status="started",task_type="snapshot"} 1' in output
        # No duration for start events
        assert "task_event_duration_ms" not in output

    def test_completed_event_with_latency(self) -> None:
        record_task_event("report", "completed", latency_ms=5200.0)
        output = render_metrics()

        assert 'task_events_total{status="completed",task_type="report"} 1' in output
        assert 'task_event_duration_ms{task_type="report"}_count 1' in output
        assert "task_event_duration_ms" in output

    def test_failed_event(self) -> None:
        record_task_event("web_sentiment", "failed", latency_ms=1500.0)
        output = render_metrics()

        assert 'task_events_total{status="failed",task_type="web_sentiment"} 1' in output
        assert 'task_event_duration_ms{task_type="web_sentiment"}' in output


class TestRecordSchedulerEvent:
    """``record_scheduler_event()`` — not yet wired in."""

    def test_success(self) -> None:
        record_scheduler_event("monitor_check_steam_online", "success", latency_ms=800.0)
        output = render_metrics()

        assert 'scheduler_events_total{job="monitor_check_steam_online",status="success"} 1' in output
        assert 'scheduler_event_duration_ms{job="monitor_check_steam_online"}_count 1' in output

    def test_error_skipped(self) -> None:
        record_scheduler_event("monitor_daily_snapshot", "error", latency_ms=0.0)
        record_scheduler_event("monitor_daily_snapshot", "skipped")
        output = render_metrics()

        assert 'status="error"' in output
        assert 'status="skipped"' in output

    def test_skipped_no_latency(self) -> None:
        record_scheduler_event("job_x", "skipped")
        output = render_metrics()
        assert "scheduler_event_duration_ms" not in output


class TestRecordAgentRun:
    """``record_agent_run()`` — not yet wired in."""

    def test_success_with_tokens(self) -> None:
        record_agent_run("chat", "success", latency_ms=3500.0, tokens=1200)
        output = render_metrics()

        assert 'agent_runs_total{agent="chat",status="success"} 1' in output
        assert 'agent_run_duration_ms{agent="chat"}_count 1' in output
        assert 'agent_tokens_total{agent="chat"} 1200' in output

    def test_timeout_no_tokens(self) -> None:
        record_agent_run("compare", "timeout", latency_ms=30000.0)
        output = render_metrics()

        assert 'agent_runs_total{agent="compare",status="timeout"} 1' in output
        assert "agent_tokens_total" not in output


# ---------------------------------------------------------------------------
# reset_metrics
# ---------------------------------------------------------------------------


class TestResetMetrics:
    """``reset_metrics()`` clears all stored data."""

    def test_clears_counters(self) -> None:
        inc_counter("test", 5)
        reset_metrics()
        assert render_metrics() == "\n"

    def test_clears_histograms(self) -> None:
        observe_histogram("latency", 42.0)
        reset_metrics()
        assert render_metrics() == "\n"

    def test_clears_both(self) -> None:
        inc_counter("a", 1)
        observe_histogram("b", 1.0)
        record_request("GET", "/api/x", 200, 5.0)
        reset_metrics()
        assert render_metrics() == "\n"

    def test_after_reset_fresh_recording_works(self) -> None:
        inc_counter("old", 1)
        reset_metrics()
        inc_counter("new", 1)
        output = render_metrics()
        assert "old" not in output
        assert "new 1" in output


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Basic concurrent access does not corrupt counters."""

    def test_concurrent_counter_incs(self) -> None:
        n_threads = 8
        n_per_thread = 250

        def _inc_many() -> None:
            for _ in range(n_per_thread):
                inc_counter("concurrent_total")

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            futures = [pool.submit(_inc_many) for _ in range(n_threads)]
            for f in as_completed(futures):
                f.result()

        output = render_metrics()
        assert f"concurrent_total {n_threads * n_per_thread}" in output

    def test_concurrent_histogram_observations(self) -> None:
        n_threads = 4
        n_per_thread = 100

        def _observe_many() -> None:
            for i in range(n_per_thread):
                observe_histogram("concurrent_latency", float(i))

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            futures = [pool.submit(_observe_many) for _ in range(n_threads)]
            for f in as_completed(futures):
                f.result()

        output = render_metrics()
        assert f"concurrent_latency_count {n_threads * n_per_thread}" in output

    def test_mixed_concurrent_access(self) -> None:
        """Counters and histograms updated concurrently should be consistent."""

        def _mixed() -> None:
            for i in range(50):
                inc_counter("mixed_total")
                observe_histogram("mixed_latency", float(i))

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_mixed) for _ in range(4)]
            for f in as_completed(futures):
                f.result()

        output = render_metrics()
        assert "mixed_total 200" in output
        assert "mixed_latency_count 200" in output


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


class TestHtmlDashboard:
    """``render_metrics_html()`` smoke tests."""

    def test_returns_html_with_counter(self) -> None:
        inc_counter("test_total", 42)
        html = render_metrics_html()

        assert "<!DOCTYPE html>" in html
        assert "<title>Metrics</title>" in html
        assert "test_total" in html
        assert "42" in html
        # Counter table populated (no "No data" in the counters section)
        counter_section = html.split("<h2>Counters</h2>")[1].split("<h2>Histograms</h2>")[0]
        assert "No data" not in counter_section

    def test_returns_html_with_histogram(self) -> None:
        observe_histogram("test_latency", 10.0)
        observe_histogram("test_latency", 20.0)
        html = render_metrics_html()

        assert "test_latency" in html
        assert "2" in html  # count
        assert "15.0" in html  # avg

    def test_no_data_when_empty(self) -> None:
        html = render_metrics_html()
        assert "No data" in html


# ---------------------------------------------------------------------------
# Output format sanity
# ---------------------------------------------------------------------------


class TestOutputFormat:
    """Prometheus exposition format structural checks."""

    def test_type_lines_precede_data(self) -> None:
        inc_counter("foo_total")
        observe_histogram("bar_latency", 1.0)

        output = render_metrics()
        lines = output.strip().split("\n")

        type_lines = [ln for ln in lines if ln.startswith("# TYPE")]
        data_lines = [ln for ln in lines if not ln.startswith("#")]

        assert len(type_lines) >= 1
        assert len(data_lines) >= 1
        # Every TYPE line should appear before its data line
        for tln in type_lines:
            type_idx = lines.index(tln)
            base = tln.split()[2]
            data_indices = [
                i
                for i, dln in enumerate(lines)
                if dln.startswith(base) and not dln.startswith("#")
            ]
            for di in data_indices:
                assert type_idx < di, f"TYPE line for {base} must precede its data"

    def test_no_duplicate_type_for_same_base(self) -> None:
        """Multiple counters with same base name (different labels) should have
        at least one TYPE line.  Prometheus accepts duplicates; we just check
        the format is parseable."""
        inc_counter(_fmt_metric("http_requests_total", {"method": "GET", "status": "200"}))
        inc_counter(_fmt_metric("http_requests_total", {"method": "POST", "status": "201"}))
        output = render_metrics()

        # Both data lines present
        assert 'method="GET",status="200"}' in output
        assert 'method="POST",status="201"}' in output

    def test_prometheus_parseable_structure(self) -> None:
        """Output lines (except TYPE/empty) must match: <name>{labels} <value>."""
        inc_counter("test_counter")
        inc_counter(_fmt_metric("test_labeled", {"x": "y"}))
        observe_histogram("test_hist", 1.0)

        output = render_metrics()
        data_pattern = re.compile(
            r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"  # metric name
            r"(?:\{[^}]*\})?"  # optional labels
            r"\s+(?P<value>\S+)$"  # value
        )
        for line in output.strip().split("\n"):
            if line.startswith("#") or line == "":
                continue
            assert data_pattern.match(line), f"Unparseable line: {line!r}"
