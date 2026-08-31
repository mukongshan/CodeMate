import { useState } from 'react';
import { useStore } from '../../store';
import {
  ChevronDown,
  Plus,
  GitCompare,
  LogOut,
  RefreshCw,
  ShieldCheck,
  Code2,
  FolderOpen,
  Wifi,
  WifiOff,
} from 'lucide-react';
import AgentStatusBadge from './AgentStatusBadge';
import CreateLaneModal from '../modals/CreateLaneModal';
import PermissionGateModal from '../modals/PermissionGateModal';
import LaneCodeManagerModal from '../modals/LaneCodeManagerModal';

export default function Toolbar() {
  const {
    sessionId,
    workspace,
    currentLane,
    lanes,
    agentState,
    wsConnected,
    wsReconnecting,
    setSession,
    clearSession,
    setShowCompareDrawer,
    setShowWorkspaceFiles,
  } = useStore();
  const [showLaneDropdown, setShowLaneDropdown] = useState(false);
  const [showCreateLane, setShowCreateLane] = useState(false);
  const [showPermissionGate, setShowPermissionGate] = useState(false);
  const [showCodeManager, setShowCodeManager] = useState(false);

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
  const activeLane = lanes[activeLaneIndex];
  const connectionLabel = wsConnected
    ? '已连接'
    : wsReconnecting
      ? '重连中'
      : '未连接';
  const connectionIcon = wsConnected ? (
    <Wifi className="h-4 w-4" />
  ) : wsReconnecting ? (
    <RefreshCw className="h-4 w-4 animate-spin" />
  ) : (
    <WifiOff className="h-4 w-4" />
  );

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
            {activeLane?.git?.enabled && (
              <span
                className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                  activeLane.git.sync_state === 'clean'
                    ? 'bg-green-50 text-status-success'
                    : 'bg-amber-50 text-status-warning'
                }`}
                title={activeLane.git.managed_branch}
              >
                {activeLane.git.short_head || activeLane.git.sync_state}
              </span>
            )}
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

        <button
          onClick={() => setShowPermissionGate(true)}
          className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm transition-colors hover:bg-surface-3"
          title="维护命令工具门禁"
        >
          <ShieldCheck className="h-4 w-4" />
          门禁
        </button>

        <button
          onClick={() => setShowCodeManager(true)}
          className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm transition-colors hover:bg-surface-3"
          title="管理代码检查点、发布和 Lane 生命周期"
        >
          <Code2 className="h-4 w-4" />
          代码管理
        </button>

        <button
          onClick={() => setShowWorkspaceFiles(true)}
          className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm transition-colors hover:bg-surface-3"
          title="浏览当前 Lane 工作区文件"
        >
          <FolderOpen className="h-4 w-4" />
          文件
        </button>
      </div>

      {/* 右侧 */}
      <div className="flex items-center gap-4">
        {workspace && (
          <div className="hidden xl:block max-w-[360px] truncate text-xs font-mono text-text-muted">
            {workspace}
          </div>
        )}

        <div
          className={`hidden items-center gap-1.5 rounded-md border border-border bg-surface-1 px-2.5 py-1.5 text-xs md:flex ${
            wsConnected ? 'text-status-success' : 'text-status-warning'
          }`}
          title="后端连接状态"
        >
          {connectionIcon}
          <span>{connectionLabel}</span>
        </div>

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
      {showPermissionGate && (
        <PermissionGateModal onClose={() => setShowPermissionGate(false)} />
      )}
      {showCodeManager && (
        <LaneCodeManagerModal onClose={() => setShowCodeManager(false)} />
      )}
    </div>
  );
}
