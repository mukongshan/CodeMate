import { useState } from 'react';
import { useStore } from '../../store';
import { ChevronDown, Plus, GitCompare, LogOut } from 'lucide-react';
import AgentStatusBadge from './AgentStatusBadge';
import CreateLaneModal from '../modals/CreateLaneModal';

export default function Toolbar() {
  const {
    sessionId,
    workspace,
    currentLane,
    lanes,
    agentState,
    setSession,
    clearSession,
    setShowCompareDrawer,
  } = useStore();
  const [showLaneDropdown, setShowLaneDropdown] = useState(false);
  const [showCreateLane, setShowCreateLane] = useState(false);

  const laneColors = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'];

  const syncSession = async () => {
    if (!sessionId) return;
    const res = await fetch(`/api/sessions/${sessionId}`);
    const data = await res.json();
    if (res.ok) {
      setSession(sessionId, data);
    }
  };

  const switchLane = async (lane: string) => {
    try {
      if (!sessionId) return;
      const res = await fetch(`/api/sessions/${sessionId}/lanes/${lane}/switch`, {
        method: 'POST',
      });
      if (!res.ok) return;
      await syncSession();
      setShowLaneDropdown(false);
    } catch (error) {
      console.error('Failed to switch lane:', error);
    }
  };
  const activeLaneIndex = Math.max(0, lanes.findIndex(l => l.lane === currentLane));

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
            <div
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: laneColors[activeLaneIndex % 4] }}
            />
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
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: laneColors[index % 4] }}
                  />
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
        {workspace && (
          <div className="hidden xl:block max-w-[360px] truncate text-xs font-mono text-text-muted">
            {workspace}
          </div>
        )}

        <AgentStatusBadge state={agentState} />

        <button
          onClick={clearSession}
          className="p-1.5 hover:bg-surface-3 rounded-md transition-colors"
          title="退出工作区"
        >
          <LogOut className="w-5 h-5 text-text-muted" />
        </button>
      </div>

      {/* 创建分支对话框 */}
      {showCreateLane && <CreateLaneModal onClose={() => setShowCreateLane(false)} />}
    </div>
  );
}
