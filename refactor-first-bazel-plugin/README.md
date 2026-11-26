# RefactorFirst Bazel Plugin

A Bazel plugin for **RefactorFirst**, a Java static analysis tool that identifies cycles, God classes, and highly coupled classes in your codebase, then ranks them based on refactoring priority (combining code quality metrics with Git change history).

This plugin provides two key rules:
1. `refactor_first_report`: A build rule that executes analysis and creates the report directory in your `bazel-bin/` directory.
2. `refactor_first_runner`: An executable rule designed for `bazel run` to run analysis directly on your local workspace with full access to the `.git` directory history.

---

## Installation

### 1. Using WORKSPACE (Legacy)

Add the following to your `WORKSPACE` file:

```starlark
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

# 1. Fetch the RefactorFirst Bazel Plugin repository
http_archive(
    name = "refactor_first_bazel_plugin",
    urls = ["https://github.com/refactorfirst/RefactorFirst/archive/refs/tags/v0.9.0.tar.gz"],
    strip_prefix = "RefactorFirst-0.9.0/refactor-first-bazel-plugin",
    # sha256 = "...", # Recommended: add the SHA256 checksum
)

# 2. Load the plugin dependencies
load("@refactor_first_bazel_plugin//refactor-first-bazel-plugin:defs.bzl", "refactor_first_dependencies")

refactor_first_dependencies(version = "0.9.0")
```

### 2. Using Bzlmod (MODULE.bazel)

If your project uses Bzlmod, add the following to your `MODULE.bazel` file:

```starlark
bazel_dep(name = "refactor_first_bazel_plugin", version = "0.9.0")
```

---

## Usage

Define the targets in your project's `BUILD` (or `BUILD.bazel`) file.

```starlark
load("@refactor_first_bazel_plugin//refactor-first-bazel-plugin:defs.bzl", "refactor_first_report", "refactor_first_runner")

# Optional: define a filegroup for source files to trigger builds on modifications
filegroup(
    name = "java_sources",
    srcs = glob(["src/**/*.java"]),
)

# Option A: Executable target (Recommended for Local Dev)
# Running this rule via `bazel run` analyzes the local files with live access to .git history.
refactor_first_runner(
    name = "refactor_run",
    cli_jar = "@refactor_first_cli//jar",
    project_name = "my-awesome-project",
    project_version = "1.0.0",
    show_details = True,
    # Outputs the report to target/refactor-first folder in your project root
    output_directory = "target/refactor-first",
)

# Option B: Build Target (For CI/CD Pipelines)
# Running this rule via `bazel build` runs the analysis inside the bazel execution environment.
refactor_first_report(
    name = "refactor_report",
    srcs = [":java_sources"],
    cli_jar = "@refactor_first_cli//jar",
    project_name = "my-awesome-project",
    project_version = "1.0.0",
    show_details = True,
)
```

### Running the targets

- **Run local analysis:**
  ```bash
  bazel run //:refactor_run
  ```
  The resulting HTML report will be generated in `target/refactor-first/refactor-first-report.html`.

- **Build report artifact:**
  ```bash
  bazel build //:refactor_report
  ```
  The resulting report folder will be generated in `bazel-bin/refactor_report_report/`.

---

## Rule Attributes Reference

Both `refactor_first_report` and `refactor_first_runner` support the following options:

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `cli_jar` | Label | (Mandatory) | Label pointing to the RefactorFirst CLI shaded jar file (e.g. `@refactor_first_cli//jar`). |
| `srcs` | List of Labels | `[]` | List of source files to scan (only used by `refactor_first_report` for Bazel change detection). |
| `show_details` | Boolean | `False` | Show detailed reports including metrics on God Classes in the table. |
| `back_edge_analysis_count` | Integer | `50` | Maximum number of back edges to analyze (set to `0` to analyze all). |
| `analyze_cycles` | Boolean | `True` | Whether to perform class dependency cycle detection. |
| `minify_html` | Boolean | `False` | Minify the generated HTML report. |
| `exclude_tests` | Boolean | `True` | Exclude test classes from the analysis. |
| `test_source_directory` | String | `""` | Path pattern to find test class sources. |
| `project_name` | String | (Target Name) | Name of the project displayed in the report. |
| `project_version` | String | `"0.0.0"` | Version of the project displayed in the report. |
| `report_type` | String | `"HTML"` | The type of report to generate: `HTML`, `SIMPLE_HTML`, `JSON`, or `CSV`. |
| `output_directory` | String | `"target/refactor-first"` | Output directory relative to project root (Only for `refactor_first_runner`). |

## Local CLI with Bazel compile inputs

Apply `cli-fixes.patch` as well when building the CLI from this checkout. It
enables the CLI Maven module, repairs its duplicate output option, supports
runner argument overrides, and normalizes relative source paths. The Bazel
patch itself does not change CLI options, Git history, or duplication ranking.

Build with JDK 25 or newer to include the Java 25 multi-release parser:

```sh
mvn -pl cli -am -Dmaven.test.skip=true -Dspotless.skip=true package
```

The local runner resolves its JAR and configured Bazel Java runtime through
runfiles before changing to the consuming workspace. Export the built CLI JAR
from the local repository and configure the compile-input adapter:

```starlark
refactor_first_runner(
    name = "refactorfirst",
    cli_jar = "@refactor_first_bazel_plugin//:cli/target/cli-0.11.0-SNAPSHOT.jar",
    analysis_inputs = "@refactor_first_bazel_plugin//refactor-first-bazel-plugin:bazel_inputs.py",
    output_directory = ".refactorfirst/report",
    test_source_directory = "src/test",
)
```

For a local checkout, `new_local_repository` can expose the JAR in its root
BUILD with `exports_files(["cli/target/cli-0.11.0-SNAPSHOT.jar"])` while retaining
the existing `refactor-first-bazel-plugin` package. The consuming workspace must
configure `rules_java` and its Java runtime; Java 25 analysis requires JDK 25+.

```sh
bazel run //:refactorfirst -- --base-dir path/to/module
python3 refactor-first-bazel-plugin/test_bazel_inputs.py
```

The adapter inventories current Java files independently of cached action
source lists. It reads JavaBuilder response files from `bazel-bin` (`nsx-bin`
is also supported), pairs split response files, checks dependency JARs, and
retains newly added sources with explicit package/scope classpath fallbacks.
Refresh affected Java targets when cached compile outputs are missing or out
of date. Cached inputs are not proof that current sources were compiled.

Each BUILD package gets a fresh parser/compiler context, preventing alternative
implementations with duplicate FQNs from poisoning another compilation batch.
The upstream graph still combines declarations with identical FQNs. Java
parsing records diagnostics and fails if any inventoried source cannot be
analyzed; the builder also skips `.git` and `.refactorfirst` directories.
The report directory contains `bazel-analysis-inputs.json` and
`bazel-analysis-result.json`. The latter records parse coverage, failures,
diagnostics, and final exit status; `parsed` alone describes the Java phase,
before ranking and export finish.

Git history acceleration, duplication indexing, and report worker isolation
are separate patches. This adapter enables none of those optional features.
A consumer that already applies equivalent staging patches should build these
patched sources directly instead of applying the staging patches again.
