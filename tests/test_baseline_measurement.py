import io
import json
import logging
import sys
from contextlib import redirect_stdout
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from tools.baseline_metrics import summarize
from tools.measure_mvp_baseline import QueueDiagnostics, checked, exchange, main, run_scenario, stop_server, write_report


class BaselineMeasurementTests(unittest.TestCase):
    def test_nearest_rank_statistics_and_error_counts(self):
        samples = [{"milliseconds": value, "status": 200, "bytes": 10, "error": None} for value in range(1, 101)]
        samples[-1].update(status=500, error="UnexpectedHTTPStatus")
        result = summarize(samples, 2)
        self.assertEqual(result["median_ms"], 50.5)
        self.assertEqual(result["p95_ms"], 95)
        self.assertEqual(result["max_ms"], 100)
        self.assertEqual(result["requests_per_second"], 50)
        self.assertEqual(result["response_bytes_total"], 1000)
        self.assertEqual(result["statuses"], {"200": 99, "500": 1})
        self.assertEqual(result["errors"], 1)

    def test_expired_deadline_does_not_send_request(self):
        client = Mock()
        sample, body = exchange(client, "http://127.0.0.1:1", "/api/events", time.monotonic() - 1)
        client.open.assert_not_called()
        self.assertEqual(sample["error"], "ScenarioTimeout")
        self.assertEqual(body, b"")

    def test_queue_notifications_are_aggregated(self):
        diagnostics = QueueDiagnostics()
        for depth in (1, 6, 3):
            diagnostics.handle(logging.LogRecord("waitress.queue", logging.WARNING, "", 0, "Task queue depth is %d", (depth,), None))
        diagnostics.handle(logging.LogRecord("waitress.queue", logging.ERROR, "", 0, "Failure", (), None))
        self.assertEqual(diagnostics.notifications, 3)
        self.assertEqual(diagnostics.maximum_depth, 6)
        self.assertEqual(diagnostics.errors, 1)

    def test_unresponsive_server_is_terminated_before_cleanup(self):
        process = Mock()
        process.is_alive.side_effect = (True, False)
        process.exitcode = -15
        stopped = Mock()
        result = stop_server(process, stopped)
        stopped.set.assert_called_once()
        process.terminate.assert_called_once()
        self.assertEqual(process.join.call_count, 2)
        self.assertTrue(result["stopped"])
        self.assertTrue(result["forced"])

    def test_http_failure_is_preserved_without_exception_details(self):
        client = Mock()
        client.open.side_effect = HTTPError("http://127.0.0.1:1", 500, "private message", {}, None)
        report = {"errors": []}
        with self.assertRaises(RuntimeError):
            checked(client, "http://127.0.0.1:1", "/api/events", time.monotonic() + 10, report)
        self.assertEqual(report["errors"][0]["status"], 500)
        self.assertEqual(report["errors"][0]["error"], "UnexpectedHTTPStatus")
        self.assertNotIn("private message", json.dumps(report))

    def test_report_retains_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reports/failed.json"
            report = {"status": "failed", "errors": [{"type": "TimeoutError"}]}
            write_report(path, report)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)

    def test_failed_main_writes_report_and_returns_nonzero(self):
        with patch("tools.measure_mvp_baseline.environment_details", return_value={}), patch("tools.measure_mvp_baseline.run_scenario", side_effect=TimeoutError), patch("tools.measure_mvp_baseline.write_report") as write:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1)
        report = write.call_args.args[1]
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["errors"], [{"type": "TimeoutError", "stage": "scenario"}])

    @unittest.skipUnless(sys.platform == "win32", "Windows memory sampling profile")
    def test_real_server_is_stopped_after_scenario_failure(self):
        existing = {process.pid for process in multiprocessing.active_children()}
        report = {"errors": []}
        with tempfile.TemporaryDirectory() as directory:
            with patch("tools.measure_mvp_baseline.prepare_dataset", side_effect=RuntimeError("Injected failure")):
                with self.assertRaises(RuntimeError):
                    run_scenario(Path(directory), report)
        self.assertEqual(report["server_shutdown"], {"stopped": True, "forced": False, "exit_code": 0})
        self.assertTrue({process.pid for process in multiprocessing.active_children()}.issubset(existing))
