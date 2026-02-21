import React, { useRef, useMemo } from "react";
import { InteractiveNvlWrapper } from "@neo4j-nvl/react";
import type { MouseEventCallbacks } from "@neo4j-nvl/react";
import type { Node, Relationship, HitTargets } from "@neo4j-nvl/base";

interface GraphCanvasProps {
  nodes: Node[];
  rels: Relationship[];
  onNodeClick: (node: Node) => void;
  onNodeDoubleClick: (node: Node) => void;
  onCanvasClick: () => void;
}

function GraphCanvasInner({
  nodes,
  rels,
  onNodeClick,
  onNodeDoubleClick,
  onCanvasClick,
}: GraphCanvasProps) {
  const nvlRef = useRef(null);

  const mouseEventCallbacks: MouseEventCallbacks = useMemo(
    () => ({
      onNodeClick: (node: Node, _hitTargets: HitTargets, _event: MouseEvent) =>
        onNodeClick(node),
      onNodeDoubleClick: (
        node: Node,
        _hitTargets: HitTargets,
        _event: MouseEvent
      ) => onNodeDoubleClick(node),
      onCanvasClick: (_event: MouseEvent) => onCanvasClick(),
      onZoom: true,
      onPan: true,
      onDrag: true,
    }),
    [onNodeClick, onNodeDoubleClick, onCanvasClick]
  );

  return (
    <div className="w-full h-full" style={{ minHeight: 400 }}>
      <InteractiveNvlWrapper
        ref={nvlRef}
        nodes={nodes}
        rels={rels}
        layout="forceDirected"
        mouseEventCallbacks={mouseEventCallbacks}
        nvlOptions={{
          initialZoom: 1,
          minZoom: 0.1,
          maxZoom: 5,
          renderer: "canvas",
          disableTelemetry: true,
        }}
      />
    </div>
  );
}

const GraphCanvas = React.memo(GraphCanvasInner);
export default GraphCanvas;
