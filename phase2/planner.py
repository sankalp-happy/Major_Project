from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import networkx as nx


def _is_internal_function(node_attrs: dict[str, Any]) -> bool:
    return node_attrs.get("node_type") == "Function" and not bool(
        node_attrs.get("external", False)
    )


@dataclass(frozen=True)
class MigrationBatch:
    index: int
    component_ids: tuple[str, ...]
    function_node_ids: tuple[str, ...]
    function_names: tuple[str, ...]


@dataclass(frozen=True)
class MigrationPlan:
    internal_function_count: int
    dependency_edge_count: int
    scc_count: int
    batches: tuple[MigrationBatch, ...]
    component_members: dict[str, tuple[str, ...]]

    def node_to_batch_index(self) -> dict[str, int]:
        lookup: dict[str, int] = {}
        for batch in self.batches:
            for node_id in batch.function_node_ids:
                lookup[node_id] = batch.index
        return lookup


def build_function_dependency_graph(sdg: nx.MultiDiGraph) -> nx.DiGraph:
    """
    Build a dependency graph with edges `callee -> caller`.

    In the source SDG, call edges are represented as `caller -> callee`.
    Reversing this direction allows topological planning where dependencies
    naturally appear before dependents.
    """

    graph = nx.DiGraph()

    for node_id, attrs in sdg.nodes(data=True):
        if _is_internal_function(attrs):
            graph.add_node(node_id, **attrs)

    for caller, callee, _, edge_attrs in sdg.edges(keys=True, data=True):
        if edge_attrs.get("edge_type") != "calls":
            continue
        if not graph.has_node(caller) or not graph.has_node(callee):
            continue
        graph.add_edge(callee, caller)

    return graph


def _component_sort_key(
    condensed: nx.DiGraph, component_id: int, names_by_component: dict[int, list[str]]
) -> tuple[int, str]:
    return (-condensed.out_degree(component_id), names_by_component[component_id][0])


def plan_migration_batches(sdg: nx.MultiDiGraph) -> MigrationPlan:
    dependency_graph = build_function_dependency_graph(sdg)

    if dependency_graph.number_of_nodes() == 0:
        return MigrationPlan(
            internal_function_count=0,
            dependency_edge_count=0,
            scc_count=0,
            batches=(),
            component_members={},
        )

    sccs = list(nx.strongly_connected_components(dependency_graph))
    sccs.sort(key=lambda component: min(component))

    condensed = nx.condensation(dependency_graph, scc=sccs)

    names_by_component: dict[int, list[str]] = {}
    component_members: dict[str, tuple[str, ...]] = {}

    for component_id in condensed.nodes:
        members = sorted(condensed.nodes[component_id]["members"])
        member_names = sorted(
            dependency_graph.nodes[node_id].get("name", node_id) for node_id in members
        )
        names_by_component[component_id] = member_names
        component_members[f"scc:{component_id}"] = tuple(members)

    batches: list[MigrationBatch] = []
    generation_index = 0

    for generation in nx.topological_generations(condensed):
        sorted_components = sorted(
            generation,
            key=lambda component_id: _component_sort_key(
                condensed, component_id, names_by_component
            ),
        )

        component_labels = tuple(
            f"scc:{component_id}" for component_id in sorted_components
        )
        function_node_ids = tuple(
            node_id
            for component_id in sorted_components
            for node_id in sorted(component_members[f"scc:{component_id}"])
        )
        function_names = tuple(
            dependency_graph.nodes[node_id].get("name", node_id)
            for node_id in function_node_ids
        )

        batches.append(
            MigrationBatch(
                index=generation_index,
                component_ids=component_labels,
                function_node_ids=function_node_ids,
                function_names=function_names,
            )
        )
        generation_index += 1

    return MigrationPlan(
        internal_function_count=dependency_graph.number_of_nodes(),
        dependency_edge_count=dependency_graph.number_of_edges(),
        scc_count=len(sccs),
        batches=tuple(batches),
        component_members=component_members,
    )


def serialize_migration_plan(plan: MigrationPlan) -> dict[str, Any]:
    return {
        "internal_function_count": plan.internal_function_count,
        "dependency_edge_count": plan.dependency_edge_count,
        "scc_count": plan.scc_count,
        "batch_count": len(plan.batches),
        "batches": [
            {
                "index": batch.index,
                "component_ids": list(batch.component_ids),
                "function_node_ids": list(batch.function_node_ids),
                "function_names": list(batch.function_names),
            }
            for batch in plan.batches
        ],
        "component_members": {
            component_id: list(members)
            for component_id, members in sorted(plan.component_members.items())
        },
    }
