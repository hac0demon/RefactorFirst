# Rules implementation for RefactorFirst Bazel plugin

load("@rules_java//java/common:java_common.bzl", "java_common")

def _runfile_path(ctx, path):
    if path.startswith("/"):
        return path
    if path.startswith("../"):
        return path[3:]
    return ctx.workspace_name + "/" + path

def _refactor_first_report_impl(ctx):
    cli_jar = ctx.file.cli_jar

    # Declare an output directory for the report
    output_dir = ctx.actions.declare_directory(ctx.attr.name + "_report")

    # Build up the CLI arguments
    args = []

    # Base directory is "." (the root of the execution)
    args.extend(["-b", "."])
    args.extend(["-o", output_dir.path])

    if ctx.attr.show_details:
        args.append("-d")

    args.extend(["-eac", str(ctx.attr.back_edge_analysis_count)])

    if not ctx.attr.analyze_cycles:
        args.append("-c=false")

    if ctx.attr.minify_html:
        args.append("-m")

    if not ctx.attr.exclude_tests:
        args.append("-xt=false")

    if ctx.attr.test_source_directory:
        args.extend(["-tsd", ctx.attr.test_source_directory])

    if ctx.attr.project_name:
        args.extend(["-p", ctx.attr.project_name])
    else:
        args.extend(["-p", ctx.label.name])

    if ctx.attr.project_version:
        args.extend(["-v", ctx.attr.project_version])

    if ctx.attr.report_type:
        args.extend(["-t", ctx.attr.report_type])

    # Combine all input files
    inputs = [cli_jar]
    inputs.extend(ctx.files.srcs)

    # Run the action locally without sandbox to allow JGit to find the .git directory
    ctx.actions.run_shell(
        outputs = [output_dir],
        inputs = inputs,
        command = "java -jar \"$1\" \"${@:2}\"",
        arguments = [cli_jar.path] + args,
        execution_requirements = {
            "no-sandbox": "1",
            "local": "1",
        },
        mnemonic = "RefactorFirstReport",
        progress_message = "Generating RefactorFirst report for target %s..." % ctx.label.name,
    )

    return [
        DefaultInfo(
            files = depset([output_dir]),
        )
    ]

refactor_first_report = rule(
    implementation = _refactor_first_report_impl,
    attrs = {
        "cli_jar": attr.label(
            allow_single_file = True,
            mandatory = True,
            doc = "Label pointing to the RefactorFirst CLI shaded jar file.",
        ),
        "srcs": attr.label_list(
            allow_files = True,
            doc = "Java source files to analyze.",
        ),
        "show_details": attr.bool(
            default = False,
            doc = "Show detailed report.",
        ),
        "back_edge_analysis_count": attr.int(
            default = 50,
            doc = "Back edge analysis count.",
        ),
        "analyze_cycles": attr.bool(
            default = True,
            doc = "Analyze cycles.",
        ),
        "minify_html": attr.bool(
            default = False,
            doc = "Minify HTML output.",
        ),
        "exclude_tests": attr.bool(
            default = True,
            doc = "Exclude tests from analysis.",
        ),
        "test_source_directory": attr.string(
            doc = "Test source directory.",
        ),
        "project_name": attr.string(
            doc = "Project name.",
        ),
        "project_version": attr.string(
            doc = "Project version.",
        ),
        "report_type": attr.string(
            default = "HTML",
            values = ["HTML", "SIMPLE_HTML", "JSON", "CSV"],
            doc = "Report type: HTML, SIMPLE_HTML, JSON, CSV.",
        ),
    },
    doc = "Bazel build rule to run RefactorFirst and generate a report folder",
)

def _refactor_first_runner_impl(ctx):
    cli_jar = ctx.file.cli_jar
    analysis_inputs = ctx.file.analysis_inputs
    launch_command = 'exec "${JAVA}" -jar "${JAR_PATH}"'
    if analysis_inputs:
        launch_command = 'exec python3 "${INPUTS}" --java "${JAVA}" --jar "${JAR_PATH}" --'
    java_runtime = ctx.attr._java_runtime[java_common.JavaRuntimeInfo]

    # We generate a wrapper script
    script_file = ctx.actions.declare_file(ctx.label.name + "_runner.sh")

    # Build up options
    args = []
    if ctx.attr.show_details:
        args.append("-d")
    args.extend(["-eac", str(ctx.attr.back_edge_analysis_count)])
    if not ctx.attr.analyze_cycles:
        args.append("-c=false")
    if ctx.attr.minify_html:
        args.append("-m")
    if not ctx.attr.exclude_tests:
        args.append("-xt=false")
    if ctx.attr.test_source_directory:
        args.extend(["-tsd", ctx.attr.test_source_directory])
    if ctx.attr.project_name:
        args.extend(["-p", ctx.attr.project_name])
    else:
        args.extend(["-p", ctx.label.name])
    if ctx.attr.project_version:
        args.extend(["-v", ctx.attr.project_version])
    if ctx.attr.report_type:
        args.extend(["-t", ctx.attr.report_type])
    if ctx.attr.output_directory:
        args.extend(["-o", ctx.attr.output_directory])
    else:
        args.extend(["-o", "target/refactor-first"])

    # We want the script to locate the jar and run java.
    # When running under 'bazel run', BUILD_WORKSPACE_DIRECTORY is set to the workspace root.
    # The runner script should run in the BUILD_WORKSPACE_DIRECTORY, so it can see `.git`.
    script_content = """#!/bin/bash
set -uo pipefail

# Resolve runfiles before changing to the source workspace.
f=bazel_tools/tools/bash/runfiles/runfiles.bash
source "${{RUNFILES_DIR:-/dev/null}}/$f" 2>/dev/null || \
  source "$(grep -sm1 "^$f " "${{RUNFILES_MANIFEST_FILE:-/dev/null}}" | cut -d ' ' -f 2-)" 2>/dev/null || \
  source "$0.runfiles/$f" 2>/dev/null || \
  source "$(grep -sm1 "^$f " "$0.runfiles_manifest" | cut -d ' ' -f 2-)" 2>/dev/null || \
  {{ echo >&2 "Cannot find Bazel runfiles library"; exit 1; }}
set -e
JAR_PATH="$(rlocation '{jar_path}')"
JAVA="$(rlocation '{java_path}')"
if [[ -n '{inputs_path}' ]]; then
  INPUTS="$(rlocation '{inputs_path}')"
fi

if [[ -n "${{BUILD_WORKSPACE_DIRECTORY:-}}" ]]; then
  cd "${{BUILD_WORKSPACE_DIRECTORY}}"
fi
 
echo "Running RefactorFirst analysis using ${{JAR_PATH}}..."
{launch_command} {args} "$@"
""".format(
        inputs_path = _runfile_path(ctx, analysis_inputs.short_path) if analysis_inputs else "",
        launch_command = launch_command,
        jar_path = _runfile_path(ctx, cli_jar.short_path),
        java_path = _runfile_path(ctx, java_runtime.java_executable_runfiles_path),
        args = " ".join(['"' + arg.replace('"', '\\"') + '"' for arg in args]),
    )

    ctx.actions.write(
        output = script_file,
        content = script_content,
        is_executable = True,
    )

    return [
        DefaultInfo(
            executable = script_file,
            runfiles = ctx.runfiles(
                files = [cli_jar] + ([analysis_inputs] if analysis_inputs else []),
                transitive_files = java_runtime.files,
            ).merge(ctx.attr._runfiles[DefaultInfo].default_runfiles),
        )
    ]

refactor_first_runner = rule(
    implementation = _refactor_first_runner_impl,
    executable = True,
    attrs = {
        "analysis_inputs": attr.label(
            allow_single_file = [".py"],
            doc = "Optional runner that supplies Bazel source sets and compile classpaths.",
        ),
        "_java_runtime": attr.label(
            default = Label("@rules_java//toolchains:current_java_runtime"),
            providers = [java_common.JavaRuntimeInfo],
        ),
        "_runfiles": attr.label(
            default = Label("@bazel_tools//tools/bash/runfiles"),
        ),
        "cli_jar": attr.label(
            allow_single_file = True,
            mandatory = True,
            doc = "Label pointing to the RefactorFirst CLI shaded jar file.",
        ),
        "show_details": attr.bool(
            default = False,
            doc = "Show detailed report.",
        ),
        "back_edge_analysis_count": attr.int(
            default = 50,
            doc = "Back edge analysis count.",
        ),
        "analyze_cycles": attr.bool(
            default = True,
            doc = "Analyze cycles.",
        ),
        "minify_html": attr.bool(
            default = False,
            doc = "Minify HTML output.",
        ),
        "exclude_tests": attr.bool(
            default = True,
            doc = "Exclude tests from analysis.",
        ),
        "test_source_directory": attr.string(
            doc = "Test source directory.",
        ),
        "project_name": attr.string(
            doc = "Project name.",
        ),
        "project_version": attr.string(
            doc = "Project version.",
        ),
        "report_type": attr.string(
            default = "HTML",
            values = ["HTML", "SIMPLE_HTML", "JSON", "CSV"],
            doc = "Report type: HTML, SIMPLE_HTML, JSON, CSV.",
        ),
        "output_directory": attr.string(
            doc = "Output directory relative to project root.",
        ),
    },
    doc = "Bazel rule to run RefactorFirst via bazel run",
)
