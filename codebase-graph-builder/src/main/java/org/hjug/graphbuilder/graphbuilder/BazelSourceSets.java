package org.hjug.graphbuilder.graphbuilder;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Input adapter for the source sets and compile classpaths supplied by the Bazel runner. */
final class BazelSourceSets {
    private static final String INPUTS_PROPERTY = "refactorfirst.bazelInputs";

    record SourceSet(String name, List<Path> sources, List<Path> classpath) {}

    private BazelSourceSets() {}

    static boolean isGeneratedInput(Path sourceRoot, Path file) {
        for (Path part : sourceRoot.normalize().relativize(file.normalize())) {
            if (part.toString().equals(".git") || part.toString().equals(".refactorfirst")) {
                return true;
            }
        }
        return false;
    }

    static List<SourceSet> load(List<Path> sources, Path sourceRoot) throws IOException {
        String configured = System.getProperty(INPUTS_PROPERTY);
        if (configured == null || configured.isBlank()) {
            return List.of(new SourceSet("default", sources, List.of()));
        }
        JsonNode manifest = new ObjectMapper().readTree(Path.of(configured).toFile());
        if (manifest.path("schema_version").asInt() != 1
                || !Path.of(manifest.path("source_root").asText()).equals(sourceRoot.normalize())) {
            throw new IllegalArgumentException(
                    "Bazel analysis inputs do not match the source directory: " + configured);
        }
        Map<Path, JsonNode> owners = new HashMap<>();
        for (JsonNode sourceSet : manifest.path("source_sets")) {
            for (JsonNode file : sourceSet.path("sources")) {
                Path path = Path.of(file.asText()).normalize();
                if (owners.putIfAbsent(path, sourceSet) != null) {
                    throw new IllegalArgumentException("Bazel input lists a source more than once: " + path);
                }
            }
        }
        Map<String, List<Path>> grouped = new LinkedHashMap<>();
        Map<String, JsonNode> metadata = new HashMap<>();
        for (Path source : sources) {
            JsonNode sourceSet = owners.get(source.normalize());
            if (sourceSet == null) {
                throw new IllegalArgumentException("Bazel input is missing a current source: " + source);
            }
            String name = sourceSet.path("package").asText();
            grouped.computeIfAbsent(name, key -> new ArrayList<>()).add(source);
            metadata.put(name, sourceSet);
        }
        List<SourceSet> result = new ArrayList<>();
        Set<Path> validated = new HashSet<>();
        for (Map.Entry<String, List<Path>> group : grouped.entrySet()) {
            List<Path> classpath = new ArrayList<>();
            for (JsonNode entry : metadata.get(group.getKey()).path("classpath")) {
                Path path = Path.of(entry.asText());
                if (validated.add(path) && (!Files.isRegularFile(path) || !Files.isReadable(path))) {
                    throw new IllegalArgumentException("Bazel compile dependency is missing or unreadable: " + path);
                }
                classpath.add(path);
            }
            result.add(new SourceSet(group.getKey(), group.getValue(), classpath));
        }
        return result;
    }

    static void writeParseResult(int expected, int parsed, List<String> failed, List<Throwable> diagnostics)
            throws IOException {
        String configured = System.getProperty(INPUTS_PROPERTY);
        if (configured == null || configured.isBlank()) {
            return;
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", parsed == expected && failed.isEmpty() && diagnostics.isEmpty() ? "parsed" : "failed");
        result.put("expected_source_count", expected);
        result.put("parsed_source_count", parsed);
        result.put("failed_sources", failed);
        result.put("diagnostic_count", diagnostics.size());
        List<String> details = new ArrayList<>();
        for (Throwable error : diagnostics.subList(0, Math.min(20, diagnostics.size()))) {
            StringWriter stack = new StringWriter();
            error.printStackTrace(new PrintWriter(stack));
            details.add(stack.toString());
        }
        result.put("first_diagnostics", details);
        Path output = Path.of(configured).resolveSibling("bazel-analysis-result.json");
        new ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(output.toFile(), result);
    }
}
