import { useStore } from './store';
import { useWebSocket } from './hooks/useWebSocket';
import Workspace from './components/Workspace';
import SessionPicker from './components/SessionPicker';
import ToastContainer from './components/ToastContainer';

function App() {
  const { sessionId } = useStore();
  const { sendMessage, sendPermissionResponse, interruptRun, compactSession } = useWebSocket(sessionId);

  if (!sessionId) {
    return (
      <>
        <SessionPicker />
        <ToastContainer />
      </>
    );
  }

  return (
    <>
      <Workspace
        sendMessage={sendMessage}
        sendPermissionResponse={sendPermissionResponse}
        interruptRun={interruptRun}
        compactSession={compactSession}
      />
      <ToastContainer />
    </>
  );
}

export default App;
