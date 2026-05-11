import { ProtectedAppGate } from "./app/ProtectedAppGate";
import { NingyuAppShell } from "./app/ningyu/NingyuAppShell";

export function App() {
  return (
    <ProtectedAppGate>
      <NingyuAppShell />
    </ProtectedAppGate>
  );
}
