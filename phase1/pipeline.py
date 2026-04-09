from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import networkx as nx
from tree_sitter import Language, Node, Parser
import tree_sitter_c


C_EXTENSIONS = {".c", ".h"}
DECLARATOR_LIKE_TYPES = {
    "identifier",
    "init_declarator",
    "pointer_declarator",
    "array_declarator",
    "parenthesized_declarator",
}


@dataclass(frozen=True)
class ParsedFile:
    relative_path: str
    absolute_path: Path
    source: bytes
    tree: Any
    has_error: bool
    node_count: int


@dataclass
class Phase1Analysis:
    repo_root: Path
    parsed_files: dict[str, ParsedFile]
    ast_artifacts: dict[str, dict[str, Any]]
    symbol_table: dict[str, Any]
    function_analyses: dict[str, dict[str, Any]]
    unresolved_calls: list[dict[str, Any]]
    call_graph: nx.DiGraph
    include_graph: nx.DiGraph
    sdg: nx.MultiDiGraph
    report: dict[str, Any]
    artifact_paths: dict[str, str] | None = None


def iter_nodes(node: Node) -> Iterator[Node]:
    stack: list[Node] = [node]
    while stack:
        current = stack.pop()
        yield current
        if current.children:
            stack.extend(reversed(current.children))


def node_text(source: bytes, node: Node | None) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_same_node(a: Node | None, b: Node | None) -> bool:
    if a is None or b is None:
        return False
    return (
        a.type == b.type and a.start_byte == b.start_byte and a.end_byte == b.end_byte
    )


def node_within(child: Node | None, ancestor: Node | None) -> bool:
    if child is None or ancestor is None:
        return False
    return (
        ancestor.start_byte <= child.start_byte and child.end_byte <= ancestor.end_byte
    )


def extract_identifier_from_declarator(node: Node | None, source: bytes) -> str | None:
    if node is None:
        return None
    if node.type == "identifier":
        return node_text(source, node)

    declarator_child = node.child_by_field_name("declarator")
    if declarator_child is not None:
        identifier = extract_identifier_from_declarator(declarator_child, source)
        if identifier:
            return identifier

    for child in node.named_children:
        identifier = extract_identifier_from_declarator(child, source)
        if identifier:
            return identifier
    return None


def declaration_has_function_declarator(declaration_node: Node) -> bool:
    for descendant in iter_nodes(declaration_node):
        if descendant.type == "function_declarator":
            return True
    return False


def declaration_has_storage_class(
    declaration_node: Node, source: bytes, keyword: str
) -> bool:
    for child in declaration_node.named_children:
        if child.type == "storage_class_specifier":
            if normalize_space(node_text(source, child)) == keyword:
                return True
    return False


def is_file_scope(node: Node) -> bool:
    current = node.parent
    while current is not None:
        if current.type == "function_definition":
            return False
        current = current.parent
    return True


def function_name_from_definition(function_node: Node, source: bytes) -> str | None:
    declarator = function_node.child_by_field_name("declarator")
    return extract_identifier_from_declarator(declarator, source)


def enclosing_function_name(node: Node, source: bytes) -> str | None:
    current = node.parent
    while current is not None:
        if current.type == "function_definition":
            return function_name_from_definition(current, source)
        current = current.parent
    return None


def extract_declared_identifiers_from_declaration(
    declaration_node: Node, source: bytes
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    for child in declaration_node.named_children:
        if child.type == "function_declarator":
            continue
        if child.type in DECLARATOR_LIKE_TYPES:
            name = extract_identifier_from_declarator(child, source)
            if name and name not in seen:
                seen.add(name)
                names.append(name)

    if names:
        return names

    for descendant in iter_nodes(declaration_node):
        if descendant.type in DECLARATOR_LIKE_TYPES:
            name = extract_identifier_from_declarator(descendant, source)
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def extract_declaration_type(declaration_node: Node, source: bytes) -> str:
    parts: list[str] = []
    for child in declaration_node.named_children:
        if child.type in DECLARATOR_LIKE_TYPES or child.type == "function_declarator":
            break
        if child.type == "storage_class_specifier":
            continue
        parts.append(node_text(source, child))
    return normalize_space(" ".join(parts))


def extract_include_target(include_node: Node, source: bytes) -> tuple[str, bool]:
    for child in include_node.named_children:
        if child.type in {"string_literal", "system_lib_string"}:
            raw = node_text(source, child).strip()
            if raw.startswith("<") and raw.endswith(">"):
                return raw[1:-1], True
            if raw.startswith('"') and raw.endswith('"'):
                return raw[1:-1], False
            return raw, False
    return "", False


def sanitize_for_node_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    return cleaned.strip("_") or "unknown"


def build_ast_artifact(parsed_file: ParsedFile) -> dict[str, Any]:
    root = parsed_file.tree.root_node
    top_level_nodes = []
    for child in root.children:
        if not child.is_named:
            continue
        top_level_nodes.append(
            {
                "type": child.type,
                "start_line": child.start_point.row + 1,
                "start_col": child.start_point.column + 1,
                "end_line": child.end_point.row + 1,
                "end_col": child.end_point.column + 1,
            }
        )

    named_node_count = sum(1 for node in iter_nodes(root) if node.is_named)

    return {
        "file": parsed_file.relative_path,
        "has_error": parsed_file.has_error,
        "node_count": parsed_file.node_count,
        "named_node_count": named_node_count,
        "top_level_nodes": top_level_nodes,
    }


def is_declared_identifier(identifier_node: Node) -> bool:
    current = identifier_node
    while current.parent is not None:
        parent = current.parent

        if parent.type == "init_declarator":
            declarator = parent.child_by_field_name("declarator")
            return node_within(identifier_node, declarator)

        if parent.type in {
            "declaration",
            "parameter_declaration",
            "field_declaration",
            "function_declarator",
            "type_definition",
            "struct_specifier",
            "enum_specifier",
        }:
            declarator = parent.child_by_field_name("declarator")
            if declarator is None:
                return True
            return node_within(identifier_node, declarator)

        if parent.type.endswith("_expression") or parent.type in {
            "argument_list",
            "return_statement",
        }:
            return False

        if parent.type == "function_definition":
            return False

        current = parent

    return False


def is_assignment_left(identifier_node: Node, source: bytes) -> tuple[bool, str]:
    parent = identifier_node.parent
    if parent is None or parent.type != "assignment_expression":
        return False, ""
    left = parent.child_by_field_name("left")
    if not is_same_node(left, identifier_node):
        return False, ""
    operator_node = parent.child_by_field_name("operator")
    operator = node_text(source, operator_node)
    return True, operator


def is_update_target(identifier_node: Node) -> bool:
    parent = identifier_node.parent
    if parent is None or parent.type != "update_expression":
        return False
    argument = parent.child_by_field_name("argument")
    if argument is None:
        return True
    return is_same_node(argument, identifier_node)


def is_call_target(identifier_node: Node) -> bool:
    parent = identifier_node.parent
    if parent is None or parent.type != "call_expression":
        return False
    function_node = parent.child_by_field_name("function")
    return is_same_node(function_node, identifier_node)


def resolve_include_target(
    source_file: str, target: str, repo_files: set[str]
) -> tuple[str | None, bool]:
    candidates = [
        target,
        (Path(source_file).parent / target).as_posix(),
        (Path("include") / target).as_posix(),
        (Path("src") / target).as_posix(),
    ]
    for candidate in candidates:
        if candidate in repo_files:
            return candidate, True

    target_basename = Path(target).name
    matches = sorted(path for path in repo_files if Path(path).name == target_basename)
    if len(matches) == 1:
        return matches[0], True

    return None, False


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def serialize_digraph(graph: nx.DiGraph) -> dict[str, Any]:
    nodes = []
    for node_id, attrs in sorted(graph.nodes(data=True), key=lambda item: item[0]):
        nodes.append({"id": node_id, **_json_safe(attrs)})

    edges = []
    for source, target, attrs in graph.edges(data=True):
        edges.append({"source": source, "target": target, **_json_safe(attrs)})
    edges.sort(
        key=lambda edge: (
            edge["source"],
            edge["target"],
            edge.get("edge_type", ""),
            edge.get("classification", ""),
        )
    )

    return {
        "directed": True,
        "multigraph": False,
        "nodes": nodes,
        "edges": edges,
    }


def serialize_multidigraph(graph: nx.MultiDiGraph) -> dict[str, Any]:
    nodes = []
    for node_id, attrs in sorted(graph.nodes(data=True), key=lambda item: item[0]):
        nodes.append({"id": node_id, **_json_safe(attrs)})

    edges = []
    for source, target, key, attrs in graph.edges(keys=True, data=True):
        edges.append(
            {
                "source": source,
                "target": target,
                "key": key,
                **_json_safe(attrs),
            }
        )
    edges.sort(
        key=lambda edge: (
            edge["source"],
            edge["target"],
            edge.get("edge_type", ""),
            str(edge["key"]),
        )
    )

    return {
        "directed": True,
        "multigraph": True,
        "nodes": nodes,
        "edges": edges,
    }


def deserialize_multidigraph(payload: dict[str, Any]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for node in payload.get("nodes", []):
        node = dict(node)
        node_id = node.pop("id")
        graph.add_node(node_id, **node)

    for edge in payload.get("edges", []):
        edge = dict(edge)
        source = edge.pop("source")
        target = edge.pop("target")
        key = edge.pop("key")
        graph.add_edge(source, target, key=key, **edge)
    return graph


def sort_symbol_table(symbol_table: dict[str, Any]) -> dict[str, Any]:
    files = dict(sorted(symbol_table["files"].items(), key=lambda item: item[0]))

    functions: dict[str, list[dict[str, Any]]] = {}
    for name, records in sorted(
        symbol_table["functions"].items(), key=lambda item: item[0]
    ):
        functions[name] = sorted(
            records,
            key=lambda record: (
                record["kind"],
                record["file"],
                record["line"],
                record["column"],
            ),
        )

    variables: dict[str, list[dict[str, Any]]] = {}
    for name, records in sorted(
        symbol_table["variables"].items(), key=lambda item: item[0]
    ):
        variables[name] = sorted(
            records,
            key=lambda record: (
                record["scope"],
                record["file"],
                record["line"],
                record["column"],
                record.get("function", ""),
            ),
        )

    types: dict[str, list[dict[str, Any]]] = {}
    for name, records in sorted(
        symbol_table["types"].items(), key=lambda item: item[0]
    ):
        types[name] = sorted(
            records,
            key=lambda record: (
                record["kind"],
                record["file"],
                record["line"],
                record["column"],
            ),
        )

    includes = sorted(
        symbol_table["includes"],
        key=lambda include: (include["file"], include["line"], include["target"]),
    )

    return {
        "files": files,
        "functions": functions,
        "variables": variables,
        "types": types,
        "includes": includes,
    }


def parse_repository(repo_root: Path) -> dict[str, ParsedFile]:
    parser = Parser(Language(tree_sitter_c.language()))
    source_files = sorted(
        [
            path
            for path in repo_root.rglob("*")
            if path.is_file() and path.suffix in C_EXTENSIONS
        ],
        key=lambda path: path.as_posix(),
    )

    parsed_files: dict[str, ParsedFile] = {}
    for path in source_files:
        relative_path = path.relative_to(repo_root).as_posix()
        source = path.read_bytes()
        tree = parser.parse(source)
        node_count = sum(1 for _ in iter_nodes(tree.root_node))
        parsed_files[relative_path] = ParsedFile(
            relative_path=relative_path,
            absolute_path=path,
            source=source,
            tree=tree,
            has_error=tree.root_node.has_error,
            node_count=node_count,
        )
    return parsed_files


def analyze_phase1(repo_root: Path | str) -> Phase1Analysis:
    repo_root = Path(repo_root).resolve()
    parsed_files = parse_repository(repo_root)

    symbol_table: dict[str, Any] = {
        "files": {},
        "functions": defaultdict(list),
        "variables": defaultdict(list),
        "types": defaultdict(list),
        "includes": [],
    }
    ast_artifacts: dict[str, dict[str, Any]] = {}

    function_definition_nodes: list[tuple[str, str, Node, bytes]] = []
    function_definitions: dict[str, dict[str, Any]] = {}

    for relative_path, parsed in parsed_files.items():
        source = parsed.source
        root = parsed.tree.root_node

        symbol_table["files"][relative_path] = {
            "path": relative_path,
            "extension": Path(relative_path).suffix,
            "line_count": source.count(b"\n") + 1,
        }
        ast_artifacts[relative_path] = build_ast_artifact(parsed)

        for node in iter_nodes(root):
            if node.type == "preproc_include":
                target, is_system = extract_include_target(node, source)
                if target:
                    symbol_table["includes"].append(
                        {
                            "file": relative_path,
                            "target": target,
                            "is_system": is_system,
                            "line": node.start_point.row + 1,
                            "column": node.start_point.column + 1,
                        }
                    )
                continue

            if node.type == "function_definition":
                function_name = function_name_from_definition(node, source)
                if not function_name:
                    continue

                if function_name in function_definitions:
                    function_node_id = f"function:{function_name}@{relative_path}:{node.start_point.row + 1}"
                else:
                    function_node_id = f"function:{function_name}"

                body = node.child_by_field_name("body")
                signature_end = body.start_byte if body is not None else node.end_byte
                signature = normalize_space(
                    source[node.start_byte : signature_end].decode(
                        "utf-8", errors="replace"
                    )
                )

                definition_record = {
                    "name": function_name,
                    "kind": "definition",
                    "file": relative_path,
                    "line": node.start_point.row + 1,
                    "column": node.start_point.column + 1,
                    "signature": signature,
                    "node_id": function_node_id,
                }
                symbol_table["functions"][function_name].append(definition_record)
                if function_name not in function_definitions:
                    function_definitions[function_name] = definition_record

                function_definition_nodes.append(
                    (function_name, relative_path, node, source)
                )
                continue

            if node.type == "declaration":
                if declaration_has_function_declarator(node) and is_file_scope(node):
                    function_declarator = None
                    for descendant in iter_nodes(node):
                        if descendant.type == "function_declarator":
                            function_declarator = descendant
                            break

                    function_name = extract_identifier_from_declarator(
                        function_declarator, source
                    )
                    if function_name:
                        signature = normalize_space(node_text(source, node))
                        if signature.endswith(";"):
                            signature = signature[:-1].strip()
                        symbol_table["functions"][function_name].append(
                            {
                                "name": function_name,
                                "kind": "declaration",
                                "file": relative_path,
                                "line": node.start_point.row + 1,
                                "column": node.start_point.column + 1,
                                "signature": signature,
                                "node_id": function_definitions.get(
                                    function_name, {}
                                ).get("node_id", f"function:{function_name}"),
                            }
                        )
                    continue

                variable_names = extract_declared_identifiers_from_declaration(
                    node, source
                )
                if not variable_names:
                    continue

                scope = "global" if is_file_scope(node) else "local"
                owner_function = (
                    None if scope == "global" else enclosing_function_name(node, source)
                )
                is_extern = declaration_has_storage_class(node, source, "extern")
                variable_type = extract_declaration_type(node, source)

                for variable_name in variable_names:
                    symbol_table["variables"][variable_name].append(
                        {
                            "name": variable_name,
                            "scope": scope,
                            "file": relative_path,
                            "line": node.start_point.row + 1,
                            "column": node.start_point.column + 1,
                            "function": owner_function,
                            "type": variable_type,
                            "is_extern": is_extern,
                            "is_definition": scope == "global" and not is_extern,
                        }
                    )
                continue

            if node.type == "type_definition":
                alias_name = None
                alias_node = None
                for child in node.named_children:
                    if child.type == "type_identifier":
                        alias_name = node_text(source, child)
                        alias_node = child
                if alias_name:
                    kind = "typedef"
                    for descendant in iter_nodes(node):
                        if descendant.type == "struct_specifier":
                            kind = "typedef_struct"
                            break
                        if descendant.type == "enum_specifier":
                            kind = "typedef_enum"
                            break
                    symbol_table["types"][alias_name].append(
                        {
                            "name": alias_name,
                            "kind": kind,
                            "file": relative_path,
                            "line": (alias_node or node).start_point.row + 1,
                            "column": (alias_node or node).start_point.column + 1,
                        }
                    )
                continue

            if node.type in {"struct_specifier", "enum_specifier"}:
                if node.parent is not None and node.parent.type == "type_definition":
                    continue
                name_node = node.child_by_field_name("name")
                if name_node is None:
                    for child in node.named_children:
                        if child.type in {"identifier", "type_identifier"}:
                            name_node = child
                            break
                if name_node is None:
                    continue
                type_name = node_text(source, name_node)
                if not type_name:
                    continue
                symbol_table["types"][type_name].append(
                    {
                        "name": type_name,
                        "kind": "struct" if node.type == "struct_specifier" else "enum",
                        "file": relative_path,
                        "line": name_node.start_point.row + 1,
                        "column": name_node.start_point.column + 1,
                    }
                )

    global_variable_names = {
        variable_name
        for variable_name, records in symbol_table["variables"].items()
        if any(record["scope"] == "global" for record in records)
    }
    known_type_names = set(symbol_table["types"].keys())

    function_analyses: dict[str, dict[str, Any]] = {}
    for (
        function_name,
        relative_path,
        function_node,
        source,
    ) in function_definition_nodes:
        if function_name not in function_definitions:
            continue
        function_id = function_definitions[function_name]["node_id"]
        body = function_node.child_by_field_name("body")

        calls: list[dict[str, Any]] = []
        reads: set[str] = set()
        writes: set[str] = set()
        uses_types: set[str] = set()

        for descendant in iter_nodes(function_node):
            if descendant.type == "type_identifier":
                type_name = node_text(source, descendant)
                if type_name in known_type_names:
                    uses_types.add(type_name)

        if body is not None:
            for descendant in iter_nodes(body):
                if descendant.type == "call_expression":
                    function_expr = descendant.child_by_field_name("function")
                    callee = node_text(source, function_expr) if function_expr else ""
                    calls.append(
                        {
                            "callee": callee,
                            "line": descendant.start_point.row + 1,
                            "column": descendant.start_point.column + 1,
                            "is_identifier": bool(
                                function_expr is not None
                                and function_expr.type == "identifier"
                            ),
                        }
                    )
                    continue

                if descendant.type != "identifier":
                    continue

                identifier_name = node_text(source, descendant)
                if identifier_name not in global_variable_names:
                    continue
                if is_declared_identifier(descendant):
                    continue
                if is_call_target(descendant):
                    continue

                left_assignment, assignment_operator = is_assignment_left(
                    descendant, source
                )
                if left_assignment:
                    writes.add(identifier_name)
                    if assignment_operator and assignment_operator != "=":
                        reads.add(identifier_name)
                    continue

                if is_update_target(descendant):
                    reads.add(identifier_name)
                    writes.add(identifier_name)
                    continue

                reads.add(identifier_name)

        function_analyses[function_id] = {
            "function_id": function_id,
            "function_name": function_name,
            "file": relative_path,
            "calls": calls,
            "reads": sorted(reads),
            "writes": sorted(writes),
            "uses_types": sorted(uses_types),
        }

    call_graph = nx.DiGraph()
    unresolved_calls: list[dict[str, Any]] = []

    for function_name, definition in sorted(
        function_definitions.items(), key=lambda item: item[0]
    ):
        call_graph.add_node(
            definition["node_id"],
            node_type="Function",
            name=function_name,
            file=definition["file"],
            external=False,
        )

    for function_id, analysis in sorted(
        function_analyses.items(), key=lambda item: item[0]
    ):
        source_name = analysis["function_name"]
        for call in analysis["calls"]:
            callee = call["callee"]
            if call["is_identifier"] and callee in function_definitions:
                target_id = function_definitions[callee]["node_id"]
                classification = "internal"
                resolved = True
            elif call["is_identifier"] and callee in symbol_table["functions"]:
                target_id = f"function:declared_only:{callee}"
                classification = "unknown"
                resolved = False
            elif call["is_identifier"]:
                target_id = f"function:external:{callee}"
                classification = "external"
                resolved = False
            else:
                sanitized = sanitize_for_node_id(callee)
                target_id = (
                    f"function:unknown:{sanitized}:{call['line']}:{call['column']}"
                )
                classification = "unknown"
                resolved = False

            if not call_graph.has_node(target_id):
                call_graph.add_node(
                    target_id,
                    node_type="Function",
                    name=callee,
                    file=None,
                    external=classification != "internal",
                    classification=classification,
                )

            if call_graph.has_edge(function_id, target_id):
                call_graph[function_id][target_id]["count"] += 1
                call_graph[function_id][target_id]["sites"].append(
                    {"line": call["line"], "column": call["column"]}
                )
            else:
                call_graph.add_edge(
                    function_id,
                    target_id,
                    edge_type="calls",
                    callee=callee,
                    classification=classification,
                    resolved=resolved,
                    count=1,
                    sites=[{"line": call["line"], "column": call["column"]}],
                )

            if not resolved:
                unresolved_calls.append(
                    {
                        "caller": source_name,
                        "caller_id": function_id,
                        "callee": callee,
                        "classification": classification,
                        "line": call["line"],
                        "column": call["column"],
                    }
                )

    include_graph = nx.DiGraph()
    repo_files = set(symbol_table["files"].keys())

    for file_path in sorted(repo_files):
        include_graph.add_node(
            f"file:{file_path}",
            node_type="File",
            path=file_path,
            external=False,
        )

    for include in symbol_table["includes"]:
        source_file_id = f"file:{include['file']}"
        resolved_target, resolved = resolve_include_target(
            include["file"], include["target"], repo_files
        )

        if resolved and resolved_target is not None:
            target_file_id = f"file:{resolved_target}"
            target_path = resolved_target
            external = False
        else:
            target_file_id = f"file:external:{include['target']}"
            target_path = include["target"]
            external = True

        if not include_graph.has_node(target_file_id):
            include_graph.add_node(
                target_file_id,
                node_type="File",
                path=target_path,
                external=external,
            )

        include_graph.add_edge(
            source_file_id,
            target_file_id,
            edge_type="includes",
            include=include["target"],
            resolved=resolved,
            is_system=include["is_system"],
            line=include["line"],
            column=include["column"],
        )

    sdg = nx.MultiDiGraph()

    for node_id, attrs in include_graph.nodes(data=True):
        sdg.add_node(node_id, **attrs)

    for node_id, attrs in call_graph.nodes(data=True):
        sdg.add_node(node_id, **attrs)

    for variable_name, records in sorted(
        symbol_table["variables"].items(), key=lambda item: item[0]
    ):
        global_records = [record for record in records if record["scope"] == "global"]
        if not global_records:
            continue
        primary_record = sorted(
            global_records,
            key=lambda record: (
                not record["is_definition"],
                record["file"],
                record["line"],
                record["column"],
            ),
        )[0]
        sdg.add_node(
            f"variable:{variable_name}",
            node_type="Variable",
            name=variable_name,
            file=primary_record["file"],
            type=primary_record["type"],
        )

    for type_name, records in sorted(
        symbol_table["types"].items(), key=lambda item: item[0]
    ):
        primary_record = sorted(
            records,
            key=lambda record: (record["file"], record["line"], record["column"]),
        )[0]
        sdg.add_node(
            f"type:{type_name}",
            node_type="Type",
            name=type_name,
            file=primary_record["file"],
            kind=primary_record["kind"],
        )

    for source, target, attrs in include_graph.edges(data=True):
        sdg.add_edge(source, target, **attrs)

    for source, target, attrs in call_graph.edges(data=True):
        sdg.add_edge(source, target, **attrs)

    for function_id, analysis in function_analyses.items():
        for variable_name in analysis["reads"]:
            variable_id = f"variable:{variable_name}"
            if sdg.has_node(variable_id):
                sdg.add_edge(
                    function_id,
                    variable_id,
                    edge_type="reads",
                    variable=variable_name,
                )

        for variable_name in analysis["writes"]:
            variable_id = f"variable:{variable_name}"
            if sdg.has_node(variable_id):
                sdg.add_edge(
                    function_id,
                    variable_id,
                    edge_type="writes",
                    variable=variable_name,
                )

        for type_name in analysis["uses_types"]:
            type_id = f"type:{type_name}"
            if sdg.has_node(type_id):
                sdg.add_edge(
                    function_id,
                    type_id,
                    edge_type="uses_type",
                    type_name=type_name,
                )

    global_state_map: dict[str, dict[str, list[str]]] = {}
    function_name_by_id = {
        node_id: attrs.get("name", node_id)
        for node_id, attrs in sdg.nodes(data=True)
        if attrs.get("node_type") == "Function"
    }
    for variable_name in sorted(global_variable_names):
        variable_id = f"variable:{variable_name}"
        readers: set[str] = set()
        writers: set[str] = set()

        if sdg.has_node(variable_id):
            for source, _, _, edge_attrs in sdg.in_edges(
                variable_id, keys=True, data=True
            ):
                edge_type = edge_attrs.get("edge_type")
                if edge_type == "reads":
                    readers.add(function_name_by_id.get(source, source))
                if edge_type == "writes":
                    writers.add(function_name_by_id.get(source, source))

        global_state_map[variable_name] = {
            "readers": sorted(readers),
            "writers": sorted(writers),
        }

    resolved_internal_calls = 0
    for _, _, edge_attrs in call_graph.edges(data=True):
        if edge_attrs.get("classification") == "internal":
            resolved_internal_calls += edge_attrs.get("count", 1)

    sorted_symbol_table = sort_symbol_table(symbol_table)

    total_c_like_files = len(parsed_files)
    parsed_without_error = sum(
        1 for parsed in parsed_files.values() if not parsed.has_error
    )
    parser_coverage = (
        float(parsed_without_error) / float(total_c_like_files)
        if total_c_like_files
        else 0.0
    )

    report = {
        "repo_root": repo_root.as_posix(),
        "total_c_like_files": total_c_like_files,
        "parsed_without_error": parsed_without_error,
        "parser_coverage": parser_coverage,
        "files_with_parse_errors": sorted(
            relative_path
            for relative_path, parsed in parsed_files.items()
            if parsed.has_error
        ),
        "functions_defined": sum(
            1
            for records in sorted_symbol_table["functions"].values()
            for record in records
            if record["kind"] == "definition"
        ),
        "functions_declared": sum(
            1
            for records in sorted_symbol_table["functions"].values()
            for record in records
            if record["kind"] == "declaration"
        ),
        "global_variables": len(global_variable_names),
        "types": len(sorted_symbol_table["types"]),
        "includes": len(sorted_symbol_table["includes"]),
        "call_edges": call_graph.number_of_edges(),
        "include_edges": include_graph.number_of_edges(),
        "sdg_nodes": sdg.number_of_nodes(),
        "sdg_edges": sdg.number_of_edges(),
        "resolved_internal_calls": resolved_internal_calls,
        "unresolved_calls": len(unresolved_calls),
        "all_globals_linked": all(
            bool(mapping["readers"] or mapping["writers"])
            for mapping in global_state_map.values()
        ),
        "global_state_map": global_state_map,
    }

    return Phase1Analysis(
        repo_root=repo_root,
        parsed_files=parsed_files,
        ast_artifacts=dict(sorted(ast_artifacts.items(), key=lambda item: item[0])),
        symbol_table=sorted_symbol_table,
        function_analyses=dict(
            sorted(function_analyses.items(), key=lambda item: item[0])
        ),
        unresolved_calls=sorted(
            unresolved_calls,
            key=lambda record: (
                record["caller"],
                record["line"],
                record["column"],
                record["callee"],
            ),
        ),
        call_graph=call_graph,
        include_graph=include_graph,
        sdg=sdg,
        report=report,
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n")


def save_sdg_graph(graph: nx.MultiDiGraph, output_path: Path) -> None:
    write_json(output_path, serialize_multidigraph(graph))


def load_sdg_graph(path: Path | str) -> nx.MultiDiGraph:
    payload = json.loads(Path(path).read_text())
    return deserialize_multidigraph(payload)


def build_phase1(repo_root: Path | str, output_dir: Path | str) -> Phase1Analysis:
    analysis = analyze_phase1(repo_root)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ast_dir = output_dir / "ast"
    for relative_path, artifact in analysis.ast_artifacts.items():
        artifact_path = ast_dir / f"{relative_path}.json"
        write_json(artifact_path, artifact)

    symbol_table_path = output_dir / "symbol_table.json"
    call_graph_path = output_dir / "call_graph.json"
    include_graph_path = output_dir / "include_graph.json"
    sdg_path = output_dir / "sdg_v1.json"
    function_analysis_path = output_dir / "function_analysis.json"
    unresolved_calls_path = output_dir / "unresolved_calls.json"
    report_path = output_dir / "report.json"

    write_json(symbol_table_path, analysis.symbol_table)
    write_json(call_graph_path, serialize_digraph(analysis.call_graph))
    write_json(include_graph_path, serialize_digraph(analysis.include_graph))
    save_sdg_graph(analysis.sdg, sdg_path)
    write_json(function_analysis_path, analysis.function_analyses)
    write_json(unresolved_calls_path, analysis.unresolved_calls)
    write_json(report_path, analysis.report)

    analysis.artifact_paths = {
        "ast_dir": ast_dir.as_posix(),
        "symbol_table": symbol_table_path.as_posix(),
        "call_graph": call_graph_path.as_posix(),
        "include_graph": include_graph_path.as_posix(),
        "sdg": sdg_path.as_posix(),
        "function_analysis": function_analysis_path.as_posix(),
        "unresolved_calls": unresolved_calls_path.as_posix(),
        "report": report_path.as_posix(),
    }
    return analysis


def _edge_matches(edge_data: dict[str, Any], edge_types: set[str] | None) -> bool:
    if not edge_types:
        return True
    return edge_data.get("edge_type") in edge_types


class SDGQueries:
    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph

    def function_node_id(self, function_name: str) -> str | None:
        for node_id, attrs in self.graph.nodes(data=True):
            if attrs.get("node_type") != "Function":
                continue
            if attrs.get("name") != function_name:
                continue
            if attrs.get("external"):
                continue
            return node_id
        return None

    def variable_node_id(self, variable_name: str) -> str | None:
        candidate = f"variable:{variable_name}"
        if self.graph.has_node(candidate):
            return candidate
        return None

    def type_node_id(self, type_name: str) -> str | None:
        candidate = f"type:{type_name}"
        if self.graph.has_node(candidate):
            return candidate
        return None

    def upstream_callers(
        self, function_name: str, transitive: bool = True
    ) -> list[str]:
        start = self.function_node_id(function_name)
        if start is None:
            return []

        callers: set[str] = set()
        queue: deque[str] = deque([start])
        visited: set[str] = {start}

        while queue:
            current = queue.popleft()
            for source, _, _, edge_data in self.graph.in_edges(
                current, keys=True, data=True
            ):
                if edge_data.get("edge_type") != "calls":
                    continue
                if source in callers:
                    continue

                source_attrs = self.graph.nodes[source]
                if source_attrs.get("node_type") == "Function" and not source_attrs.get(
                    "external", False
                ):
                    callers.add(source)

                if transitive and source not in visited:
                    visited.add(source)
                    queue.append(source)

        caller_names = [
            self.graph.nodes[node_id].get("name", node_id) for node_id in callers
        ]
        return sorted(caller_names)

    def downstream_dependents(
        self, start_node_id: str, edge_types: set[str] | None = None
    ) -> list[str]:
        if not self.graph.has_node(start_node_id):
            return []

        dependents: set[str] = set()
        queue: deque[str] = deque([start_node_id])

        while queue:
            current = queue.popleft()
            for _, target, _, edge_data in self.graph.out_edges(
                current, keys=True, data=True
            ):
                if not _edge_matches(edge_data, edge_types):
                    continue
                if target in dependents:
                    continue
                dependents.add(target)
                queue.append(target)

        dependents.discard(start_node_id)
        return sorted(dependents)

    def transitive_closure(
        self, start_node_id: str, edge_types: set[str] | None = None
    ) -> list[str]:
        return self.downstream_dependents(start_node_id, edge_types=edge_types)

    def global_state_impact_path(
        self, function_name: str, variable_name: str | None = None
    ) -> list[list[str]]:
        source_id = self.function_node_id(function_name)
        if source_id is None:
            return []

        variable_ids: list[str] = []
        if variable_name is not None:
            variable_id = self.variable_node_id(variable_name)
            if variable_id is not None:
                variable_ids.append(variable_id)
        else:
            for _, target, _, edge_data in self.graph.out_edges(
                source_id, keys=True, data=True
            ):
                if edge_data.get("edge_type") in {"reads", "writes"}:
                    variable_ids.append(target)

        paths: set[tuple[str, ...]] = set()
        for variable_id in variable_ids:
            for accessor, _, _, edge_data in self.graph.in_edges(
                variable_id, keys=True, data=True
            ):
                if edge_data.get("edge_type") not in {"reads", "writes"}:
                    continue
                accessor_attrs = self.graph.nodes[accessor]
                if accessor_attrs.get("node_type") != "Function":
                    continue

                try:
                    call_path = nx.shortest_path(
                        self._calls_only_graph(), source=source_id, target=accessor
                    )
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue

                path = list(call_path)
                path.append(variable_id)

                for affected_fn, _, _, affected_edge_data in self.graph.in_edges(
                    variable_id, keys=True, data=True
                ):
                    if affected_edge_data.get("edge_type") not in {"reads", "writes"}:
                        continue
                    if affected_fn == accessor:
                        continue
                    affected_attrs = self.graph.nodes[affected_fn]
                    if affected_attrs.get("node_type") != "Function":
                        continue
                    paths.add(tuple(path + [affected_fn]))

                paths.add(tuple(path))

        return [list(path) for path in sorted(paths)]

    def _calls_only_graph(self) -> nx.DiGraph:
        graph = nx.DiGraph()
        for node_id, attrs in self.graph.nodes(data=True):
            if attrs.get("node_type") == "Function":
                graph.add_node(node_id)
        for source, target, _, edge_data in self.graph.edges(keys=True, data=True):
            if edge_data.get("edge_type") == "calls":
                graph.add_edge(source, target)
        return graph


class ImpactAnalyzer:
    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph
        self.queries = SDGQueries(graph)

    def analyze(self, change_event: dict[str, Any]) -> dict[str, Any]:
        change_type = change_event.get("type")

        if change_type == "function_signature_change":
            return self._function_signature_change(change_event)
        if change_type == "function_removal":
            return self._function_removal(change_event)
        if change_type == "type_shape_change":
            return self._type_shape_change(change_event)
        if change_type == "global_variable_change":
            return self._global_variable_change(change_event)

        return {
            "change": change_event,
            "impacted_nodes": [],
            "obligations": [],
            "warning": f"Unsupported change type: {change_type}",
        }

    def _function_signature_change(self, event: dict[str, Any]) -> dict[str, Any]:
        function_name = event.get("function") or event.get("name")
        if not function_name:
            return {"change": event, "impacted_nodes": [], "obligations": []}

        direct_callers = self.queries.upstream_callers(function_name, transitive=False)
        transitive_callers = self.queries.upstream_callers(
            function_name, transitive=True
        )

        obligations = [
            {
                "target": caller,
                "action": "update_call_signature",
                "reason": f"Function `{function_name}` signature changed",
            }
            for caller in transitive_callers
        ]

        return {
            "change": event,
            "impacted_nodes": sorted(transitive_callers),
            "obligations": obligations,
            "direct_callers": sorted(direct_callers),
        }

    def _function_removal(self, event: dict[str, Any]) -> dict[str, Any]:
        function_name = event.get("function") or event.get("name")
        if not function_name:
            return {"change": event, "impacted_nodes": [], "obligations": []}

        transitive_callers = self.queries.upstream_callers(
            function_name, transitive=True
        )
        obligations = [
            {
                "target": caller,
                "action": "remove_or_replace_call",
                "reason": f"Function `{function_name}` removed",
            }
            for caller in transitive_callers
        ]

        return {
            "change": event,
            "impacted_nodes": sorted(transitive_callers),
            "obligations": obligations,
        }

    def _type_shape_change(self, event: dict[str, Any]) -> dict[str, Any]:
        type_name = event.get("type_name") or event.get("name")
        if not type_name:
            return {"change": event, "impacted_nodes": [], "obligations": []}

        type_id = self.queries.type_node_id(type_name)
        if type_id is None:
            return {"change": event, "impacted_nodes": [], "obligations": []}

        directly_impacted: set[str] = set()
        for source, _, _, edge_data in self.graph.in_edges(
            type_id, keys=True, data=True
        ):
            if edge_data.get("edge_type") == "uses_type":
                source_attrs = self.graph.nodes[source]
                if source_attrs.get("node_type") == "Function":
                    directly_impacted.add(source_attrs.get("name", source))

        propagated: set[str] = set(directly_impacted)
        for function_name in directly_impacted:
            propagated.update(
                self.queries.upstream_callers(function_name, transitive=True)
            )

        obligations = [
            {
                "target": function_name,
                "action": "update_type_usage",
                "reason": f"Type `{type_name}` shape changed",
            }
            for function_name in sorted(propagated)
        ]

        return {
            "change": event,
            "impacted_nodes": sorted(propagated),
            "obligations": obligations,
            "direct_impacted": sorted(directly_impacted),
        }

    def _global_variable_change(self, event: dict[str, Any]) -> dict[str, Any]:
        variable_name = event.get("variable") or event.get("name")
        if not variable_name:
            return {"change": event, "impacted_nodes": [], "obligations": []}

        variable_id = self.queries.variable_node_id(variable_name)
        if variable_id is None:
            return {"change": event, "impacted_nodes": [], "obligations": []}

        direct_impacted: set[str] = set()
        for source, _, _, edge_data in self.graph.in_edges(
            variable_id, keys=True, data=True
        ):
            if edge_data.get("edge_type") not in {"reads", "writes"}:
                continue
            source_attrs = self.graph.nodes[source]
            if source_attrs.get("node_type") == "Function":
                direct_impacted.add(source_attrs.get("name", source))

        propagated: set[str] = set(direct_impacted)
        for function_name in direct_impacted:
            propagated.update(
                self.queries.upstream_callers(function_name, transitive=True)
            )

        obligations = [
            {
                "target": function_name,
                "action": "update_global_reference",
                "reason": f"Global variable `{variable_name}` changed",
            }
            for function_name in sorted(propagated)
        ]

        return {
            "change": event,
            "impacted_nodes": sorted(propagated),
            "obligations": obligations,
            "direct_impacted": sorted(direct_impacted),
        }


def phase1_summary(analysis: Phase1Analysis) -> dict[str, Any]:
    return {
        "repo_root": analysis.repo_root.as_posix(),
        "parser_coverage": analysis.report["parser_coverage"],
        "functions_defined": analysis.report["functions_defined"],
        "global_variables": analysis.report["global_variables"],
        "types": analysis.report["types"],
        "unresolved_calls": analysis.report["unresolved_calls"],
        "sdg_nodes": analysis.report["sdg_nodes"],
        "sdg_edges": analysis.report["sdg_edges"],
        "all_globals_linked": analysis.report["all_globals_linked"],
    }


def run_cli(args: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Phase 1 SDG artifacts for a C repository"
    )
    parser.add_argument(
        "--repo",
        default="repo",
        help="Path to the C repository root (default: repo)",
    )
    parser.add_argument(
        "--out",
        default="artifacts/phase1",
        help="Output directory for phase 1 artifacts",
    )

    parsed_args = parser.parse_args(list(args) if args is not None else None)
    analysis = build_phase1(parsed_args.repo, parsed_args.out)

    output = {
        "summary": phase1_summary(analysis),
        "artifacts": analysis.artifact_paths,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0
