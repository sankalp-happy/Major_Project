from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from phase1.pipeline import (
    ImpactAnalyzer,
    SDGQueries,
    analyze_phase1,
    build_phase1,
    load_sdg_graph,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT / "repo"


@pytest.fixture(scope="module")
def analysis():
    return analyze_phase1(REPO_ROOT)


def _function_definitions(symbol_table: dict[str, object]) -> set[str]:
    names: set[str] = set()
    functions = symbol_table["functions"]
    for name, records in functions.items():
        if any(record["kind"] == "definition" for record in records):
            names.add(name)
    return names


def _function_declarations(symbol_table: dict[str, object]) -> set[str]:
    names: set[str] = set()
    functions = symbol_table["functions"]
    for name, records in functions.items():
        if any(record["kind"] == "declaration" for record in records):
            names.add(name)
    return names


def test_phase11_parser_coverage_and_ast_artifacts(analysis):
    report = analysis.report

    assert report["total_c_like_files"] == 8
    assert report["parsed_without_error"] == 8
    assert report["parser_coverage"] >= 0.95
    assert report["files_with_parse_errors"] == []

    assert set(analysis.ast_artifacts.keys()) == {
        "include/cart.h",
        "include/discount.h",
        "include/state.h",
        "include/types.h",
        "src/cart.c",
        "src/discount.c",
        "src/main.c",
        "src/state.c",
    }

    for artifact in analysis.ast_artifacts.values():
        assert artifact["has_error"] is False
        assert artifact["node_count"] > 0
        assert artifact["named_node_count"] > 0
        assert artifact["top_level_nodes"]


def test_phase11_symbol_table_entities(analysis):
    expected_defined_functions = {
        "apply_global_discount",
        "calculate_subtotal",
        "checkout_total",
        "get_discount_percent",
        "get_last_total",
        "main",
        "set_discount_percent",
        "set_last_total",
    }
    assert _function_definitions(analysis.symbol_table) == expected_defined_functions

    expected_declared_functions = {
        "apply_global_discount",
        "calculate_subtotal",
        "checkout_total",
        "get_discount_percent",
        "get_last_total",
        "set_discount_percent",
        "set_last_total",
    }
    assert _function_declarations(analysis.symbol_table) == expected_declared_functions

    assert set(analysis.symbol_table["types"]) == {"Cart", "Item"}
    assert set(analysis.symbol_table["variables"]) >= {
        "g_discount_percent",
        "g_last_total",
    }

    g_discount_records = analysis.symbol_table["variables"]["g_discount_percent"]
    g_last_records = analysis.symbol_table["variables"]["g_last_total"]

    assert any(
        record["scope"] == "global"
        and record["is_definition"]
        and record["file"] == "src/state.c"
        for record in g_discount_records
    )
    assert any(
        record["scope"] == "global"
        and record["is_definition"]
        and record["file"] == "src/state.c"
        for record in g_last_records
    )


def test_phase12_call_graph_resolution(analysis):
    call_graph = analysis.call_graph
    assert call_graph.number_of_edges() == 9

    expected_internal_edges = {
        ("function:main", "function:set_discount_percent"),
        ("function:main", "function:checkout_total"),
        ("function:main", "function:get_discount_percent"),
        ("function:main", "function:get_last_total"),
        ("function:checkout_total", "function:calculate_subtotal"),
        ("function:checkout_total", "function:apply_global_discount"),
        ("function:checkout_total", "function:set_last_total"),
        ("function:apply_global_discount", "function:get_discount_percent"),
    }

    for source, target in expected_internal_edges:
        assert call_graph.has_edge(source, target)
        assert call_graph[source][target]["classification"] == "internal"
        assert call_graph[source][target]["resolved"] is True

    assert call_graph.has_edge("function:main", "function:external:printf")
    assert (
        call_graph["function:main"]["function:external:printf"]["classification"]
        == "external"
    )
    assert call_graph["function:main"]["function:external:printf"]["count"] == 4

    assert len(analysis.unresolved_calls) == 4
    assert all(
        unresolved["callee"] == "printf" for unresolved in analysis.unresolved_calls
    )
    assert all(
        unresolved["classification"] == "external"
        for unresolved in analysis.unresolved_calls
    )


def test_phase12_include_graph_resolution(analysis):
    include_graph = analysis.include_graph

    assert include_graph.number_of_edges() == 12
    assert include_graph.has_edge("file:src/main.c", "file:include/cart.h")
    assert include_graph.has_edge("file:src/main.c", "file:include/state.h")
    assert include_graph.has_edge("file:src/main.c", "file:include/types.h")

    assert include_graph.has_edge("file:src/main.c", "file:external:stdio.h")
    assert (
        include_graph["file:src/main.c"]["file:external:stdio.h"]["resolved"] is False
    )
    assert (
        include_graph["file:src/main.c"]["file:external:stdio.h"]["is_system"] is True
    )

    unresolved_non_system = [
        edge
        for edge in include_graph.edges(data=True)
        if edge[2]["resolved"] is False and edge[2]["is_system"] is False
    ]
    assert unresolved_non_system == []


def test_phase13_global_state_and_type_usage(analysis):
    function_analyses = analysis.function_analyses

    assert function_analyses["function:get_discount_percent"]["reads"] == [
        "g_discount_percent"
    ]
    assert function_analyses["function:set_discount_percent"]["writes"] == [
        "g_discount_percent"
    ]
    assert function_analyses["function:get_last_total"]["reads"] == ["g_last_total"]
    assert function_analyses["function:set_last_total"]["writes"] == ["g_last_total"]

    assert set(function_analyses["function:main"]["uses_types"]) == {"Cart", "Item"}
    assert function_analyses["function:checkout_total"]["uses_types"] == ["Cart"]
    assert function_analyses["function:calculate_subtotal"]["uses_types"] == ["Cart"]

    global_state_map = analysis.report["global_state_map"]
    assert global_state_map["g_discount_percent"] == {
        "readers": ["get_discount_percent"],
        "writers": ["set_discount_percent"],
    }
    assert global_state_map["g_last_total"] == {
        "readers": ["get_last_total"],
        "writers": ["set_last_total"],
    }
    assert analysis.report["all_globals_linked"] is True


def test_phase14_sdg_schema_and_queries(analysis):
    sdg = analysis.sdg

    node_types = {attrs.get("node_type") for _, attrs in sdg.nodes(data=True)}
    assert node_types >= {"File", "Function", "Variable", "Type"}

    edge_types = {
        attrs.get("edge_type") for _, _, _, attrs in sdg.edges(keys=True, data=True)
    }
    assert edge_types >= {"includes", "calls", "reads", "writes", "uses_type"}

    assert analysis.report["sdg_nodes"] == sdg.number_of_nodes()
    assert analysis.report["sdg_edges"] == sdg.number_of_edges()

    queries = SDGQueries(sdg)

    assert queries.upstream_callers("get_discount_percent", transitive=False) == [
        "apply_global_discount",
        "main",
    ]
    assert queries.upstream_callers("get_discount_percent", transitive=True) == [
        "apply_global_discount",
        "checkout_total",
        "main",
    ]

    closure = queries.transitive_closure("function:main", edge_types={"calls"})
    assert "function:checkout_total" in closure
    assert "function:calculate_subtotal" in closure
    assert "function:external:printf" in closure

    paths = queries.global_state_impact_path("checkout_total", "g_last_total")
    assert [
        "function:checkout_total",
        "function:set_last_total",
        "variable:g_last_total",
    ] in paths
    assert [
        "function:checkout_total",
        "function:set_last_total",
        "variable:g_last_total",
        "function:get_last_total",
    ] in paths


def test_phase14_serialization_deserialization_reproducible(tmp_path):
    first_dir = tmp_path / "run1"
    second_dir = tmp_path / "run2"

    first = build_phase1(REPO_ROOT, first_dir)
    second = build_phase1(REPO_ROOT, second_dir)

    expected_files = {
        "symbol_table.json",
        "call_graph.json",
        "include_graph.json",
        "sdg_v1.json",
        "function_analysis.json",
        "unresolved_calls.json",
        "report.json",
    }
    assert expected_files.issubset({path.name for path in first_dir.iterdir()})
    assert expected_files.issubset({path.name for path in second_dir.iterdir()})

    for filename in expected_files:
        first_content = (first_dir / filename).read_text()
        second_content = (second_dir / filename).read_text()
        assert first_content == second_content

    first_graph = load_sdg_graph(first_dir / "sdg_v1.json")
    second_graph = load_sdg_graph(second_dir / "sdg_v1.json")

    assert first_graph.number_of_nodes() == first.sdg.number_of_nodes()
    assert first_graph.number_of_edges() == first.sdg.number_of_edges()
    assert second_graph.number_of_nodes() == second.sdg.number_of_nodes()
    assert second_graph.number_of_edges() == second.sdg.number_of_edges()


def test_phase15_impact_analyzer_seeded_changes(analysis):
    analyzer = ImpactAnalyzer(analysis.sdg)

    function_change = analyzer.analyze(
        {"type": "function_signature_change", "function": "checkout_total"}
    )
    assert function_change["impacted_nodes"] == ["main"]
    assert function_change["obligations"] == [
        {
            "target": "main",
            "action": "update_call_signature",
            "reason": "Function `checkout_total` signature changed",
        }
    ]

    removal_change = analyzer.analyze(
        {"type": "function_removal", "function": "get_discount_percent"}
    )
    assert removal_change["impacted_nodes"] == [
        "apply_global_discount",
        "checkout_total",
        "main",
    ]

    type_change = analyzer.analyze({"type": "type_shape_change", "type_name": "Cart"})
    assert type_change["direct_impacted"] == [
        "calculate_subtotal",
        "checkout_total",
        "main",
    ]
    assert type_change["impacted_nodes"] == [
        "calculate_subtotal",
        "checkout_total",
        "main",
    ]

    variable_change = analyzer.analyze(
        {"type": "global_variable_change", "variable": "g_last_total"}
    )
    assert variable_change["direct_impacted"] == ["get_last_total", "set_last_total"]
    assert variable_change["impacted_nodes"] == [
        "checkout_total",
        "get_last_total",
        "main",
        "set_last_total",
    ]

    unknown_change = analyzer.analyze({"type": "unknown_change", "name": "x"})
    assert unknown_change["impacted_nodes"] == []
    assert unknown_change["obligations"] == []
    assert "Unsupported change type" in unknown_change["warning"]


def test_phase1_cli_entrypoint(tmp_path):
    output_dir = tmp_path / "phase1_out"
    command = [
        "python3",
        "-m",
        "phase1",
        "--repo",
        str(REPO_ROOT),
        "--out",
        str(output_dir),
    ]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    summary = payload["summary"]
    artifacts = payload["artifacts"]

    assert summary["parser_coverage"] >= 0.95
    assert summary["all_globals_linked"] is True
    assert Path(artifacts["sdg"]).exists()
    assert Path(artifacts["symbol_table"]).exists()
