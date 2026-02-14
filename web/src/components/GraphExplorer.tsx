import { useCallback, useEffect, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { GraphEdge, GraphNode, SubgraphResponse } from "../api/client";

const LABEL_COLORS: Record<string, string> = {
  Metric: "#6366f1",     // indigo
  Event: "#f59e0b",      // amber
  KPI: "#10b981",        // emerald
  Document: "#64748b",   // slate
  Team: "#ec4899",       // pink
  DataSource: "#06b6d4", // cyan
};

const DEFAULT_COLOR = "#9ca3af"; // gray-400

interface Props {
  data: SubgraphResponse | null;
  loading: boolean;
  onNodeClick?: (name: string, label: string) => void;
  selectedNode?: string | null;
  width?: number;
  height?: number;
}

interface FGNode {
  id: string;
  label: string;
  isCenter: boolean;
  x?: number;
  y?: number;
}

interface FGEdge {
  source: string | FGNode;
  target: string | FGNode;
  rel_type: string;
  confidence?: number | null;
}

interface FGData {
  nodes: FGNode[];
  links: FGEdge[];
}

function toForceGraphData(data: SubgraphResponse): FGData {
  return {
    nodes: data.nodes.map((n: GraphNode) => ({
      id: n.id,
      label: n.label,
      isCenter: n.isCenter ?? false,
    })),
    links: data.edges.map((e: GraphEdge) => ({
      source: e.source,
      target: e.target,
      rel_type: e.rel_type,
      confidence: e.confidence,
    })),
  };
}

export default function GraphExplorer({
  data,
  loading,
  onNodeClick,
  selectedNode,
  width,
  height,
}: Props) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: width ?? 800, h: height ?? 500 });

  // Auto-size to container
  useEffect(() => {
    if (width && height) {
      setDims({ w: width, h: height });
      return;
    }
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      const { width: w, height: h } = entries[0].contentRect;
      if (w > 0 && h > 0) setDims({ w, h });
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, [width, height]);

  // Center graph on data change
  useEffect(() => {
    if (data && fgRef.current) {
      setTimeout(() => fgRef.current?.zoomToFit(300, 40), 200);
    }
  }, [data]);

  const handleNodeClick = useCallback(
    (node: FGNode) => {
      onNodeClick?.(node.id, node.label);
    },
    [onNodeClick]
  );

  const nodeCanvasObject = useCallback(
    (node: FGNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const fontSize = Math.max(10 / globalScale, 3);
      const radius = node.isCenter ? 7 : 5;
      const color = LABEL_COLORS[node.label] ?? DEFAULT_COLOR;
      const isSelected = node.id === selectedNode;

      // Node circle
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();

      // Selection ring
      if (isSelected) {
        ctx.strokeStyle = "#1e1b4b";
        ctx.lineWidth = 2 / globalScale;
        ctx.stroke();
      }

      // Label
      ctx.font = `${node.isCenter ? "bold " : ""}${fontSize}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = "#374151";
      ctx.fillText(node.id, x, y + radius + 2);
    },
    [selectedNode]
  );

  const linkCanvasObject = useCallback(
    (link: FGEdge, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const src = link.source as FGNode;
      const tgt = link.target as FGNode;
      if (!src.x || !tgt.x) return;

      // Line
      ctx.beginPath();
      ctx.moveTo(src.x, src.y!);
      ctx.lineTo(tgt.x, tgt.y!);
      ctx.strokeStyle = "#d1d5db";
      ctx.lineWidth = 1 / globalScale;
      ctx.stroke();

      // Arrow
      const angle = Math.atan2(tgt.y! - src.y!, tgt.x - src.x);
      const arrowLen = 4 / globalScale;
      const mx = (src.x + tgt.x) / 2;
      const my = (src.y! + tgt.y!) / 2;

      ctx.beginPath();
      ctx.moveTo(mx, my);
      ctx.lineTo(
        mx - arrowLen * Math.cos(angle - Math.PI / 6),
        my - arrowLen * Math.sin(angle - Math.PI / 6)
      );
      ctx.lineTo(
        mx - arrowLen * Math.cos(angle + Math.PI / 6),
        my - arrowLen * Math.sin(angle + Math.PI / 6)
      );
      ctx.fillStyle = "#9ca3af";
      ctx.fill();

      // Edge label
      if (globalScale > 0.8) {
        const fontSize = Math.max(8 / globalScale, 2.5);
        ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.fillStyle = "#9ca3af";
        ctx.fillText(link.rel_type, mx, my - 2);
      }
    },
    []
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-gray-400">
        <span className="inline-block w-2 h-2 bg-indigo-400 rounded-full animate-pulse mr-2" />
        Loading graph...
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-gray-400">
        Search for an entity to explore its knowledge graph.
      </div>
    );
  }

  const graphData = toForceGraphData(data);

  return (
    <div ref={containerRef} className="w-full h-full relative">
      {/* Legend */}
      <div className="absolute top-2 right-2 bg-white/90 border border-gray-200 rounded-lg p-2 text-xs space-y-1 z-10">
        {Object.entries(LABEL_COLORS).map(([label, color]) => (
          <div key={label} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-gray-600">{label}</span>
          </div>
        ))}
      </div>

      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        width={dims.w}
        height={dims.h}
        nodeCanvasObject={nodeCanvasObject}
        linkCanvasObject={linkCanvasObject}
        onNodeClick={handleNodeClick}
        cooldownTicks={60}
        nodeRelSize={6}
        enableNodeDrag
        enableZoomInteraction
        enablePanInteraction
      />
    </div>
  );
}
