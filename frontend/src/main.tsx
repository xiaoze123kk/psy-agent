import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { I18nProvider } from "@heroui/react/rac";

import { SessionProvider } from "./app/session";
import { AppStateProvider } from "./app/state";
import { App } from "./App";
import "./styles.css";

const rootElement = document.getElementById("app");

if (!rootElement) {
  throw new Error("React root element #app was not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <I18nProvider locale="zh-CN">
      <SessionProvider>
        <AppStateProvider>
          <App />
        </AppStateProvider>
      </SessionProvider>
    </I18nProvider>
  </StrictMode>,
);
