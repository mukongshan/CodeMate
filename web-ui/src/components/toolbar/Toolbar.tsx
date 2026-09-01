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
  Settings,
  Wifi,
  WifiOff,
  MessageSquare,
} from 'lucide-react';
import AgentStatusBadge from './AgentStatusBadge';
import CreateLaneModal from '../modals/CreateLaneModal';
import PermissionGateModal from '../modals/PermissionGateModal';
import LaneCodeManagerModal from '../modals/LaneCodeManagerModal';
import SessionManagerModal from '../modals/SessionManagerModal';

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
  const [showSettings, setShowSettings] = useState(false);
  const [showCreateLane, setShowCreateLane] = useState(false);
  const [showPermissionGate, setShowPermissionGate] = useState(false);
  const [showCodeManager, setShowCodeManager] = useState(false);
  const [showSessionManager, setShowSessionManager] = useState(false);

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
    <Wifi className="h-3.5 w-3.5" />
  ) : wsReconnecting ? (
    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
  ) : (
    <WifiOff className="h-3.5 w-3.5" />
  );

  return (
    <div className="flex h-[52px] items-center justify-between gap-3 border-b border-border bg-surface-2 px-4">
      {/* 左侧 */}
      <div className="flex min-w-0 items-center gap-2">
        <div className="flex-none pr-1 text-base font-semibold tracking-tight">◈ CodeMate</div>

        <div className="mx-1 hidden h-5 w-px flex-none bg-border sm:block" />

        {/* Lane 选择器 */}
        <div className="relative flex-none">
          <button
            onClick={() => setShowLaneDropdown(!showLaneDropdown)}
            className="flex items-center gap-2 rounded-lg border border-border bg-surface-1 px-2.5 py-1.5 transition-colors hover:bg-surface-3"
          >
            <div
              className="h-2 w-2 rounded-full"
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
            <ChevronDown className="h-3.5 w-3.5 text-text-muted" />
          </button>

          {showLaneDropdown && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowLaneDropdown(false)} />
              <div className="absolute left-0 top-full z-50 mt-1.5 w-60 overflow-hidden rounded-xl border border-border bg-surface-2 py-1 shadow-pop">
                <div className="px-3 pb-1 pt-1 text-[11px] font-medium uppercase tracking-wide text-text-muted">
                  分支
                </div>
                {lanes.map((lane, index) => (
                  <button
                    key={lane.lane}
                    onClick={() => switchLane(lane.lane)}
                    className="flex w-full items-center gap-2 px-3 py-2 transition-colors hover:bg-surface-3"
                  >
                    <div
                      className="h-2 w-2 flex-none rounded-full"
                      style={{ backgroundColor: laneColors[index % 4] }}
                    />
                    <span className="flex-1 truncate text-left text-sm">{lane.lane}</span>
                    {lane.lane === currentLane && (
                      <span className="text-xs text-status-success">✓</span>
                    )}
                  </button>
                ))}

                <div className="mt-1 border-t border-border pt-1">
                  <button
                    onClick={() => {
                      setShowLaneDropdown(false);
                      setShowCreateLane(true);
                    }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-accent transition-colors hover:bg-surface-3"
                  >
                    <Plus className="h-4 w-4" />
                    <span className="text-sm">新建分支</span>
                  </button>
                </div>
              </div>
            </>
          )}
        </div>

        {/* 常用操作 */}
        <button
          onClick={() => setShowWorkspaceFiles(true)}
          className="flex flex-none items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-text-secondary transition-colors hover:bg-surface-3 hover:text-text-primary"
          title="浏览当前 Lane 工作区文件"
        >
          <FolderOpen className="h-4 w-4" />
          <span className="hidden lg:inline">文件</span>
        </button>

        <button
          onClick={() => setShowCompareDrawer(true)}
          className="flex flex-none items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-text-secondary transition-colors hover:bg-surface-3 hover:text-text-primary"
          title="对比分支代码差异"
        >
          <GitCompare className="h-4 w-4" />
          <span className="hidden lg:inline">对比</span>
        </button>

        {workspace && (
          <div
            className="ml-1 hidden min-w-0 truncate font-mono text-xs text-text-muted xl:block"
            title={workspace}
          >
            {workspace}
          </div>
        )}
      </div>

      {/* 右侧 */}
      <div className="flex flex-none items-center gap-2">
        <div
          className={`hidden items-center gap-1.5 rounded-lg border border-border bg-surface-1 px-2 py-1.5 text-xs md:flex ${
            wsConnected ? 'text-status-success' : 'text-status-warning'
          }`}
          title="后端连接状态"
        >
          {connectionIcon}
          <span>{connectionLabel}</span>
        </div>

        <AgentStatusBadge state={agentState} />

        {/* 设置菜单 */}
        <div className="relative">
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-surface-3 hover:text-text-primary"
            title="设置"
            aria-label="设置"
            aria-expanded={showSettings}
          >
            <Settings className="h-4 w-4" />
          </button>

          {showSettings && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowSettings(false)} />
              <div className="absolute right-0 top-full z-50 mt-1.5 w-56 overflow-hidden rounded-xl border border-border bg-surface-2 py-1 shadow-pop">
                <div className="px-3 pb-1 pt-1 text-[11px] font-medium uppercase tracking-wide text-text-muted">
                  工作区设置
                </div>
                <button
                  onClick={() => {
                    setShowSettings(false);
                    setShowCodeManager(true);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm transition-colors hover:bg-surface-3"
                >
                  <Code2 className="h-4 w-4 text-text-muted" />
                  代码管理
                </button>
                <button
                  onClick={() => {
                    setShowSettings(false);
                    setShowPermissionGate(true);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm transition-colors hover:bg-surface-3"
                >
                  <ShieldCheck className="h-4 w-4 text-text-muted" />
                  命令门禁
                </button>
                <button
                  onClick={() => {
                    setShowSettings(false);
                    setShowCreateLane(true);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm transition-colors hover:bg-surface-3"
                >
                  <Plus className="h-4 w-4 text-text-muted" />
                  新建分支
                </button>
                <button
                  onClick={() => {
                    setShowSettings(false);
                    setShowSessionManager(true);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm transition-colors hover:bg-surface-3"
                >
                  <MessageSquare className="h-4 w-4 text-text-muted" />
                  会话管理
                </button>

                {workspace && (
                  <div className="border-t border-border px-3 py-2">
                    <div className="text-[11px] text-text-muted">当前工作区</div>
                    <div className="truncate font-mono text-xs text-text-secondary" title={workspace}>
                      {workspace}
                    </div>
                  </div>
                )}

                <div className="border-t border-border pt-1">
                  <button
                    onClick={() => {
                      setShowSettings(false);
                      clearSession();
                    }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-sm text-status-error transition-colors hover:bg-red-50"
                  >
                    <LogOut className="h-4 w-4" />
                    退出工作区
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* 创建分支对话框 */}
      {showCreateLane && <CreateLaneModal onClose={() => setShowCreateLane(false)} />}
      {showPermissionGate && (
        <PermissionGateModal onClose={() => setShowPermissionGate(false)} />
      )}
      {showCodeManager && (
        <LaneCodeManagerModal onClose={() => setShowCodeManager(false)} />
      )}
      {showSessionManager && (
        <SessionManagerModal onClose={() => setShowSessionManager(false)} />
      )}
    </div>
  );
}
