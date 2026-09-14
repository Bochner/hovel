from __future__ import annotations

import json
import stat
import tempfile
import unittest
import urllib.request
from pathlib import Path

from ci_summary import render
from ci_timing import label
from ci_audit import SafeRedirect
from configure_bazel_cache import configure, rc_path


class CIIntegrationTest(unittest.TestCase):
    def test_audit_does_not_forward_credentials_to_signed_log_downloads(self) -> None:
        request = urllib.request.Request("https://api.github.com/logs", headers={"Authorization": "Bearer secret"})
        redirected = SafeRedirect().redirect_request(request, None, 302, "", {}, "https://storage.example/log?signature=test")
        self.assertFalse(redirected.has_header("Authorization"))

    def test_task_labels_do_not_capture_credentials_or_runtime_arguments(self) -> None:
        self.assertEqual(label(["run", "--bazel-flag=--remote_header=SECRET", "//tool:run", "--", "SECRET"]), "run //tool:run")

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = {"HOME": str(self.root), "RUNNER_TEMP": str(self.root)}

    def test_authenticated_setup_keeps_secret_out_of_exported_environment(self) -> None:
        self.env["BUILDBUDDY_API_KEY"] = "synthetic-test-credential"
        values = configure(self.env)
        self.assertIn("--config=buildbuddy", values["HOVEL_BAZEL_ARGS"])
        self.assertIn("synthetic-test-credential", rc_path(self.env).read_text())
        self.assertNotIn("synthetic-test-credential", json.dumps(values))
        self.assertEqual(stat.S_IMODE(rc_path(self.env).stat().st_mode), 0o600)

    def test_fork_setup_retains_ci_metadata_without_remote_services(self) -> None:
        values = configure(self.env)
        self.assertEqual(values["HOVEL_BAZEL_ARGS"], "--config=github-actions --config=ci")
        self.assertNotIn("remote_header", rc_path(self.env).read_text())

    def test_rerun_removes_stale_credentials_and_restricts_permissions(self) -> None:
        configure(self.env | {"BUILDBUDDY_API_KEY": "old-key"})
        rc_path(self.env).chmod(0o644)
        configure(self.env)
        self.assertNotIn("old-key", rc_path(self.env).read_text())
        self.assertEqual(stat.S_IMODE(rc_path(self.env).stat().st_mode), 0o600)

    def test_rejects_credential_line_injection(self) -> None:
        with self.assertRaises(ValueError):
            configure(self.env | {"BUILDBUDDY_API_KEY": "key\nbuild --remote_executor=unexpected"})
        self.assertFalse(rc_path(self.env).exists())

    def test_does_not_follow_a_credential_file_symlink(self) -> None:
        other = self.root / "other"
        other.write_text("preserve")
        rc_path(self.env).symlink_to(other)
        with self.assertRaises(OSError):
            configure(self.env)
        self.assertEqual(other.read_text(), "preserve")

    def test_summary_links_completed_and_interrupted_builds_without_raw_options(self) -> None:
        values = configure(self.env | {"BUILDBUDDY_API_KEY": "key"})
        events = Path(values["HOVEL_BEP_DIR"]) / "1.json"
        invocation = "01234567-0123-0123-0123-012345678901"
        events.write_text("\n".join(json.dumps(event) for event in [
            {"started": {"uuid": invocation, "command": "test", "optionsDescription": "SECRET"}},
            {"structuredCommandLine": {"secret": "SECRET"}},
            {"finished": {"exitCode": {"name": "TESTS_FAILED"}}},
        ]) + "\n{partial")
        summary = render(values | {"JOB_STATUS": "failure"})
        self.assertIn("https://vibepwners.buildbuddy.io/invocation/" + invocation, summary)
        self.assertIn("TESTS_FAILED", summary)
        self.assertNotIn("SECRET", summary)
        events.write_text(json.dumps({"started": {"uuid": invocation, "command": "build"}}))
        self.assertIn("incomplete", render(values))

    def test_local_summary_does_not_link_unsent_invocations(self) -> None:
        values = configure(self.env)
        (Path(values["HOVEL_BEP_DIR"]) / "1.json").write_text(json.dumps({
            "started": {"uuid": "01234567-0123-0123-0123-012345678901", "command": "test"},
        }))
        self.assertNotIn("https://", render(values))


if __name__ == "__main__":
    unittest.main()
