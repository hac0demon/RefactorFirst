"""Regression tests for the inputs supplied to the RefactorFirst parser."""

import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).with_name("bazel_inputs.py")
SPEC = importlib.util.spec_from_file_location("bazel_inputs", MODULE_PATH)
bazel_inputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bazel_inputs)

class BazelInputsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name).resolve()
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.execroot = root / "output/execroot/nsx"
        self.bin = self.execroot / "bazel-out/macos-fastbuild/bin"
        self.bin.mkdir(parents=True)
        (self.workspace / "nsx-bin").symlink_to(self.bin, target_is_directory=True)
        (self.workspace / "mp").mkdir()
        (self.execroot / "mp").symlink_to(self.workspace / "mp", target_is_directory=True)

    def source(self, package, name="Example", test=False, build=True):
        directory = self.workspace / "mp/policy" / package
        directory.mkdir(parents=True, exist_ok=True)
        if build:
            (directory / "BUILD").touch()
        path = directory / ("src/test/java" if test else "src/main/java") / (name + ".java")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("package example; class %s {}\n" % name)
        return path

    def jar(self, name):
        path = self.execroot / "external/dependencies" / (name + ".jar")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"cached jar")
        return path

    def params(self, package, name, sources, jars, split=False):
        directory = self.bin / "mp/policy" / package
        directory.mkdir(parents=True, exist_ok=True)
        source_args = ["--sources"] + [str(p.relative_to(self.workspace)) for p in sources]
        source_args += ["--target_label", "//mp/policy/%s:%s" % (package, name),
                        "--output", "unused.jar", "--javacopts", "--"]
        classpath_args = ["--classpath"] + [str(p.relative_to(self.execroot)) for p in jars]
        prefix = directory / ("lib" + name + "-compile-class.jar")
        if split:
            Path(str(prefix) + "-0.params").write_text("\n".join(source_args) + "\n")
            Path(str(prefix) + "-1.params").write_text("\n".join(classpath_args) + "\n")
        else:
            Path(str(prefix) + "-0.params").write_text("\n".join(source_args + classpath_args) + "\n")

    def prepare(self):
        return bazel_inputs.prepare_inputs(self.workspace, self.workspace / "mp/policy")

    def test_duplicate_class_names_stay_in_separate_bazel_packages(self):
        # Given mutually exclusive implementations with the same FQN.
        gm = self.source("gm")
        lm = self.source("lm")
        gm_jar, lm_jar = self.jar("gm"), self.jar("lm")
        self.params("gm", "gm", [gm], [gm_jar])
        self.params("lm", "lm", [lm], [lm_jar])
        # When current sources and compile dependencies are collected.
        result = self.prepare()
        # Then neither parser batch contains the other implementation or JAR.
        groups = {group["package"]: group for group in result["source_sets"]}
        self.assertEqual([str(gm)], groups["mp/policy/gm"]["sources"])
        self.assertEqual([str(gm_jar)], groups["mp/policy/gm"]["classpath"])
        self.assertEqual([str(lm)], groups["mp/policy/lm"]["sources"])
        self.assertEqual([str(lm_jar)], groups["mp/policy/lm"]["classpath"])

    def test_new_and_ownerless_sources_are_retained_when_cache_is_incomplete(self):
        # Given a cached action that predates new source files.
        old = self.source("api", "Old")
        new = self.source("api", "New")
        loose = self.source("legacy", "Loose", build=False)
        jar = self.jar("api")
        self.params("api", "api", [old], [jar])
        # When inputs are prepared from the current working tree.
        result = self.prepare()
        # Then all current files remain, and cache coverage is explicit.
        files = {p for group in result["source_sets"] for p in group["sources"]}
        self.assertEqual({str(old), str(new), str(loose)}, files)
        self.assertEqual(3, result["source_count"])
        self.assertEqual(1, result["cached_source_count"])
        self.assertEqual(2, result["uncached_source_count"])

    def test_split_response_files_resolve_classpaths_against_the_same_execroot(self):
        # Given a Javac action split across two parameter files.
        source = self.source("api")
        jar = self.jar("api")
        self.params("api", "api", [source], [jar], split=True)
        # When the paired files are read.
        result = self.prepare()
        # Then the classpath comes from that output tree's execution root.
        self.assertEqual([str(jar)], result["source_sets"][0]["classpath"])
        self.assertEqual(1, result["cached_source_count"])

    def test_test_only_compile_dependencies_do_not_enter_production_inputs(self):
        # Given separate production and test Javac actions.
        main = self.source("api")
        test = self.source("api", "ExampleTest", test=True)
        main_jar, test_jar = self.jar("main"), self.jar("test")
        self.params("api", "api", [main], [main_jar])
        self.params("api", "test", [test], [test_jar])
        # When tests are excluded.
        result = self.prepare()
        # Then test sources and their exclusive dependencies are excluded.
        self.assertEqual(1, result["source_count"])
        self.assertEqual([str(main_jar)], result["source_sets"][0]["classpath"])

    def test_compile_output_names_are_not_used_as_java_action_identity(self):
        # Given a valid JavaBuilder action producing an hjar with another name.
        source = self.source("api")
        jar = self.jar("api")
        self.params("api", "api", [source], [jar])
        original = self.bin / "mp/policy/api/libapi-compile-class.jar-0.params"
        original.rename(original.with_name("libapi-hjar.jar-0.params"))
        # When actions are selected by their structured options and sources.
        result = self.prepare()
        # Then compile.jar, class.jar and hjar output names all work.
        self.assertEqual(1, result["cached_source_count"])
        self.assertEqual([str(jar)], result["source_sets"][0]["classpath"])

    def test_mixed_test_and_main_action_does_not_add_test_dependencies(self):
        # Given a test action that also compiles a production source.
        main = self.source("api")
        test = self.source("api", "ExampleTest", test=True)
        main_jar, test_jar = self.jar("main"), self.jar("test")
        self.params("api", "api", [main], [main_jar])
        self.params("api", "integration", [main, test], [main_jar, test_jar])
        # When tests are excluded, only the production action supplies its classpath.
        result = self.prepare()
        self.assertEqual([str(main_jar)], result["source_sets"][0]["classpath"])
        # When tests are requested, their compile dependencies are retained too.
        result = bazel_inputs.prepare_inputs(self.workspace, self.workspace / "mp/policy", exclude_tests=False)
        self.assertEqual(2, result["source_count"])
        self.assertEqual({str(main_jar), str(test_jar)}, set(result["source_sets"][0]["classpath"]))

    def test_missing_dependency_fails_with_an_actionable_error(self):
        # Given a cached classpath referencing a missing output.
        source = self.source("api")
        missing = self.execroot / "external/dependencies/missing.jar"
        self.params("api", "api", [source], [missing])
        # When preparing the parser's inputs.
        # Then an incomplete classpath cannot silently look complete.
        with self.assertRaisesRegex(bazel_inputs.AnalysisInputsError, "missing.jar"):
            self.prepare()

    def test_nested_scope_uses_the_enclosing_package_compile_action(self):
        # Given a source subdirectory with generated outputs but no Javac action.
        source = self.source("api")
        jar = self.jar("api")
        self.params("api", "api", [source], [jar])
        (self.bin / "mp/policy/api/src/main/java").mkdir(parents=True)
        # When only that source subdirectory is requested.
        result = bazel_inputs.prepare_inputs(self.workspace, source.parent)
        # Then its BUILD package's compile action still provides dependencies.
        self.assertEqual(1, result["cached_source_count"])
        self.assertEqual([str(jar)], result["source_sets"][0]["classpath"])

    def test_unrelated_nested_response_files_do_not_hide_parent_compile_inputs(self):
        # Given unrelated generated-action metadata in a nested source directory.
        source = self.source("api")
        jar = self.jar("api")
        self.params("api", "api", [source], [jar])
        output = self.bin / "mp/policy/api/src/main/java"
        output.mkdir(parents=True)
        (output / "unrelated-0.params").write_text("--input\nfile.txt\n")
        # When that nested directory is analyzed, its parent action still applies.
        result = bazel_inputs.prepare_inputs(self.workspace, source.parent)
        self.assertEqual(1, result["cached_source_count"])
        self.assertEqual([str(jar)], result["source_sets"][0]["classpath"])

    def invoke_runner(self, arguments):
        argv = ["bazel_inputs.py", "--java", "java", "--jar", "cli.jar", "--",
                "--base-dir", "mp/policy"] + arguments
        with mock.patch.object(sys, "argv", argv), mock.patch.dict(os.environ, {
            "BUILD_WORKSPACE_DIRECTORY": str(self.workspace),
        }), mock.patch.object(bazel_inputs.subprocess, "call", return_value=0), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return bazel_inputs.main()

    def test_bare_test_flag_matches_the_real_cli_false_fallback(self):
        # Given the CLI's default-true test exclusion and a bare toggle flag.
        self.source("api")
        self.source("api", "ExampleTest", test=True)
        # When the same flag is passed through the runner, both files are included.
        self.invoke_runner(["--exclude-tests"])
        path = self.workspace / "mp/policy/.refactorfirst/report/bazel-analysis-inputs.json"
        self.assertEqual(2, json.loads(path.read_text())["source_count"])

    def test_normal_runner_type_option_does_not_override_test_source_directory(self):
        # Given the upstream runner's actual short-option sequence.
        self.source("api")
        self.source("api", "ExampleTest", test=True)
        # When -t HTML follows -tsd src/test, argparse must not abbreviate -tsd.
        self.invoke_runner(["-d", "-eac", "50", "-tsd", "src/test", "-p", "NSX", "-t", "HTML"])
        path = self.workspace / "mp/policy/.refactorfirst/report/bazel-analysis-inputs.json"
        self.assertEqual(1, json.loads(path.read_text())["source_count"])

    def test_input_failure_replaces_previous_parse_success(self):
        # Given an old success record and a dependency removed from the cache.
        source = self.source("api")
        self.params("api", "api", [source], [self.execroot / "missing.jar"])
        directory = self.workspace / "mp/policy/.refactorfirst/report"
        directory.mkdir(parents=True)
        result = directory / "bazel-analysis-result.json"
        result.write_text('{"status":"parsed"}')
        # When input preparation fails, the previous success cannot describe this run.
        with self.assertRaises(SystemExit):
            self.invoke_runner([])
        self.assertEqual("input_failed", json.loads(result.read_text())["status"])

    def test_a_source_only_fixture_remains_usable_without_bazel_outputs(self):
        # Given sources whose dependencies are entirely in the JDK.
        source = self.source("fixture")
        # When no cached Javac actions exist.
        result = self.prepare()
        # Then the file is retained with an explicit source-only origin.
        self.assertEqual([str(source)], result["source_sets"][0]["sources"])
        self.assertEqual("source_only", result["source_sets"][0]["classpath_origin"])

if __name__ == "__main__":
    unittest.main()

