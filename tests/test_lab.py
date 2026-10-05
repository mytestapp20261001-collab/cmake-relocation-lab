import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import lab

CMAKE = os.environ.get("CMAKE_LAB_EXECUTABLE", "cmake")


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {profile: lab.run_profile(profile, CMAKE) for profile in lab.PROFILES}

    def test_fixed_runs_real_consumer_before_and_after(self):
        result = self.results["fixed"]
        self.assertTrue(result["contract_passed"])
        for phase in ("original", "relocated"):
            self.assertEqual([x["phase"] for x in result[phase]["phases"]], ["configure", "build", "run"])
            self.assertEqual(result[phase]["phases"][-1]["output"], "relocation-value=144\n")

    def test_absolute_prefix_passes_baseline_then_fails_specific_path(self):
        result = self.results["absolute-prefix"]
        self.assertTrue(result["original"]["passed"])
        self.assertFalse(result["contract_passed"])
        self.assertTrue(result["expected_failure_observed"])
        final = result["relocated"]["phases"][-1]
        self.assertEqual(final["phase"], "configure")
        self.assertIn("original-install/include", final["output"])
        self.assertIn("non-existent path", final["output"])

    def test_missing_header_fails_during_compile(self):
        result = self.results["missing-header"]
        self.assertTrue(result["expected_failure_observed"])
        self.assertFalse(result["contract_passed"])
        self.assertEqual(result["relocated"]["phases"][-1]["phase"], "build")

    def test_missing_archive_fails_during_import(self):
        result = self.results["missing-library"]
        self.assertTrue(result["expected_failure_observed"])
        self.assertFalse(result["contract_passed"])
        self.assertIn("librelocation_fixture.a", result["relocated"]["phases"][-1]["output"])

    def test_every_profile_uses_requested_config_and_removes_old_paths(self):
        for result in self.results.values():
            with self.subTest(profile=result["profile"]):
                self.assertTrue(all(result["removed_original_paths"].values()))
                self.assertTrue(result["original"]["package_from_requested_prefix"])
                self.assertTrue(result["relocated"]["package_from_requested_prefix"])
                self.assertTrue(result["temporary_directory_removed"])
                self.assertTrue(result["source_unchanged"])
                self.assertTrue(result["demonstration_passed"])
                self.assertEqual(len(result["source_sha256"]), 6)

    def test_inherited_build_search_settings_do_not_change_result(self):
        poison = {"CMAKE_PREFIX_PATH": "/nonexistent-poison", "CMAKE_TOOLCHAIN_FILE": "/bad-toolchain",
                  "CMAKE_GENERATOR": "NoSuchGenerator", "MAKEFLAGS": "--bad-flag",
                  "CC": "/bin/false", "CPATH": "/nonexistent-headers", "LIBRARY_PATH": "/bad-libs"}
        with patch.dict(os.environ, poison):
            self.assertTrue(lab.run_profile("fixed", CMAKE)["contract_passed"])

    def test_wrong_compiled_value_cannot_pass_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture"
            shutil.copytree(lab.FIXTURE, fixture)
            source = fixture / "library/value.c"
            source.write_text(source.read_text().replace("return 137", "return 138"))
            with patch.object(lab, "FIXTURE", fixture):
                with self.assertRaises(lab.LabError) as caught:
                    lab.run_profile("fixed", CMAKE)
            self.assertEqual(caught.exception.kind, "baseline_failed")


class ContractTests(unittest.TestCase):
    def test_environment_allowlist_is_small(self):
        env = lab.isolated_env(Path("/owned/home"))
        self.assertEqual(set(env), {"PATH", "HOME", "TMPDIR", "LC_ALL", "TZ", "PYTHONDONTWRITEBYTECODE"})
        self.assertEqual(env["PATH"], "/usr/bin:/bin")

    def test_missing_tool_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(lab.LabError) as caught:
                lab.tools_for(Path(directory), "/does/not/exist/cmake")
        self.assertEqual(caught.exception.kind, "unsupported")

    def test_unsupported_platform_is_incomplete(self):
        with patch.object(lab.platform, "system", return_value="Windows"):
            with self.assertRaises(lab.LabError) as caught:
                lab.tools_for(Path("/tmp"), CMAKE)
        self.assertEqual(caught.exception.kind, "unsupported")

    def test_unknown_profile_rejected(self):
        with self.assertRaises(lab.LabError):
            lab.run_profile("arbitrary-project", CMAKE)

    def test_source_hashes_detect_content_change(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture"
            shutil.copytree(lab.FIXTURE, fixture)
            before = lab.source_hashes(fixture)
            (fixture / "library/value.h").write_text("changed\n")
            self.assertNotEqual(before, lab.source_hashes(fixture))

    def test_source_file_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture"
            shutil.copytree(lab.FIXTURE, fixture)
            path = fixture / "library/value.h"
            path.unlink()
            path.symlink_to(lab.FIXTURE / "library/value.h")
            with self.assertRaises(lab.LabError):
                lab.source_hashes(fixture)

    def test_missing_and_oversized_source_rejected(self):
        for mode in ("missing", "oversized"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                fixture = Path(directory) / "fixture"
                shutil.copytree(lab.FIXTURE, fixture)
                path = fixture / "library/value.h"
                if mode == "missing":
                    path.unlink()
                else:
                    path.write_bytes(b"x" * 16385)
                with self.assertRaises(lab.LabError):
                    lab.source_hashes(fixture)

    def test_stale_consumer_build_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with self.assertRaises(lab.LabError):
                lab.configure({}, path, path, [], {})

    def test_package_cache_requires_exact_selected_path(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            prefix = build / "moved prefix"
            cache = build / "CMakeCache.txt"
            self.assertFalse(lab.package_from_cache(build, prefix))
            cache.write_text("RelocationFixture_DIR:PATH=/wrong/package\n")
            self.assertFalse(lab.package_from_cache(build, prefix))
            cache.write_text("RelocationFixture_DIR:PATH=" + str(prefix / "lib/cmake/RelocationFixture") + "\n")
            self.assertTrue(lab.package_from_cache(build, prefix))

    def test_unexpected_failure_is_not_expected_control(self):
        wrong_failure = {"passed": False, "package_from_requested_prefix": True,
                         "phases": [{"phase": "configure", "exit_code": 1, "output": "unrelated failure"}]}
        real_consume = lab.consume
        calls = 0
        def consume_then_fail(*args):
            nonlocal calls
            calls += 1
            return real_consume(*args) if calls == 1 else wrong_failure
        with patch.object(lab, "consume", side_effect=consume_then_fail):
            result = lab.run_profile("absolute-prefix", CMAKE)
        self.assertFalse(result["expected_failure_observed"])
        self.assertFalse(result["demonstration_passed"])

    def test_successful_executable_with_wrong_value_is_failure(self):
        zero = {"exit_code": 0, "output": ""}
        wrong = {"exit_code": 0, "output": "relocation-value=145\n"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch.object(lab, "configure", return_value=zero), \
                 patch.object(lab, "package_from_cache", return_value=True), \
                 patch.object(lab, "command", side_effect=[zero, wrong]):
                result = lab.consume({"cmake": "cmake"}, path, path, path, {})
        self.assertFalse(result["passed"])

    def test_command_preserves_nonzero_and_combines_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = lab.command([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)"], root, lab.isolated_env(root))
        self.assertEqual(result["exit_code"], 7)
        self.assertIn("out", result["output"])
        self.assertIn("err", result["output"])

    def test_command_timeout_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(lab.LabError) as caught:
                lab.command([sys.executable, "-c", "import time; time.sleep(10)"], root, lab.isolated_env(root), timeout=0.05)
        self.assertEqual(caught.exception.kind, "timeout")

    def test_command_output_limit_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(lab.LabError) as caught:
                lab.command([sys.executable, "-c", "print('x' * 4096)"], root, lab.isolated_env(root), limit=100)
        self.assertEqual(caught.exception.kind, "output_limit")

    def test_command_missing_executable_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(lab.LabError) as caught:
                lab.command(["/not/a/tool"], root, lab.isolated_env(root))
        self.assertEqual(caught.exception.kind, "tool_error")

    def test_cli_incomplete_and_negative_exit_codes(self):
        for result, expected in (({"contract_passed": False}, 1), ({"contract_passed": True}, 0)):
            with patch.object(lab, "run_profile", return_value=result), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(lab.main([]), expected)
            self.assertEqual(json.loads(output.getvalue())["passed"], expected == 0)
        with patch.object(lab, "run_profile", side_effect=lab.LabError("unsupported", "test")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(lab.main([]), 2)
        self.assertFalse(json.loads(output.getvalue())["assessment_complete"])

    def test_demo_requires_every_control(self):
        for passing in (True, False):
            results = [{"demonstration_passed": True}] * 3 + [{"demonstration_passed": passing}]
            with patch.object(lab, "run_profile", side_effect=results), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(lab.main(["--demo"]), 0 if passing else 1)


if __name__ == "__main__":
    unittest.main()
