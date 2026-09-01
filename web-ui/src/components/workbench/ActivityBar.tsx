import { Files, GitBranch, Search, Sparkles, TerminalSquare } from 'lucide-react';
import { useStore } from '../../store';
import type { WorkbenchView } from '../../types';

const items: Array<{ view: WorkbenchView; label: string; icon: typeof Files }> = [
  { view: 'explorer', label: '资源管理器', icon: Files },
  { view: 'history', label: '分支历史', icon: GitBranch },
  { view: 'source-control', label: '源代码管理', icon: Sparkles },
  { view: 'search', label: '搜索', icon: Search },
];

export default function ActivityBar() {
  const { activeWorkbenchView, setWorkbenchView, terminalOpen, setTerminalOpen } = useStore();
  return (
    <nav className="flex w-12 flex-none flex-col items-center border-r border-border bg-surface-2 py-2" aria-label="工作台功能">
      <div className="flex flex-col items-center gap-1">
        {items.map(({ view, label, icon: Icon }) => {
          const active = activeWorkbenchView === view;
          return (
            <button key={view} type="button" onClick={() => setWorkbenchView(active ? null : view)} className={'relative flex h-10 w-10 items-center justify-center rounded-md transition-colors ' + (active ? 'bg-blue-50 text-accent' : 'text-text-muted hover:bg-surface-3 hover:text-text-primary')} title={label} aria-label={label} aria-pressed={active}>
              {active && <span className="absolute left-0 h-6 w-0.5 rounded-r bg-accent" />}
              <Icon className="h-[19px] w-[19px]" strokeWidth={active ? 2.2 : 1.8} />
            </button>
          );
        })}
      </div>
      <div className="mt-auto flex flex-col items-center gap-1 border-t border-border pt-2">
        <button type="button" onClick={() => setTerminalOpen(!terminalOpen)} className={'relative flex h-10 w-10 items-center justify-center rounded-md transition-colors ' + (terminalOpen ? 'bg-blue-50 text-accent' : 'text-text-muted hover:bg-surface-3 hover:text-text-primary')} title={terminalOpen ? '关闭终端' : '打开终端'} aria-label={terminalOpen ? '关闭终端' : '打开终端'} aria-pressed={terminalOpen}>
          {terminalOpen && <span className="absolute left-0 h-6 w-0.5 rounded-r bg-accent" />}
          <TerminalSquare className="h-[19px] w-[19px]" strokeWidth={1.8} />
        </button>
      </div>
    </nav>
  );
}
