import { useState } from 'react';
import { useStore } from '../store';
import Toolbar from './toolbar/Toolbar';
import TreeCanvas from './tree/TreeCanvas';
import ConversationPanel from './conversation/ConversationPanel';
import PermissionModal from './modals/PermissionModal';
import CompareDrawer from './modals/CompareDrawer';
import WorkspaceFileViewer from './modals/WorkspaceFileViewer';

interface WorkspaceProps {
  sendMessage: (content: string, lane?: string) => void;
  sendPermissionResponse: (requestId: string, action: string) => void;
  interruptRun: () => boolean;
  compactSession: (lane?: string) => Promise<boolean>;
}

export default function Workspace({
  sendMessage,
  sendPermissionResponse,
  interruptRun,
  compactSession,
}: WorkspaceProps) {
  const { permissionRequest, showCompareDrawer, showWorkspaceFiles } = useStore();
  const [splitRatio, setSplitRatio] = useState(40); // 左侧占比

  return (
    <div className="h-screen flex flex-col bg-surface-1">
      {/* 顶部工具栏 */}
      <Toolbar />

      {/* 主工作区 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧：树形画布 */}
        <div
          className="border-r border-border min-w-0"
          style={{ width: `${splitRatio}%`, minWidth: '320px' }}
        >
          <TreeCanvas />
        </div>

        {/* 中间：可拖拽分隔条 */}
        <div
          className="w-1 bg-border hover:bg-accent cursor-col-resize"
          onMouseDown={(e) => {
            e.preventDefault();
            const startX = e.clientX;
            const startRatio = splitRatio;

            const handleMouseMove = (e: MouseEvent) => {
              const deltaX = e.clientX - startX;
              const containerWidth = window.innerWidth;
              const deltaRatio = (deltaX / containerWidth) * 100;
              const newRatio = Math.max(30, Math.min(55, startRatio + deltaRatio));
              setSplitRatio(newRatio);
            };

            const handleMouseUp = () => {
              document.removeEventListener('mousemove', handleMouseMove);
              document.removeEventListener('mouseup', handleMouseUp);
            };

            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
          }}
          onDoubleClick={() => setSplitRatio(40)}
        />

        {/* 右侧：对话面板 */}
        <div className="flex-1 min-w-0">
          <ConversationPanel
            sendMessage={sendMessage}
            interruptRun={interruptRun}
            compactSession={compactSession}
          />
        </div>
      </div>

      {/* 权限确认浮层 */}
      {permissionRequest && (
        <PermissionModal sendPermissionResponse={sendPermissionResponse} />
      )}

      {/* 分支对比抽屉 */}
      {showCompareDrawer && <CompareDrawer />}
      {showWorkspaceFiles && <WorkspaceFileViewer />}
    </div>
  );
}
