import { useEffect } from 'react';
import ReactFlow, {
  BackgroundVariant,
  type Node,
  type Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
} from 'reactflow';
import 'reactflow/dist/style.css';
import dagre from 'dagre';
import { useStore } from '../../store';
import TreeNode from './TreeNode';

const nodeTypes = {
  custom: TreeNode,
};

export default function TreeCanvas() {
  const { entries, currentLane, lanes, highlightedPaths, setHighlightedPaths, setSelectedNode } = useStore();
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // 计算当前 Lane 的高亮路径
  useEffect(() => {
    const currentLanePointer = lanes.find(l => l.lane === currentLane);
    if (!currentLanePointer || !currentLanePointer.leaf_id) {
      setHighlightedPaths(new Set());
      return;
    }

    // 从 leaf_id 沿 parent 向上走到根
    const pathSet = new Set<string>();
    let currentId: string | null = currentLanePointer.leaf_id;

    while (currentId) {
      pathSet.add(currentId);
      const entry = entries.find(e => e.id === currentId);
      currentId = entry?.parent || null;
    }

    setHighlightedPaths(pathSet);
  }, [currentLane, lanes, entries]);

  // 转换 entries 为 React Flow 的节点和边
  useEffect(() => {
    if (entries.length === 0) return;

    // 创建节点
    const newNodes: Node[] = entries.map((entry) => {
      const isHighlighted = highlightedPaths.has(entry.id);
      const laneIndex = lanes.findIndex(l => l.lane === entry.lane);
      const laneColor = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'][laneIndex % 4];

      return {
        id: entry.id,
        type: 'custom',
        position: { x: 0, y: 0 }, // 将由布局算法设置
        data: {
          entry,
          isHighlighted,
          laneColor,
        },
      };
    });

    // 创建边
    const newEdges: Edge[] = entries
      .filter(e => e.parent)
      .map((entry) => {
        const isHighlighted = highlightedPaths.has(entry.id) && highlightedPaths.has(entry.parent!);
        const laneIndex = lanes.findIndex(l => l.lane === entry.lane);
        const laneColor = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'][laneIndex % 4];

        return {
          id: `${entry.parent}-${entry.id}`,
          source: entry.parent!,
          target: entry.id,
          type: 'smoothstep',
          animated: isHighlighted,
          style: {
            stroke: isHighlighted ? laneColor : 'rgba(11, 11, 11, 0.10)',
            strokeWidth: isHighlighted ? 2.5 : 1,
          },
        };
      });

    // 使用 dagre 计算布局
    const layoutedNodes = getLayoutedElements(newNodes, newEdges);
    setNodes(layoutedNodes);
    setEdges(newEdges);
  }, [entries, highlightedPaths, lanes]);

  const onNodeClick = (_: any, node: Node) => {
    setSelectedNode(node.id);
  };

  return (
    <div className="w-full h-full bg-surface-1">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.1}
        maxZoom={2}
      >
        <Background color="#e1e0d9" gap={16} size={1} variant={BackgroundVariant.Dots} />
        <Controls />
        <MiniMap
          nodeColor={(node) => {
            const isHighlighted = highlightedPaths.has(node.id);
            return isHighlighted ? '#2a78d6' : '#898781';
          }}
          maskColor="rgba(252, 252, 251, 0.8)"
        />
      </ReactFlow>
    </div>
  );
}

// 使用 dagre 计算布局
function getLayoutedElements(nodes: Node[], edges: Edge[]) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: 'TB', nodesep: 28, ranksep: 56 });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: 280, height: 80 });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  return nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      position: {
        x: nodeWithPosition.x - 140,
        y: nodeWithPosition.y - 40,
      },
    };
  });
}
