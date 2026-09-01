import { useStore } from '../store';
import Toolbar from './toolbar/Toolbar';
import PermissionModal from './modals/PermissionModal';
import CompareDrawer from './modals/CompareDrawer';
import WorkspaceFileViewer from './modals/WorkspaceFileViewer';
import ActivityBar from './workbench/ActivityBar';
import { EditorArea, SidePanel, TerminalPanel } from './workbench/WorkbenchPanels';
import ConversationPanel from './conversation/ConversationPanel';
import type { MouseEvent as ReactMouseEvent } from 'react';

interface WorkspaceProps {
  sendMessage: (content: string, lane?: string) => void;
  sendPermissionResponse: (requestId: string, action: string) => void;
  interruptRun: () => boolean;
  compactSession: (lane?: string) => Promise<boolean>;
  openTerminal: () => boolean;
  sendTerminalInput: (text: string) => boolean;
  signalTerminal: (signal?: string) => boolean;
  closeTerminal: () => void;
}

export default function Workspace({ sendMessage, sendPermissionResponse, interruptRun, compactSession, openTerminal, sendTerminalInput, signalTerminal, closeTerminal }: WorkspaceProps) {
  const {
    permissionRequest,
    showCompareDrawer,
    showWorkspaceFiles,
    activeWorkbenchView,
    sidePanelWidth,
    conversationWidth,
    terminalOpen,
    setWorkbenchView,
    setSidePanelWidth,
    setConversationWidth,
  } = useStore();

  const startResize = (event: ReactMouseEvent, kind: 'side' | 'conversation') => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = kind === 'side' ? sidePanelWidth : conversationWidth;
    const move = (moveEvent: MouseEvent) => {
      const delta = moveEvent.clientX - startX;
      if (kind === 'side') setSidePanelWidth(startWidth + delta);
      else setConversationWidth(startWidth - delta);
    };
    const stop = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', stop);
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', stop);
  };

  return (
    <div className="flex h-screen min-h-0 flex-col overflow-hidden bg-surface-1">
      <Toolbar />
      <div className="flex min-h-0 flex-1">
        <ActivityBar />
        {activeWorkbenchView && (
          <>
            <div className="min-w-0 flex-none border-r border-border" style={{ width: sidePanelWidth }}>
              <SidePanel view={activeWorkbenchView} onClose={() => setWorkbenchView(null)} />
            </div>
            <div
              className="w-1 flex-none cursor-col-resize bg-border/60 transition-colors hover:bg-accent"
              onMouseDown={(event) => startResize(event, 'side')}
              onDoubleClick={() => setSidePanelWidth(280)}
              title="拖动调整侧边栏宽度"
            />
          </>
        )}

        <main className="flex min-w-0 flex-1 flex-col">
          <EditorArea />
          {terminalOpen && <TerminalPanel openTerminal={openTerminal} sendTerminalInput={sendTerminalInput} signalTerminal={signalTerminal} closeTerminal={closeTerminal} />}
        </main>

        <div
          className="w-1 flex-none cursor-col-resize bg-border/60 transition-colors hover:bg-accent"
          onMouseDown={(event) => startResize(event, 'conversation')}
          onDoubleClick={() => setConversationWidth(380)}
          title="拖动调整对话区宽度"
        />
        <aside className="min-w-0 flex-none" style={{ width: conversationWidth }} aria-label="对话区">
          <div className="h-full min-w-0 border-l border-border">
            <ConversationPanel
              sendMessage={sendMessage}
              interruptRun={interruptRun}
              compactSession={compactSession}
            />
          </div>
        </aside>
      </div>

      {permissionRequest && <PermissionModal sendPermissionResponse={sendPermissionResponse} />}
      {showCompareDrawer && <CompareDrawer />}
      {showWorkspaceFiles && <WorkspaceFileViewer />}
    </div>
  );
}
