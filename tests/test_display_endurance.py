import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import check_display_endurance as endurance


class ReportReplacementTests(unittest.TestCase):
    def test_transient_sharing_failure_replaces_complete_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            path.write_text('{"generation": 0}')
            replace = os.replace
            attempts = []

            def sharing_then_replace(source, destination):
                attempts.append(destination)
                if len(attempts) < 3:
                    self.assertEqual(json.loads(path.read_text()), {"generation": 0})
                    raise PermissionError("Sharing violation")
                replace(source, destination)

            with patch.object(endurance.os, "replace", side_effect=sharing_then_replace), patch.object(endurance.time, "sleep"):
                endurance.write_json(path, {"generation": 1})
            self.assertEqual(json.loads(path.read_text()), {"generation": 1})
            self.assertFalse(path.with_suffix(".pending").exists())

    def test_persistent_sharing_failure_is_bounded_and_preserves_previous_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            path.write_text('{"generation": 0}')
            with patch.object(endurance.os, "replace", side_effect=PermissionError("Denied")) as replace, patch.object(endurance.time, "sleep") as sleep:
                with self.assertRaises(PermissionError):
                    endurance.write_json(path, {"generation": 1})
            self.assertEqual(replace.call_count, 21)
            self.assertEqual(sleep.call_count, 20)
            self.assertEqual(json.loads(path.read_text()), {"generation": 0})
            self.assertEqual(json.loads(path.with_suffix(".pending").read_text()), {"generation": 1})

    @unittest.skipUnless(os.name == "nt", "Windows file sharing required")
    def test_actual_windows_reader_temporarily_blocks_report_replacement(self):
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            path.write_text('{"generation": 0}')
            handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
            self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
            timer = threading.Timer(.15, kernel.CloseHandle, args=(handle,))
            timer.start()
            try:
                endurance.write_json(path, {"generation": 1})
            finally:
                timer.join()
            self.assertEqual(json.loads(path.read_text()), {"generation": 1})


class FakeClock:
    def __init__(self):
        self.value = 100

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class DisplayEnduranceTests(unittest.TestCase):
    def test_due_actions_are_ordered_and_not_repeated(self):
        self.assertEqual(endurance.due_actions(299, set()), [])
        self.assertEqual(endurance.due_actions(720, {"update_1", "stop"}), ["restart", "update_2"])
        self.assertEqual(endurance.due_actions(1800, {name for _, name in endurance.SCHEDULE}), [])

    def test_only_transport_failures_overlapping_actual_outage_are_expected(self):
        sample = {"start": 599, "end": 601, "error": "ConnectionRefusedError"}
        self.assertEqual(endurance.classify_sample(sample, [[600, 665]]), "expected_outage")
        self.assertEqual(endurance.classify_sample({**sample, "end": 599.5}, [[600, 665]]), "unexpected_failure")
        for error in ["SSLCertVerificationError", "SSLError", "ValueError", "JSONDecodeError"]:
            self.assertEqual(endurance.classify_sample({**sample, "error": error}, [[600, 665]]), "unexpected_failure")
        self.assertEqual(endurance.classify_sample({"start": 602, "end": 603, "status": 503}, [[600, 665]]), "unexpected_failure")

    def test_schedule_runs_real_duration_with_actual_restart_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "control.txt").write_text("start")
            clock = FakeClock()
            fixture = SimpleNamespace(args=None, runtime=SimpleNamespace(check_running=lambda: None))
            fixture.stop = lambda: setattr(fixture, "runtime", None)
            def start():
                clock.sleep(2)
                fixture.runtime = SimpleNamespace(check_running=lambda: None)
            fixture.start = start
            report = {"output": folder, "actions": [], "resources": [], "outages": [], "generation": 0}
            with patch.object(endurance, "change_content", side_effect=[3, 4, 5]), patch.object(endurance, "write_json"):
                endurance.run_schedule(fixture, {}, report, clock.now, clock.sleep, lambda *args: [])
            self.assertTrue(report["schedule_completed"])
            self.assertGreaterEqual(report["elapsed"], 1800)
            self.assertEqual([item["action"] for item in report["actions"]], [name for _, name in endurance.SCHEDULE])
            self.assertGreaterEqual(report["outages"][0][1] - report["outages"][0][0], 61)
            self.assertGreaterEqual(len(report["resources"]), 29)

    def test_aborted_schedule_never_claims_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "control.txt").write_text("abort")
            report = {"output": folder, "schedule_completed": False}
            with self.assertRaises(KeyboardInterrupt):
                endurance.run_schedule(None, {}, report)
            self.assertFalse(report["schedule_completed"])

    def test_content_uses_existing_image_and_version_logic_and_preserves_restart(self):
        from tools.check_managed_https import fixture_factory
        with tempfile.TemporaryDirectory() as directory:
            factory = fixture_factory(Path(directory), "disposable-endurance-password")
            fixture = SimpleNamespace(runtime=SimpleNamespace(app=factory({})))
            first = endurance.change_content(fixture, 0)
            response = fixture.runtime.app.test_client().get("/api/events")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(endurance.valid_payload("/api/events", response.json))
            old_image = response.json["events"][0]["image_tv"]
            fixture.runtime.app = factory({})
            second = endurance.change_content(fixture, 1)
            self.assertEqual(second, first + 1)
            client = fixture.runtime.app.test_client()
            events = client.get("/api/events").json["events"]
            self.assertEqual(len(events), 3)
            self.assertNotEqual(events[0]["image_tv"], old_image)
            with client.get(events[0]["image_tv"]) as response:
                self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get(endurance.STATE_PATH).status_code, 404)

    def test_invalid_payload_is_rejected(self):
        for data in [{}, {"content_version": True}, {"content_version": "2"}, {"content_version": -1}]:
            self.assertFalse(endurance.valid_payload("/api/version", data))
        for data in [None, {}, {"events": []}, {"events": [None] * 3}]:
            self.assertFalse(endurance.valid_payload("/api/events", data))

    def test_fixture_state_requires_https_selected_peer_and_separate_capability(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(server_ip="192.168.1.165", client_ip="192.168.1.117", port=8443)
            state = {"began": None, "capability": "b" * 64}
            fixture = endurance.create_fixture(args, Path(directory), "isolated-state-password", state)
            app = fixture.app_factory({})
            client = app.test_client()
            settings = {"base_url": "https://192.168.1.165:8443", "environ_overrides": {"REMOTE_ADDR": args.client_ip}}
            self.assertEqual(client.get(endurance.STATE_PATH, **settings).status_code, 404)
            self.assertEqual(client.get(endurance.STATE_PATH, headers={"X-Display-Test": fixture.session}, **settings).status_code, 404)
            headers = {"X-Display-Test": state["capability"]}
            self.assertEqual(client.post(endurance.STATE_PATH, headers=headers, **settings).status_code, 404)
            self.assertEqual(client.get(endurance.STATE_PATH, headers=headers, base_url="http://192.168.1.165:8443", environ_overrides={"REMOTE_ADDR": args.client_ip}).status_code, 404)
            self.assertEqual(client.get(endurance.STATE_PATH, headers=headers, base_url=settings["base_url"], environ_overrides={"REMOTE_ADDR": args.server_ip}).status_code, 404)
            response = client.get(endurance.STATE_PATH, headers=headers, **settings)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {"elapsed": None})
            state["began"] = endurance.time.monotonic() - 3
            self.assertGreaterEqual(client.get(endurance.STATE_PATH, headers=headers, **settings).json["elapsed"], 3)

    def test_manifest_requires_independent_exact_digest_and_https_identity(self):
        manifest = {"schema_version": 1, "origin": "https://192.168.1.165:8443", "session": "a" * 32, "display_capability": "b" * 64}
        authority = SimpleNamespace(read_text=lambda **kwargs: "pem")
        import hashlib
        digest = hashlib.sha256(b"der").hexdigest()
        with patch.object(endurance.ssl, "PEM_cert_to_DER_cert", return_value=b"der"):
            self.assertEqual(endurance.validate_manifest(manifest, digest, authority).port, 8443)
            for wrong in [{**manifest, "origin": "http://192.168.1.165:8443"}, {**manifest, "origin": "https://192.168.1.165:8443/path"}, {**manifest, "session": "bad"}]:
                with self.assertRaises(ValueError):
                    endurance.validate_manifest(wrong, digest, authority)
            with self.assertRaises(ValueError):
                endurance.validate_manifest(manifest, "0" * 64, authority)

    def test_interrupted_client_writes_partial_report(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "session.json").write_text(json.dumps({"session": "a" * 32, "display_capability": "b" * 64}))
            args = SimpleNamespace(manifest=folder / "session.json", ca_sha256="digest", output=folder / "client.json")
            with patch.object(endurance, "validate_manifest"), patch.object(endurance.ssl, "SSLContext"), patch.object(endurance, "request_json", side_effect=KeyboardInterrupt):
                self.assertEqual(endurance.client_main(args), 1)
            report = json.loads(args.output.read_text())
            self.assertFalse(report["completed"])
            self.assertEqual(report["error"], "KeyboardInterrupt")

    def test_summary_requires_complete_coverage_generations_and_cleanup(self):
        samples = []
        for elapsed in range(0, 1800, 10):
            for route in ["/api/version", "/api/events"]:
                row = {"route": route, "start": elapsed, "end": elapsed + .1}
                if 600 <= elapsed < 665:
                    row["error"] = "ConnectionRefusedError"
                else:
                    row.update(status=200, valid=True)
                    if route == "/api/events":
                        row["generation"] = 0 if elapsed < 300 else 1 if elapsed < 720 else 2 if elapsed < 1500 else 3
                samples.append(row)
        server = {"session": "fixture", "outages": [[600, 665]], "schedule_completed": True, "elapsed": 1800,
                  "invalid_metadata": 0, "source_counts": {"client": 1}, "cleanup": {"managed_ok": True, "temporary_removed": True}}
        client = {"session": "fixture", "samples": samples, "completed": True, "elapsed": 1800, "alignment_uncertainty_seconds": .01}
        self.assertTrue(endurance.summarize(server, client)["automated_scope_passed"])
        for changed in [{**client, "completed": False}, {**client, "samples": samples[:20]}, {**client, "alignment_uncertainty_seconds": 3}]:
            self.assertFalse(endurance.summarize(server, changed)["automated_scope_passed"])
        self.assertFalse(endurance.summarize({**server, "cleanup": {}}, client)["automated_scope_passed"])
        with self.assertRaises(ValueError):
            endurance.summarize(server, {**client, "session": "another"})

    def test_server_startup_failure_cleans_owned_fixture_without_completion(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(server_ip="192.168.1.165", client_ip="192.168.1.117", port=8443, output=Path(directory) / "report", caddy=Path(__file__), pwsh=Path(__file__))
            fixture = Mock()
            fixture.prepare.side_effect = RuntimeError("Simulated startup failure")
            fixture.cleanups = [{"proxy_forced": False, "proxy_exit_code": 0, "backend_stopped": True, "temporary_removed": True}]
            with patch("tools.check_lan_https.validate_addresses", return_value=(args.server_ip, args.client_ip)), patch.object(endurance, "create_fixture", return_value=fixture):
                self.assertEqual(endurance.server_main(args), 1)
            fixture.stop.assert_called_once()
            report = json.loads((args.output / "server.json").read_text())
            self.assertFalse(report["schedule_completed"])
            self.assertEqual(report["error"], "RuntimeError")
            self.assertTrue(report["cleanup"]["temporary_removed"])

    def test_transport_deadline_includes_reading_body_and_closes_connection(self):
        from unittest.mock import Mock
        origin = SimpleNamespace(hostname="192.168.1.165", port=8443)
        connection = Mock()
        connection.getresponse.return_value.read1.return_value = b"{"
        with patch.object(endurance.http.client, "HTTPSConnection", return_value=connection), patch.object(endurance.time, "monotonic", side_effect=[0, 0, 0, 1, 11]):
            with self.assertRaises(TimeoutError):
                endurance.request_json(origin, object(), "/api/version")
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
