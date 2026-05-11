import type { ReactNode } from "react";

import { Spinner, VisuallyHidden } from "../components/ui";
import { useSession } from "./session";

export function ProtectedAppGate({ children }: { children: ReactNode }) {
  const session = useSession();

  if (session.status === "checking") {
    return (
      <section className="app-shell__panel" aria-labelledby="session-loading-title">
        <p className="app-shell__eyebrow">Session</p>
        <h1 id="session-loading-title">正在恢复登录状态</h1>
        <Spinner label="正在恢复登录状态" size="sm" />
        <VisuallyHidden>正在检查本地 token 并恢复当前用户。</VisuallyHidden>
      </section>
    );
  }

  if (session.status !== "authenticated") {
    return (
      <section className="app-shell__panel" aria-labelledby="auth-required-title">
        <p className="app-shell__eyebrow">需要登录</p>
        <h1 id="auth-required-title">先登录，再进入陪伴空间</h1>
        <p>这里是登录/注册流程的临时入口。正式表单会在后续 auth 模块中接入。</p>
        {session.error ? <p>登录状态已失效，请重新登录。</p> : null}
      </section>
    );
  }

  return <>{children}</>;
}
