#!/usr/bin/env python3
"""Execute one trusted static-library install/relocation contract on Linux."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixture"
FILES = (
    "library/CMakeLists.txt", "library/RelocationFixtureConfig.cmake.in",
    "library/value.h", "library/value.c", "consumer/CMakeLists.txt",
    "consumer/main.c",
)
PROFILES = ("fixed", "absolute-prefix", "missing-header", "missing-library")
EXPECTED_OUTPUT = "relocation-value=144\n"
TIMEOUT = 30
MAX_OUTPUT = 262144


class LabError(Exception):
    def __init__(self, kind, detail):
        self.kind, self.detail = kind, detail
        super().__init__(detail)


def command(argv, cwd, env, *, timeout=TIMEOUT, limit=MAX_OUTPUT):
    """Bound known subprocesses; this does not sandbox arbitrary build scripts."""
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True)
    except OSError as exc:
        raise LabError("tool_error", f"Cannot start {Path(argv[0]).name}: {exc.strerror}") from exc
    data = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LabError("timeout", "A subprocess exceeded its time limit")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        data.extend(chunk)
                        if len(data) > limit:
                            raise LabError("output_limit", "A subprocess exceeded its output limit")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LabError("timeout", "A subprocess exceeded its time limit")
            try:
                code = proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise LabError("timeout", "A subprocess exceeded its time limit") from exc
        return {"exit_code": code, "output": data.decode("utf-8", errors="replace")}
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        proc.stdout.close()


def require_success(result, phase):
    if result["exit_code"] != 0:
        raise LabError("command_failed", f"{phase} failed: {result['output'][:3000]}")
    return result["output"]


def isolated_env(home):
    # Excludes inherited CMAKE_*, compiler/include/linker paths and Make flags.
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home),
            "LC_ALL": "C", "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1"}


def source_hashes(root=None):
    root = FIXTURE if root is None else root
    hashes = {}
    for name in FILES:
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
            raise LabError("fixture_error", f"Missing, linked or oversized fixture: {name}")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def tools_for(home, cmake):
    if platform.system() != "Linux" or sys.version_info < (3, 12):
        raise LabError("unsupported", "Linux and Python 3.12+ are required")
    resolved = shutil.which(cmake)
    if not resolved:
        raise LabError("unsupported", "CMake is not installed; provide a trusted --cmake executable")
    tools = {"cmake": str(Path(resolved).absolute()),
             "cc": shutil.which("gcc", path="/usr/bin:/bin"),
             "make": shutil.which("make", path="/usr/bin:/bin")}
    if not tools["cc"] or not tools["make"]:
        raise LabError("unsupported", "GCC and GNU Make in /usr/bin or /bin are required")
    env = isolated_env(home)
    versions = {name: require_success(command([exe, "--version"], home, env), name).splitlines()[0]
                for name, exe in tools.items()}
    match = re.fullmatch(r"cmake version (\d+)\.(\d+)\.(\d+)(?:[-.].*)?", versions["cmake"])
    if not match or not ( (3, 31) <= tuple(map(int, match.groups()[:2])) < (5, 0) ):
        raise LabError("unsupported", "CMake 3.31 through 4.x is required")
    if not versions["make"].startswith("GNU Make ") or not versions["cc"].lower().startswith("gcc "):
        raise LabError("unsupported", "Only GCC and GNU Make are supported in this lab")
    versions.update(python=platform.python_version(), platform=platform.system(), machine=platform.machine())
    return tools, versions


def configure(tools, source, build, options, env):
    if build.exists():
        raise LabError("fixture_error", "A supposedly fresh build directory already exists")
    return command([tools["cmake"], "-S", str(source), "-B", str(build), "-G", "Unix Makefiles",
                    "-DCMAKE_C_COMPILER=" + tools["cc"], "-DCMAKE_MAKE_PROGRAM=" + tools["make"],
                    "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF",
                    "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF", *options], source.parent, env)


def package_from_cache(build, prefix):
    cache = build / "CMakeCache.txt"
    if not cache.is_file():
        return False
    values = [line.split("=", 1)[1] for line in cache.read_text(encoding="utf-8").splitlines()
              if line.startswith("RelocationFixture_DIR:PATH=")]
    return values == [str(prefix / "lib/cmake/RelocationFixture")]


def consume(tools, source, build, prefix, env):
    result = configure(tools, source, build, ["-DLAB_PREFIX=" + str(prefix)], env)
    phases = [{"phase": "configure", **result}]
    selected = package_from_cache(build, prefix)
    if result["exit_code"] == 0:
        result = command([tools["cmake"], "--build", str(build), "--parallel", "1"], source.parent, env)
        phases.append({"phase": "build", **result})
        if result["exit_code"] == 0:
            result = command([str(build / "consumer")], source.parent, env)
            phases.append({"phase": "run", **result})
    passed = selected and len(phases) == 3 and result["exit_code"] == 0 and result["output"] == EXPECTED_OUTPUT
    return {"package_from_requested_prefix": selected, "phases": phases, "passed": passed}


def run_profile(profile, cmake="cmake"):
    if profile not in PROFILES:
        raise LabError("fixture_error", "Unknown profile")
    before_hashes = source_hashes()
    with tempfile.TemporaryDirectory(prefix="cmake-relocation-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir()
        tools, versions = tools_for(home, cmake)
        env = isolated_env(home)
        source = root / "original-source"
        source.mkdir()
        consumer = root / "separate-consumer-source"
        consumer.mkdir()
        for name in FILES:
            section, leaf = name.split("/", 1)
            shutil.copyfile(FIXTURE / name, (source if section == "library" else consumer) / leaf)
        if profile == "absolute-prefix":
            path = source / "CMakeLists.txt"
            content = path.read_text(encoding="utf-8")
            marker = "$<INSTALL_INTERFACE:include>"
            if content.count(marker) != 1:
                raise LabError("fixture_error", "The single install-interface marker changed")
            path.write_text(content.replace(marker, "$<INSTALL_INTERFACE:${CMAKE_INSTALL_PREFIX}/include>"), encoding="utf-8")
        library_build = root / "original-build"
        original = root / "original-install"
        relocated = root / "relocated prefix with spaces"
        require_success(configure(tools, source, library_build, ["-DCMAKE_INSTALL_PREFIX=" + str(original)], env), "library configure")
        require_success(command([tools["cmake"], "--build", str(library_build), "--parallel", "1"], root, env), "library build")
        require_success(command([tools["cmake"], "--install", str(library_build)], root, env), "library install")
        original_consumer_build = root / "original-consumer-build"
        original_result = consume(tools, consumer, original_consumer_build, original, env)
        if not original_result["passed"]:
            raise LabError("baseline_failed", json.dumps(original_result, ensure_ascii=True)[:5000])

        original.rename(relocated)
        for owned in (source, library_build, original_consumer_build):
            shutil.rmtree(owned)
        absent = {"library_source": not source.exists(), "library_build": not library_build.exists(),
                  "original_install": not original.exists(), "original_consumer_build": not original_consumer_build.exists()}
        if not all(absent.values()):
            raise LabError("fixture_error", "An original fixture path remains")
        if profile == "missing-header":
            (relocated / "include/value.h").unlink()
        elif profile == "missing-library":
            (relocated / "lib/librelocation_fixture.a").unlink()
        relocated_result = consume(tools, consumer, root / "relocated-consumer-build", relocated, env)
        final = relocated_result["phases"][-1]
        expected_failure = False
        if profile == "absolute-prefix":
            expected_failure = (final["phase"] == "configure" and final["exit_code"] != 0
                                and str(original / "include") in final["output"]
                                and "non-existent path" in final["output"])
        elif profile == "missing-header":
            expected_failure = (final["phase"] == "build" and final["exit_code"] != 0
                                and "value.h" in final["output"] and "No such file" in final["output"])
        elif profile == "missing-library":
            expected_failure = (final["phase"] == "configure" and final["exit_code"] != 0
                                and str(relocated / "lib/librelocation_fixture.a") in final["output"]
                                and "does not exist" in final["output"])
        checks = {"original_consumer_passed": original_result["passed"],
                  "original_paths_absent": all(absent.values()),
                  "relocated_config_selected": relocated_result["package_from_requested_prefix"],
                  "relocated_consumer_passed": relocated_result["passed"]}
        demonstrated = all(checks.values()) if profile == "fixed" else (
            checks["original_consumer_passed"] and checks["original_paths_absent"]
            and checks["relocated_config_selected"] and expected_failure and not relocated_result["passed"])
        source_unchanged = source_hashes() == before_hashes
        if not source_unchanged:
            raise LabError("fixture_error", "Checked-in fixture changed during assessment")
        report = {"profile": profile, "versions": versions, "expected_output": EXPECTED_OUTPUT,
                  "source_sha256": before_hashes, "source_unchanged": source_unchanged,
                  "removed_original_paths": absent, "checks": checks,
                  "original": original_result, "relocated": relocated_result,
                  "expected_failure_observed": expected_failure,
                  "contract_passed": all(checks.values()), "demonstration_passed": demonstrated}
    report["temporary_directory_removed"] = not root.exists()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmake", default="cmake", help="Trusted installed CMake executable (default: PATH)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--profile", choices=PROFILES, default="fixed")
    group.add_argument("--demo", action="store_true", help="Require fixed success and all three expected negative outcomes")
    args = parser.parse_args(argv)
    try:
        reports = [run_profile(profile, args.cmake) for profile in (PROFILES if args.demo else (args.profile,))]
        passed = all(r["demonstration_passed"] if args.demo else r["contract_passed"] for r in reports)
        print(json.dumps({"mode": "demo" if args.demo else "contract", "passed": passed, "reports": reports}, ensure_ascii=True, indent=2))
        return 0 if passed else 1
    except (LabError, OSError) as exc:
        print(json.dumps({"passed": False, "assessment_complete": False,
                          "error": getattr(exc, "kind", "filesystem_error"), "detail": str(exc)}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
