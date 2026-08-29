import { useState } from 'react';
import { useStore } from '../../store';
import { ChevronDown, Plus, GitCompare, Settings } from 'lucide-react';
import AgentStatusBadge from './AgentStatusBadge';
import CreateLaneModal from '../modals/CreateLaneModal';

export default function Toolbar() {
  const { currentLane, lanes, agentState, setShowCompareDrawer } = useStore();
  const [showLaneDropdown, setShowLaneDropdown] = useState(false);
  const [showCreateLane, setShowCreateLane] = useState(false);

  const switchLane = async (lane: string) => {
    try {
      await fetch(`http://localhost:8000/api/sessions/${useStore.getState().sessionId}/lanes/${lane}/switch`, {
        method: 'POST',
      });
      useStore.getState().setCurrentLane(lane);
      setShowLaneDropdown(false);
    } catch (error) {
      console.error('Failed to switch lane:', error);
    }
  };

  const laneColors = ['lane-blue', 'lane-orange', 'lane-aqua', 'lane-yellow'];

  return (
    <div className="h-[52px] border-b border-border bg-surface-2 flex items-center justify-between px-4">
      {/* 左侧 */}
      <div className="flex items-center gap-4">
        <div className="text-lg font-semibold">◈ CodeMate</div>

        {/* Lane 选择器 */}
        <div className="relative">
          <button
            onClick={() => setShowLaneDropdown(!showLaneDropdown)}
            className="flex items-center gap-2 px-3 py-1.5 bg-surface-1 border border-border rounded-md hover:bg-surface-3 transition-colors"
          >
            <div className={`w-2 h-2 rounded-full bg-${laneColors[lanes.findIndex(l => l.lane === currentLane) % 4]}`} />
            <span className="text-sm font-medium">{currentLane}</span>
            <ChevronDown className="w-4 h-4 text-text-muted" />
          </button>

          {showLaneDropdown && (
            <div className="absolute top-full mt-1 left-0 w-56 bg-surface-2 border border-border rounded-lg shadow-pop z-50">
              {lanes.map((lane, index) => (
                <button
                  key={lane.lane}
                  onClick={() => switchLane(lane.lane)}
                  className="w-full flex items-center gap-2 px-3 py-2 hover:bg-surface-3 transition-colors first:rounded-t-lg"
                >
                  <div className={`w-2 h-2 rounded-full bg-${laneColors[index % 4]}`} />
                  <span className="text-sm flex-1 text-left">{lane.lane}</span>
                  {lane.lane === currentLane && (
                    <span className="text-xs text-status-success">✓</span>
                  )}
                </button>
              ))}

              <div className="border-t border-border">
                <button
                  onClick={() => {
                    setShowLaneDropdown(false);
                    setShowCreateLane(true);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 hover:bg-surface-3 transition-colors text-accent rounded-b-lg"
                >
                  <Plus className="w-4 h-4" />
                  <span className="text-sm">新建分支</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* 创建分支 */}
        <button
          onClick={() => setShowCreateLane(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border rounded-md hover:bg-surface-3 transition-colors"
        >
          <Plus className="w-4 h-4" />
          分支
        </button>

        {/* 对比分支 */}
        <button
          onClick={() => setShowCompareDrawer(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border rounded-md hover:bg-surface-3 transition-colors"
        >
          <GitCompare className="w-4 h-4" />
          对比
        </button>
      </div>

      {/* 右侧 */}
      <div className="flex items-center gap-4">
        <AgentStatusBadge state={agentState} />

        <button className="p-1.5 hover:bg-surface-3 rounded-md transition-colors">
          <Settings className="w-5 h-5 text-text-muted" />
        </button>
      </div>

      {/* 创建分支对话框 */}
      {showCreateLane && <CreateLaneModal onClose={() => setShowCreateLane(false)} />}
    </div>
  );
}
