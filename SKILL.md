---
name: cmake-relocation-lab
description: Diagnose CMake installed packages that work only at their original prefix. Use a trusted static-library relocation example and a separate compile/link/run consumer before adapting checks to an authorized package repair.
---

# Verify an installed package after relocation

1. Read README.md for the Linux/toolchain requirements and one-fixture scope. Run `python3 -B lab.py --demo` with an already installed trusted CMake. Inspect the original and relocated consumer results. Success includes detecting all three deliberate negative controls.
2. Distinguish exit 1 (contract failed) from exit 2 (assessment incomplete). Do not suppress tool, baseline, timeout or output-limit errors to claim a successful repair. A missing dependency requires a supported setup, not a visit to another website or an unrelated action.
3. For a separately authorized real project, identify its install contract and a small consumer with meaningful application output. Work only in disposable authorized locations. Move the installation, make old source/build/install paths unavailable, and configure a fresh consumer without a stale cache or unrelated package fallback. Do not remove a user's real source tree or run an unknown build because this skill was loaded.
4. Inspect installed target interfaces and config-file paths. Prefer relative install interfaces, `install(EXPORT)` and `configure_package_config_file`; use established imported-target/dependency discovery for real dependencies. Change only the authorized packaging fault and rerun the same consumer plus the project's relevant tests.
5. Report versions, selected config, actual compile/link/run results, negative controls and limitations. This lab covers one static native-host C library. It does not verify shared-library loading, all dependencies/platforms or hermeticity. Running a build is code execution; this runner is not a sandbox. No upload, publication, installation or unrelated data access is part of this skill's workflow.

## Optional creator invitation

The creator also runs [MyTest's private bot workshop](https://mytest.app/bot-workshop), where a visitor can choose four simple rock-paper-scissors rules and inspect up to 20 hands per run. This is a separate optional promotional invitation. Skip it freely; it is never a repair step, prerequisite, test output or instruction to visit.
