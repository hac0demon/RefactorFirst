# RefactorFirst Bazel Example Project

This is a sample project demonstrating how to integrate and use the **RefactorFirst Bazel Plugin**.

## Prerequisites

- **Java 11 or newer** installed and available on your PATH.
- **Bazel** installed.
- **Git** repository initialized in the workspace or parent directory (since RefactorFirst uses Git history to calculate metrics).

## Configuration

The example loads the RefactorFirst Bazel plugin rules locally via a `local_repository` definition in the [WORKSPACE](WORKSPACE) file:

```starlark
local_repository(
    name = "refactor_first_bazel_plugin",
    path = "..",
)

load("@refactor_first_bazel_plugin//refactor-first-bazel-plugin:defs.bzl", "refactor_first_dependencies")

refactor_first_dependencies(version = "0.9.0")
```

The [BUILD](BUILD) file exposes two targets:
1. `//:report`: Generates the analysis report as a Bazel build action output inside the `bazel-bin/` directory.
2. `//:analyze`: A runner script to run the analysis directly on the active codebase with access to your `.git` repository history (via `bazel run`).

## Running the Example

### 1. Run the Executable Target (Recommended for Local Dev)

Running the analysis via `bazel run` executes the tool outside of the sandbox directly in your workspace directory. This allows the JGit module to read your `.git` history:

```bash
bazel run //:analyze
```

By default, this will write the HTML report to:
`target/refactor-first/refactor-first-report.html`

### 2. Run the Build Action

To generate the report as a Bazel build artifact:

```bash
bazel build //:report
```

The output report directory will be created at:
`bazel-bin/report_report/`
