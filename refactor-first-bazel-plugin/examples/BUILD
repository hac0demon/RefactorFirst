load("@refactor_first_bazel_plugin//refactor-first-bazel-plugin:defs.bzl", "refactor_first_report", "refactor_first_runner")

# A filegroup representing Java source files to scan
filegroup(
    name = "srcs",
    srcs = glob(["src/**/*.java"]),
)

# Rule 1: Build target to generate a report inside the bazel-bin folder.
# Run: bazel build //:report
refactor_first_report(
    name = "report",
    srcs = [":srcs"],
    cli_jar = "@refactor_first_cli//jar",
    project_name = "example-bazel-project",
    project_version = "1.0.0",
    show_details = True,
    report_type = "HTML",
)

# Rule 2: Executable runner target to run analysis locally.
# This runs directly on your codebase directory with full access to .git repository.
# Run: bazel run //:analyze
refactor_first_runner(
    name = "analyze",
    cli_jar = "@refactor_first_cli//jar",
    project_name = "example-bazel-project",
    project_version = "1.0.0",
    show_details = True,
    report_type = "HTML",
    # Outputs the report to target/refactor-first folder in your project root
    output_directory = "target/refactor-first",
)
