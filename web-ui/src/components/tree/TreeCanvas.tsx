import { useEffect, useMemo } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Edge,
  type Node,
  useEdgesState,
  useNodesState,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useStore } from '../../store';
import type { Entry } from '../../types';
import { getLanePath } from '../../utils/history';
import TreeNode, { type ConversationRound } from './TreeNode';
import TreeNodeDetailPanel from './TreeNodeDetailPanel';

const nodeTypes = {
  custom: TreeNode,
};

const laneColors = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'];

export default function TreeCanvas() {
  const {
    entries,
    currentLane,
    lanes,
    highlightedPaths,
    selectedNodeId,
    setHighlightedPaths,
    setSelectedNode,
  } = useStore();
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const roundGraph = useMemo(
    () => buildRoundGraph(entries, lanes.map((lane) => lane.lane)),
    [entries, lanes]
  );

  useEffect(() => {
    const pathSet = new Set(getLanePath(entries, lanes, currentLane).map((entry) => entry.id));
    setHighlightedPaths(pathSet);
  }, [currentLane, lanes, entries, setHighlightedPaths]);

  useEffect(() => {
    if (roundGraph.rounds.length === 0) {
      setNodes([]);
      setEdges([]);
      return;
    }

    const newNodes: Node[] = roundGraph.rounds.map((round) => {
      const laneIndex = getLaneIndex(round.lane, lanes.map((lane) => lane.lane));
      const laneColor = laneColors[laneIndex % laneColors.length];
      const isHighlighted = round.entryIds.some((id) => highlightedPaths.has(id));

      return {
        id: round.id,
        type: 'custom',
        position: {
          x: laneIndex * 228,
          y: round.depth * 136,
        },
        data: {
          round,
          isHighlighted,
          laneColor,
        },
      };
    });

    const newEdges: Edge[] = roundGraph.edges.map((edge) => {
      const targetRound = roundGraph.roundById.get(edge.target);
      const laneIndex = getLaneIndex(targetRound?.lane || currentLane, lanes.map((lane) => lane.lane));
      const laneColor = laneColors[laneIndex % laneColors.length];
      const isHighlighted =
        roundGraph.roundById.get(edge.source)?.entryIds.some((id) => highlightedPaths.has(id)) &&
        targetRound?.entryIds.some((id) => highlightedPaths.has(id));

      return {
        id: `${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
        type: 'smoothstep',
        animated: Boolean(isHighlighted),
        zIndex: isHighlighted ? 2 : 1,
        style: {
          stroke: isHighlighted ? laneColor : 'rgba(64, 63, 58, 0.32)',
          strokeWidth: isHighlighted ? 2.25 : 1.4,
          strokeDasharray: isHighlighted ? undefined : '5 5',
        },
      };
    });

    setNodes(newNodes);
    setEdges(newEdges);
  }, [roundGraph, highlightedPaths, lanes, currentLane, setNodes, setEdges]);

  const selectedRound = selectedNodeId
    ? roundGraph.roundById.get(selectedNodeId)
    : undefined;

  return (
    <div className="relative h-full w-full bg-surface-1">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => setSelectedNode(node.id)}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.1}
        maxZoom={2}
      >
        <Background color="#e1e0d9" gap={16} size={1} variant={BackgroundVariant.Dots} />
        <Controls />
        <MiniMap
          nodeColor={(node) => {
            const round = roundGraph.roundById.get(node.id);
            const laneIndex = getLaneIndex(round?.lane || currentLane, lanes.map((lane) => lane.lane));
            const isHighlighted = round?.entryIds.some((id) => highlightedPaths.has(id));
            return isHighlighted ? laneColors[laneIndex % laneColors.length] : '#898781';
          }}
          maskColor="rgba(252, 252, 251, 0.8)"
        />
      </ReactFlow>

      {selectedRound && (
        <TreeNodeDetailPanel
          round={selectedRound}
          onClose={() => setSelectedNode(null)}
        />
      )}
    </div>
  );
}

interface RoundGraph {
  rounds: ConversationRound[];
  roundById: Map<string, ConversationRound>;
  edges: Array<{ source: string; target: string }>;
}

function buildRoundGraph(entries: Entry[], laneNames: string[]): RoundGraph {
  const sortedEntries = [...entries].sort((a, b) => a.seq - b.seq);
  const entryById = new Map(sortedEntries.map((entry) => [entry.id, entry]));
  const roundById = new Map<string, ConversationRound>();
  const roundIdByEntryId = new Map<string, string>();

  for (const entry of sortedEntries) {
    if (entry.role !== 'user') continue;
    const round: ConversationRound = {
      id: entry.id,
      lane: entry.lane,
      seq: entry.seq,
      depth: 0,
      timestamp: entry.timestamp,
      user: entry,
      assistants: [],
      tools: [],
      entryIds: [entry.id],
    };
    roundById.set(round.id, round);
    roundIdByEntryId.set(entry.id, round.id);
  }

  for (const entry of sortedEntries) {
    if (entry.role === 'user') continue;
    const ownerRoundId = findOwnerUserId(entry, entryById);
    const round = ownerRoundId ? roundById.get(ownerRoundId) : undefined;
    if (!round) continue;

    if (entry.role === 'assistant') {
      round.assistants.push(entry);
    } else if (entry.role === 'tool') {
      round.tools.push(entry);
    }
    round.entryIds.push(entry.id);
    round.timestamp = Math.max(round.timestamp, entry.timestamp);
    roundIdByEntryId.set(entry.id, round.id);
  }

  const parentByRoundId = new Map<string, string>();
  for (const round of roundById.values()) {
    const parentRoundId = findParentRoundId(round.user, entryById, roundIdByEntryId);
    if (parentRoundId && parentRoundId !== round.id) {
      parentByRoundId.set(round.id, parentRoundId);
    }
  }

  const depthCache = new Map<string, number>();
  const resolveDepth = (roundId: string, seen = new Set<string>()): number => {
    if (depthCache.has(roundId)) return depthCache.get(roundId)!;
    if (seen.has(roundId)) return 0;
    seen.add(roundId);
    const parentRoundId = parentByRoundId.get(roundId);
    const depth = parentRoundId ? resolveDepth(parentRoundId, seen) + 1 : 0;
    depthCache.set(roundId, depth);
    return depth;
  };

  const rounds = [...roundById.values()]
    .map((round) => ({
      ...round,
      assistants: [...round.assistants].sort((a, b) => a.seq - b.seq),
      tools: [...round.tools].sort((a, b) => a.seq - b.seq),
      depth: resolveDepth(round.id),
    }))
    .sort((a, b) => a.depth - b.depth || getLaneIndex(a.lane, laneNames) - getLaneIndex(b.lane, laneNames) || a.seq - b.seq);

  return {
    rounds,
    roundById: new Map(rounds.map((round) => [round.id, round])),
    edges: [...parentByRoundId.entries()].map(([target, source]) => ({ source, target })),
  };
}

function findOwnerUserId(entry: Entry, entryById: Map<string, Entry>): string | null {
  let parentId = entry.parent;
  const seen = new Set<string>();
  while (parentId && !seen.has(parentId)) {
    seen.add(parentId);
    const parent = entryById.get(parentId);
    if (!parent) return null;
    if (parent.role === 'user') return parent.id;
    parentId = parent.parent;
  }
  return null;
}

function findParentRoundId(
  userEntry: Entry,
  entryById: Map<string, Entry>,
  roundIdByEntryId: Map<string, string>
): string | null {
  let parentId = userEntry.parent;
  const seen = new Set<string>();
  while (parentId && !seen.has(parentId)) {
    seen.add(parentId);
    const roundId = roundIdByEntryId.get(parentId);
    if (roundId) return roundId;
    parentId = entryById.get(parentId)?.parent || null;
  }
  return null;
}

function getLaneIndex(lane: string, laneNames: string[]): number {
  return Math.max(0, laneNames.indexOf(lane));
}
