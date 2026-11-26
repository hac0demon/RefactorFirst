#!/usr/bin/env python3
"""Supply current source sets and cached Bazel compile classpaths to RefactorFirst."""

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


class AnalysisInputsError(ValueError):
    pass


def _field(arguments, name):
    try:
        start = arguments.index(name) + 1
    except ValueError:
        return []
    end = start
    while end < len(arguments) and not arguments[end].startswith("--"):
        end += 1
    return arguments[start:end]


def _arguments(text):
    # JavaBuilder writes one argument per line. The common unquoted case can
    # contain millions of repeated classpath entries across cached actions.
    if not any(character in text for character in ('"', "'", "\\")):
        return text.split()
    return shlex.split(text, comments=False)


def _owner(source, workspace, fallback):
    directory = source.parent
    while directory == workspace or workspace in directory.parents:
        if any((directory / name).is_file() for name in ("BUILD.bazel", "BUILD")):
            return directory
        directory = directory.parent
    return fallback


def _is_test(path, pattern):
    parts = Path(pattern).parts
    return bool(parts) and any(path.parts[i:i + len(parts)] == parts for i in range(len(path.parts)))


def prepare_inputs(workspace, base_dir, test_source_directory="src/test", exclude_tests=True):
    workspace = Path(workspace).resolve()
    base_dir = Path(base_dir).resolve()
    if not base_dir.is_dir():
        raise AnalysisInputsError("Source directory does not exist: %s" % base_dir)
    sources = []
    for directory, directories, filenames in os.walk(base_dir, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in (".git", ".refactorfirst"))
        for name in sorted(filenames):
            path = Path(directory) / name
            if name.endswith(".java") and not (exclude_tests and _is_test(path, test_source_directory)):
                sources.append(path)
    source_lookup = {path.resolve(): path for path in sources}
    owners = {path: _owner(path, workspace, base_dir) for path in sources}
    classpaths = defaultdict(set)
    all_jars = set()
    covered = set()
    selected_params = []
    output_tree = next((workspace / name for name in ("nsx-bin", "bazel-bin")
                        if (workspace / name).is_dir()), None)
    execroot = None
    if output_tree is not None:
        output_tree = output_tree.resolve()
        # bazel-out/<configuration>/bin is rooted in this one execution root.
        if output_tree.parent.parent.name != "bazel-out":
            raise AnalysisInputsError("Unrecognized Bazel output tree: %s" % output_tree)
        execroot = output_tree.parents[2]
        resolved_paths = {}

        def resolve_output(name):
            if name not in resolved_paths:
                resolved_paths[name] = (execroot / name).resolve()
            return resolved_paths[name]

        try:
            relative_scope = base_dir.relative_to(workspace)
        except ValueError:
            relative_scope = None
        if relative_scope is not None:
            scan_root = output_tree / relative_scope
            scan_roots = {scan_root}
            # A nested scope still uses its enclosing BUILD package's actions,
            # even when nested output directories contain unrelated response files.
            package = _owner(base_dir / "scope.java", workspace, base_dir)
            if set(owners.values()) == {package}:
                scan_roots.add(output_tree / package.relative_to(workspace))
            responses = defaultdict(list)
            candidates = {path for root in scan_roots if root.is_dir() for path in root.rglob("*.params")}
            if candidates:
                for path in candidates:
                    match = re.match(r"(.*)-(\d+)\.params$", str(path))
                    if match:
                        responses[match.group(1)].append((int(match.group(2)), path))
                    else:
                        responses[str(path)].append((0, path))
                for action, paths in sorted(responses.items()):
                    arguments = []
                    for _, path in sorted(paths):
                        arguments.extend(_arguments(path.read_text()))
                    if not all(option in arguments for option in
                               ("--sources", "--target_label", "--javacopts", "--output")):
                        continue
                    if exclude_tests and any(_is_test(Path(name), test_source_directory)
                                             for name in _field(arguments, "--sources")):
                        continue
                    matched = {source_lookup[resolve_output(name)]
                               for name in _field(arguments, "--sources")
                               if resolve_output(name) in source_lookup}
                    if not matched:
                        continue
                    jars = {resolve_output(name) for name in _field(arguments, "--classpath")}
                    covered.update(matched)
                    all_jars.update(jars)
                    for owner in {owners[path] for path in matched}:
                        classpaths[owner].update(jars)
                    selected_params.extend([str(path) for _, path in sorted(paths)])
    missing = sorted(path for path in all_jars if not path.is_file() or not os.access(path, os.R_OK))
    if missing:
        raise AnalysisInputsError(
            "Cached Bazel compile classpath has %d missing/unreadable JAR(s), including %s. "
            "Build the affected Java targets to refresh their outputs before retrying."
            % (len(missing), ", ".join(str(path) for path in missing[:5])))
    grouped = defaultdict(list)
    for source in sources:
        grouped[owners[source]].append(str(source))
    source_sets = []
    for owner, files in sorted(grouped.items()):
        jars = classpaths.get(owner, set())
        origin = "package_compile_classpath"
        if not jars:
            jars = all_jars
            origin = "scope_classpath_fallback" if jars else "source_only"
        try:
            package = str(owner.relative_to(workspace))
        except ValueError:
            package = str(owner)
        source_sets.append({
            "package": package,
            "sources": sorted(files),
            "classpath": sorted(str(path) for path in jars),
            "classpath_origin": origin,
        })
    return {
        "schema_version": 1,
        "source_root": str(base_dir),
        "output_tree": str(output_tree) if output_tree else None,
        "execroot": str(execroot) if execroot else None,
        "metadata_kind": "cached_javac_parameters",
        "source_count": len(sources),
        "cached_source_count": len(covered),
        "uncached_source_count": len(sources) - len(covered),
        "classpath_jar_count": len(all_jars),
        "parameter_files": selected_params,
        "source_sets": source_sets,
    }


def _boolean(value):
    if isinstance(value, bool):
        return value
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise argparse.ArgumentTypeError("Expected true or false")


def _write_json(path, value):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", required=True)
    parser.add_argument("--jar", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    options = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    options.add_argument("-b", "--base-dir", default=".")
    options.add_argument("-o", "--output", default=".refactorfirst/report")
    options.add_argument("-tsd", "--test-source-directory", default="src/test")
    # argparse still abbreviates short options with allow_abbrev=False:
    # without an exact -t, the runner's '-t HTML' becomes '-tsd HTML'.
    options.add_argument("-t", "--type")
    options.add_argument("-xt", "--exclude-tests", type=_boolean, nargs="?", const=False, default=True)
    options.add_argument("-h", "--help", action="store_true")
    known, _ = options.parse_known_args(arguments)
    command = [args.java]
    result_path = None
    if not known.help:
        workspace = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", os.getcwd())).resolve()
        base = (workspace / known.base_dir).resolve()
        if not base.is_dir():
            parser.exit(1, "RefactorFirst source directory does not exist: %s\n" % base)
        directory = (base / known.output).resolve()
        if directory != base and base not in directory.parents:
            parser.exit(1, "RefactorFirst output directory must stay inside the source directory.\n")
        directory.mkdir(parents=True, exist_ok=True)
        result_path = directory / "bazel-analysis-result.json"
        _write_json(result_path, {"status": "preparing_inputs", "source_root": str(base)})
        print("RefactorFirst: collecting current sources and cached Bazel compile inputs...", flush=True)
        try:
            manifest = prepare_inputs(workspace, base, known.test_source_directory, known.exclude_tests)
        except AnalysisInputsError as error:
            _write_json(result_path, {"status": "input_failed", "error": str(error)})
            parser.exit(1, "RefactorFirst inputs: %s\n" % error)
        # Keep input metadata inside the same project/report directory as the report.
        path = directory / "bazel-analysis-inputs.json"
        _write_json(path, manifest)
        _write_json(result_path, {"status": "parsing", "expected_source_count": manifest["source_count"]})
        command.append("-Drefactorfirst.bazelInputs=" + str(path))
        print("RefactorFirst: %d current Java sources, %d source sets, %d cached compile JARs; "
              "%d sources absent from cached action lists (retained)."
              % (manifest["source_count"], len(manifest["source_sets"]),
                 manifest["classpath_jar_count"], manifest["uncached_source_count"]), flush=True)
        if not manifest["parameter_files"]:
            print("RefactorFirst: no matching cached Javac metadata; using source-only analysis.", flush=True)
    command.extend(["-jar", args.jar] + arguments)
    code = subprocess.call(command)
    if result_path is not None:
        result = json.loads(result_path.read_text())
        result["command_exit_code"] = code
        _write_json(result_path, result)
    return code


if __name__ == "__main__":
    sys.exit(main())
