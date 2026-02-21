import { useCallback, useEffect, useMemo, useState } from "react";
import type { Node, Relationship } from "@neo4j-nvl/base";
import {
  getGraphStatus,
  getGraphEntities,
  getGraphNeighborhood,
  getEntityHistory,
  type GraphNode,
  type GraphEdge,
  type EntityHistoryResponse,
} from "../api/client";

const ENTITY_TYPE_COLORS: Record<string, string> = {
  Person: "#6366f1",
  Team: "#8b5cf6",
  Project: "#3b82f6",
  Technology: "#10b981",
  Process: "#f59e0b",
  Concept: "#ec4899",
  Asset: "#6b7280",
};

const DEFAULT_COLOR = "#9ca3af";

function toNvlNode(graphNode: GraphNode, connectionCount: number): Node {
  return {
    id: graphNode.uuid,
    caption: graphNode.name,
    color: ENTITY_TYPE_COLORS[graphNode.entity_type] ?? DEFAULT_COLOR,
    size: Math.max(20, Math.min(50, 20 + connectionCount * 5)),
  };
}

function toNvlRel(
  graphEdge: GraphEdge,
  nameToUuid: Map<string, string>
): Relationship {
  return {
    id: graphEdge.uuid,
    from: nameToUuid.get(graphEdge.source_name) ?? graphEdge.source_name,
    to: nameToUuid.get(graphEdge.target_name) ?? graphEdge.target_name,
    caption: graphEdge.relationship_type,
    color: "#94a3b8",
    width: 2,
  };
}

function countConnections(
  edges: GraphEdge[]
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const e of edges) {
    counts.set(e.source_name, (counts.get(e.source_name) ?? 0) + 1);
    counts.set(e.target_name, (counts.get(e.target_name) ?? 0) + 1);
  }
  return counts;
}

interface GraphExplorerState {
  graphNodes: GraphNode[];
  graphEdges: GraphEdge[];
  selectedEntity: GraphNode | null;
  selectedEntityHistory: EntityHistoryResponse | null;
  loading: boolean;
  error: string | null;
  entityCount: number;
}

export function useGraphExplorer() {
  const [state, setState] = useState<GraphExplorerState>({
    graphNodes: [],
    graphEdges: [],
    selectedEntity: null,
    selectedEntityHistory: null,
    loading: true,
    error: null,
    entityCount: -1, // -1 = not yet loaded
  });

  // Load initial graph on mount
  useEffect(() => {
    let cancelled = false;
    async function loadInitialGraph() {
      try {
        const status = await getGraphStatus();
        if (cancelled) return;

        if (status.total_entities === 0) {
          setState((s) => ({
            ...s,
            loading: false,
            entityCount: 0,
          }));
          return;
        }

        // Get first entity to seed the canvas
        const entityList = await getGraphEntities({ limit: 1 });
        if (cancelled) return;

        if (entityList.entities.length === 0) {
          setState((s) => ({
            ...s,
            loading: false,
            entityCount: 0,
          }));
          return;
        }

        const firstEntity = entityList.entities[0];
        const neighborhood = await getGraphNeighborhood(firstEntity.name);
        if (cancelled) return;

        const allNodes: GraphNode[] = [
          neighborhood.center,
          ...neighborhood.nodes,
        ];
        setState((s) => ({
          ...s,
          graphNodes: allNodes,
          graphEdges: neighborhood.edges,
          loading: false,
          entityCount: status.total_entities,
        }));
      } catch (err) {
        if (cancelled) return;
        setState((s) => ({
          ...s,
          loading: false,
          error:
            err instanceof Error ? err.message : "Failed to load graph data",
        }));
      }
    }

    loadInitialGraph();
    return () => {
      cancelled = true;
    };
  }, []);

  // Convert graph data to NVL nodes/rels with useMemo for stable references
  const connectionCounts = useMemo(
    () => countConnections(state.graphEdges),
    [state.graphEdges]
  );

  const nameToUuid = useMemo(() => {
    const map = new Map<string, string>();
    for (const n of state.graphNodes) {
      map.set(n.name, n.uuid);
    }
    return map;
  }, [state.graphNodes]);

  const nodes: Node[] = useMemo(
    () =>
      state.graphNodes.map((gn) =>
        toNvlNode(gn, connectionCounts.get(gn.name) ?? 0)
      ),
    [state.graphNodes, connectionCounts]
  );

  const rels: Relationship[] = useMemo(
    () => state.graphEdges.map((ge) => toNvlRel(ge, nameToUuid)),
    [state.graphEdges, nameToUuid]
  );

  const selectEntity = useCallback(
    async (node: Node) => {
      const graphNode = state.graphNodes.find((gn) => gn.uuid === node.id);
      if (!graphNode) return;

      setState((s) => ({ ...s, selectedEntity: graphNode }));

      try {
        const history = await getEntityHistory(graphNode.name);
        setState((s) => ({ ...s, selectedEntityHistory: history }));
      } catch {
        // Non-critical: history may not be available
        setState((s) => ({ ...s, selectedEntityHistory: null }));
      }
    },
    [state.graphNodes]
  );

  const expandNeighborhood = useCallback(async (node: Node) => {
    try {
      const neighborhood = await getGraphNeighborhood(node.caption ?? "");

      setState((s) => {
        const existingNodeIds = new Set(s.graphNodes.map((n) => n.uuid));
        const existingEdgeIds = new Set(s.graphEdges.map((e) => e.uuid));

        const allNewNodes: GraphNode[] = [
          neighborhood.center,
          ...neighborhood.nodes,
        ];
        const newNodes = allNewNodes.filter(
          (n) => !existingNodeIds.has(n.uuid)
        );
        const newEdges = neighborhood.edges.filter(
          (e) => !existingEdgeIds.has(e.uuid)
        );

        return {
          ...s,
          graphNodes: [...s.graphNodes, ...newNodes],
          graphEdges: [...s.graphEdges, ...newEdges],
        };
      });
    } catch {
      // Expansion failure is non-critical
    }
  }, []);

  const focusEntity = useCallback(async (entityName: string) => {
    try {
      setState((s) => ({ ...s, loading: true, error: null }));
      const neighborhood = await getGraphNeighborhood(entityName);

      const allNodes: GraphNode[] = [
        neighborhood.center,
        ...neighborhood.nodes,
      ];
      setState((s) => ({
        ...s,
        graphNodes: allNodes,
        graphEdges: neighborhood.edges,
        loading: false,
        selectedEntity: neighborhood.center,
      }));

      // Also load history for the focused entity
      try {
        const history = await getEntityHistory(entityName);
        setState((s) => ({ ...s, selectedEntityHistory: history }));
      } catch {
        setState((s) => ({ ...s, selectedEntityHistory: null }));
      }
    } catch (err) {
      setState((s) => ({
        ...s,
        loading: false,
        error:
          err instanceof Error ? err.message : "Failed to load entity data",
      }));
    }
  }, []);

  const deselectEntity = useCallback(() => {
    setState((s) => ({
      ...s,
      selectedEntity: null,
      selectedEntityHistory: null,
    }));
  }, []);

  // Edges for the currently selected entity (for sidebar)
  const selectedEntityEdges = useMemo(() => {
    if (!state.selectedEntity) return [];
    const name = state.selectedEntity.name;
    return state.graphEdges.filter(
      (e) => e.source_name === name || e.target_name === name
    );
  }, [state.selectedEntity, state.graphEdges]);

  return {
    nodes,
    rels,
    selectedEntity: state.selectedEntity,
    selectedEntityHistory: state.selectedEntityHistory,
    selectedEntityEdges,
    loading: state.loading,
    error: state.error,
    entityCount: state.entityCount,
    selectEntity,
    expandNeighborhood,
    focusEntity,
    deselectEntity,
  };
}
