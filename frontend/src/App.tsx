import { useEffect, useState } from 'react';
import { useStore } from './store';
import { useWebSocket } from './hooks/useWebSocket';
import Workspace from './components/Workspace';
import SessionPicker from './components/SessionPicker';
import ToastContainer from './components/ToastContainer';

function App() {
  const { sessionId } = useStore();
  const [loading, setLoading] = useState(false);

  const { sendMessage, sendPermissionResponse } = useWebSocket(sessionId);

  // 如果没有 sessionId，显示会话选择页
  if (!sessionId) {
    return (
      <>
        <SessionPicker />
        <ToastContainer />
      </>
    );
  }

  // 显示工作台
  return (
    <>
      <Workspace
        sendMessage={sendMessage}
        sendPermissionResponse={sendPermissionResponse}
      />
      <ToastContainer />
    </>
  );
}

export default App;
