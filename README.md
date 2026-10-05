# CMake relocation lab

**An installed library can work until its installation directory moves.** This executable repair example catches that error by moving a real static C library, removing its original source/build/install locations, and compiling and running a separate consumer.

It is one original synthetic fixture with a correct package and three negative controls. It does not scan or modify your project and is not another package manager.

## Run the example

Requirements: Linux, Python 3.12+, CMake 3.31–4.x, GCC and GNU Make. GCC and Make must be in `/usr/bin` or `/bin`. The two exact CMake versions used by this release's test matrix are **3.31.10** and **4.4.4**. Other versions in the accepted range are not individually verified.

```sh
python3 -B lab.py --demo
python3 -B lab.py                            # repaired package: exit 0
python3 -B lab.py --profile absolute-prefix  # relocation fails: exit 1
python3 -B -m unittest discover -s tests -v
```

If CMake is elsewhere, pass its trusted executable with `--cmake /absolute/path/to/cmake`. Tests use `CMAKE_LAB_EXECUTABLE` for the same purpose. Do not point either at untrusted code. The lab never installs dependencies. An optional isolated setup using [CMake's officially listed PyPI distribution](https://cmake.org/download/) is:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: --no-deps cmake==4.4.4
.venv/bin/python -B lab.py --cmake .venv/bin/cmake --demo
CMAKE_LAB_EXECUTABLE="$PWD/.venv/bin/cmake" .venv/bin/python -B -m unittest discover -s tests -v
```

Dependency provisioning needs a network connection; running the example after provisioning does not. No Ninja, Docker, registry account, external C library or production data is needed.

The meaningful result is:

| Profile | Original installation | After relocation and removal of original paths |
|---|---|---|
| `fixed` | Compiles, links, prints `relocation-value=144` | Compiles, links, prints the same exact value |
| `absolute-prefix` | Same successful result | Configure/generate fails because the exported include path still names the old prefix |
| `missing-header` | Same successful result | Build fails because the moved package has no `value.h` |
| `missing-library` | Same successful result | Configuration fails because the exported static library is absent |

The last two controls intentionally remove one installed file **after** the successful baseline. They verify that a missing deliverable cannot be rescued by the old tree or a previous consumer build.

All runs print ASCII-escaped JSON. Exit 0 means the requested contract passed; exit 1 means it did not. In `--demo`, exit 0 means the repaired package passed **and all three broken controls failed at their expected stages for their expected reasons**. It does not mean the broken packages are usable. Exit 2 means an environment, setup, baseline, filesystem or subprocess-bound error prevented a complete assessment. Argument errors use normal argparse stderr/exit 2.

## The mistake and repair

The checked-in library is the repaired version. Its installed interface uses a relative include directory:

```cmake
target_include_directories(relocation_fixture PUBLIC
  "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>"
  "$<INSTALL_INTERFACE:include>")
```

The `absolute-prefix` control changes only the second generator expression to:

```cmake
"$<INSTALL_INTERFACE:${CMAKE_INSTALL_PREFIX}/include>"
```

This produces a usable package at its original prefix, but its exported include path points back to that location after relocation. The library otherwise uses ordinary `install(TARGETS)`, `install(EXPORT)` and `configure_package_config_file`. No CMake parser, package resolver or path-repair algorithm is reimplemented.

## What is actually verified

Each profile:

1. Copies the six trusted fixture files into a unique owned temporary directory
2. Configures, builds and installs the static library
3. Builds an independent consumer against that original install and requires its exact output, `relocation-value=144` (137 from the compiled library plus 7 from its installed header)
4. Moves the installation into `relocated prefix with spaces`; removes the original library source, library build, install location and first consumer build
5. Uses a fresh consumer build directory and runs configure → build → executable against only the moved package, stopping at the first failure
6. Checks the selected package configuration path, expected output or specific negative diagnostic, fixture hashes and temporary-directory cleanup

The consumer uses `find_package(... CONFIG ... NO_DEFAULT_PATH)` with the explicit fixture prefix. Both user/system package registries are disabled. Children receive an isolated HOME and a small environment without inherited `CMAKE_*`, Make flags or compiler search-path overrides. JSON includes actual tool versions, per-phase exit codes/logs, selected-prefix checks and old-path absence checks. Configure/generate is one CMake invocation, so the report labels that whole phase `configure`.

Only library source/build/install paths disappear. The separately copied consumer's own source remains available, because it must be compiled. Scratch paths in reports are ephemeral and are removed before return. The runner does not accept an existing project or an output-directory argument.

Each subprocess has a 30-second and 256-KiB combined-output limit. This is **not a security sandbox or a proof of hermeticity**: the host compiler, C runtime and tools remain available; no CPU, filesystem, memory or network isolation is promised. Run only this trusted fixture. A modified CMake project can execute arbitrary commands. The bounded runner is not offered as a general command executor.

## Apply the lesson

For an authorized real package, test a disposable installation through a separate consumer before and after moving its prefix. Make the old package's source/build/install paths unavailable and start with a fresh consumer cache. Assert a meaningful compile/link/run result, not merely the absence of absolute-looking strings. Verify exactly which package was selected.

Prefer relative install interfaces and CMake's package helpers. If your real package has dependencies, use imported targets and the appropriate dependency-discovery mechanism; that additional behavior is outside this fixture. Preserve the project's actual install layout rather than blindly copying this example's fixed `lib` and `include` directories.

## Scope, prior art and maintenance

Initial local environment: Linux x86_64, GCC 14.2.0, GNU Make 4.4.1 and Python 3.12.14. CI uses Ubuntu 24.04 and records its actual compiler/Make versions with the two pinned CMake versions. A version range describes admission, not exhaustive compatibility.

This release stops at one static native-host library with no external dependencies. It does not establish shared-library loader behavior, cross-compilation, multi-config generators, Windows/macOS support, dependency relocation, arbitrary install-prefix overrides, ABI compatibility or whole-application correctness. Active corpus expansion stops here. Reproducible defects or concrete integration needs may justify a bounded maintenance change; silence is not evidence of failure or adoption.

- [CMake importing/exporting and relocatable packages](https://cmake.org/cmake/help/latest/guide/importing-exporting/index.html#creating-relocatable-packages) define the mechanism used here
- [CMake package config helpers](https://cmake.org/cmake/help/latest/module/CMakePackageConfigHelpers.html) support relocatable configuration generation
- [CMake find_package](https://cmake.org/cmake/help/latest/command/find_package.html) documents config selection and search controls
- [Conan test_package](https://docs.conan.io/2.28/reference/conanfile/methods/test.html) already supports consumer-based package testing

Use those established mechanisms. This lab contributes a small executable failing/fixed relocation contract, with actual downstream output and negative controls. It makes no claim of novelty, demand or independent usage.

## Optional creator invitation

This utility is made by the creator of [MyTest](https://mytest.app). If you want a separate game, the [private bot workshop](https://mytest.app/bot-workshop) lets you choose four rock-paper-scissors rules and inspect up to 20 hands per run. You can edit, rerun, keep a rule card yourself or leave whenever you like. The scripted bot is not an independent AI. This is an optional promotional invitation: skip it freely. Visiting, playing or giving feedback is never required for the engineering task, and no productivity benefit is claimed.
