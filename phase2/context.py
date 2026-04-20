from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import networkx as nx

from phase1.pipeline import SDGQueries


def _infer_function_line(path: Path, function_name: str) -> int:
    if not path.exists() or not path.is_file() or not function_name:
        return 1

    pattern = re.compile(rf"\b{re.escape(function_name)}\s*\(")
    for index, line in enumerate(
        path.read_text(errors="replace").splitlines(), start=1
    ):
        if pattern.search(line):
            return index
    return 1


def _read_file_slice(path: Path, line: int, radius: int = 12) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {
            "path": path.as_posix(),
            "start_line": 1,
            "end_line": 1,
            "source": "",
            "exists": False,
        }

    lines = path.read_text(errors="replace").splitlines()
    center = max(1, line)
    start = max(1, center - radius)
    end = min(len(lines), center + radius)
    snippet = "\n".join(lines[start - 1 : end])
    return {
        "path": path.as_posix(),
        "start_line": start,
        "end_line": end,
        "source": snippet,
        "exists": True,
    }


def function_dependencies(
    sdg: nx.MultiDiGraph, function_node_id: str
) -> dict[str, list[str]]:
    callers: set[str] = set()
    callees: set[str] = set()
    reads: set[str] = set()
    writes: set[str] = set()
    uses_types: set[str] = set()

    for source, _, _, edge_attrs in sdg.in_edges(
        function_node_id, keys=True, data=True
    ):
        edge_type = edge_attrs.get("edge_type")
        if edge_type == "calls":
            callers.add(source)

    for _, target, _, edge_attrs in sdg.out_edges(
        function_node_id, keys=True, data=True
    ):
        edge_type = edge_attrs.get("edge_type")
        if edge_type == "calls":
            callees.add(target)
        elif edge_type == "reads":
            reads.add(target)
        elif edge_type == "writes":
            writes.add(target)
        elif edge_type == "uses_type":
            uses_types.add(target)

    return {
        "callers": sorted(callers),
        "callees": sorted(callees),
        "reads": sorted(reads),
        "writes": sorted(writes),
        "uses_types": sorted(uses_types),
    }


def build_function_context_package(
    *,
    sdg: nx.MultiDiGraph,
    function_node_id: str,
    repo_root: Path,
    depth_hint: int = 1,
) -> dict[str, Any]:
    if not sdg.has_node(function_node_id):
        raise KeyError(f"Unknown function node: {function_node_id}")

    attrs = sdg.nodes[function_node_id]
    if attrs.get("node_type") != "Function":
        raise ValueError(f"Node is not a function: {function_node_id}")

    file_rel = attrs.get("file")
    line = int(attrs.get("line", 1))
    function_name = str(attrs.get("name", ""))

    code_slice = {
        "path": None,
        "start_line": 1,
        "end_line": 1,
        "source": "",
        "exists": False,
    }
    if isinstance(file_rel, str) and file_rel:
        file_path = repo_root / file_rel
        if line <= 1:
            line = _infer_function_line(file_path, function_name)
        code_slice = _read_file_slice(repo_root / file_rel, line)

    deps = function_dependencies(sdg, function_node_id)
    queries = SDGQueries(sdg)
    callers = queries.upstream_callers(
        attrs.get("name", function_node_id), transitive=False
    )

    immediate_dependencies = sorted(
        set(deps["callees"])
        | set(deps["reads"])
        | set(deps["writes"])
        | set(deps["uses_types"])
    )

    return {
        "target": {
            "node_id": function_node_id,
            "name": attrs.get("name", function_node_id),
            "file": file_rel,
            "line": line,
        },
        "code_slice": code_slice,
        "dependencies": deps,
        "immediate_callers": callers,
        "immediate_dependencies": immediate_dependencies,
        "depth_hint": max(1, depth_hint),
    }
