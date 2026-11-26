# User-facing entry point for RefactorFirst Bazel plugin

load("//refactor-first-bazel-plugin:rules.bzl", _refactor_first_report = "refactor_first_report", _refactor_first_runner = "refactor_first_runner")
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_jar")

refactor_first_report = _refactor_first_report
refactor_first_runner = _refactor_first_runner

def refactor_first_dependencies(version = "0.9.0", sha256 = None):
    """Downloads the RefactorFirst CLI jar from Maven Central.

    Args:
        version: The version of RefactorFirst CLI to download.
        sha256: Optional SHA-256 checksum of the jar file.
    """
    if "refactor_first_cli" not in native.existing_rules():
        http_jar(
            name = "refactor_first_cli",
            url = "https://repo1.maven.org/maven2/org/hjug/refactorfirst/report/cli/{version}/cli-{version}.jar".format(version = version),
            sha256 = sha256,
        )
