import { useEffect, useState, type ReactNode } from "react";

import { api } from "../api";
import { Spinner, VisuallyHidden } from "../components/ui";
import type { AgeRange } from "../types/api";
import { buildAgeModeProfile } from "./ageMode";
import { DebugOnboardingGuide } from "./auth/DebugOnboardingGuide";
import { GentleAppTransition } from "./auth/GentleAppTransition";
import { LoadingAuthEntry } from "./auth/LoadingAuthEntry";
import { OnboardingGuide } from "./auth/OnboardingGuide";
import "./ningyu/NingyuAppShell.css";
import { useSession } from "./session";

type AuthMode = "login" | "register";

interface CaptchaState {
  id: string;
  imageDataUrl: string;
}

export function ProtectedAppGate({ children }: { children: ReactNode }) {
  const session = useSession();
  const [isDebugMainEntered, setIsDebugMainEntered] = useState(false);
  const [hasEnteredAppLocally, setHasEnteredAppLocally] = useState(false);
  const [hasPlayedEntryTransition, setHasPlayedEntryTransition] = useState(false);

  if (import.meta.env.DEV && isDebugMainEntered) {
    return <>{children}</>;
  }

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
    return <AuthGate initialError={session.error} onDebugEnterMain={() => setIsDebugMainEntered(true)} />;
  }

  if (session.currentUser?.onboarding_completed === false && !hasEnteredAppLocally) {
    return (
      <OnboardingGuide
        onBack={() => setHasEnteredAppLocally(true)}
        onComplete={() => setHasEnteredAppLocally(true)}
        backLabel="暂时跳过"
        completeLabel="进入宁语"
      />
    );
  }

  if (!hasPlayedEntryTransition) {
    return <GentleAppTransition onFinished={() => setHasPlayedEntryTransition(true)}>{children}</GentleAppTransition>;
  }

  return <>{children}</>;
}

function AuthGate({ initialError, onDebugEnterMain }: { initialError: string | null; onDebugEnterMain: () => void }) {
  const session = useSession();
  const [isDebugOnboarding, setIsDebugOnboarding] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [ageRange, setAgeRange] = useState<AgeRange>("16_17");
  const [captchaCode, setCaptchaCode] = useState("");
  const [captcha, setCaptcha] = useState<CaptchaState | null>(null);
  const [isCaptchaLoading, setIsCaptchaLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(initialError);
  const [captchaError, setCaptchaError] = useState<string | null>(null);

  const refreshCaptcha = async () => {
    setIsCaptchaLoading(true);
    setCaptchaError(null);

    try {
      const response = await api.getCaptcha();
      setCaptcha({
        id: response.captcha_id,
        imageDataUrl: response.image_data_url,
      });
    } catch (loadError) {
      setCaptchaError(getAuthErrorMessage(loadError, "验证码加载失败，请稍后再试。"));
    } finally {
      setIsCaptchaLoading(false);
    }
  };

  const handleRefreshCaptcha = async () => {
    if (isCaptchaLoading || isSubmitting) return;
    setCaptchaCode("");
    await refreshCaptcha();
  };

  useEffect(() => {
    void refreshCaptcha();
  }, []);

  useEffect(() => {
    setError(initialError);
  }, [initialError]);

  const canSubmit = Boolean(username.trim() && password && captcha?.id && captchaCode.trim() && !isSubmitting);
  const ageModeProfile = buildAgeModeProfile(ageRange);

  const handleAuthModeChange = (nextMode: AuthMode) => {
    setAuthMode(nextMode);
    setError(null);
    setCaptchaCode("");
  };

  const handleAgeRangeChange = (nextAgeRange: AgeRange) => {
    setAgeRange(nextAgeRange);
    setError(null);
  };

  if (isDebugOnboarding) {
    return <DebugOnboardingGuide onBack={() => setIsDebugOnboarding(false)} />;
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!captcha || !canSubmit) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const payload = {
        username: username.trim(),
        password,
        captcha_id: captcha.id,
        captcha_code: captchaCode.trim(),
      };

      if (authMode === "register") {
        await session.register({ ...payload, age_range: ageRange });
      } else {
        await session.login(payload);
      }
    } catch (submitError) {
      setCaptchaCode("");
      setError(getAuthErrorMessage(submitError, authMode === "register" ? "注册失败，请检查输入。" : "登录失败，请检查输入。"));
      await refreshCaptcha();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <LoadingAuthEntry
      authMode={authMode}
      username={username}
      password={password}
      ageRange={ageRange}
      captchaCode={captchaCode}
      captcha={captcha}
      isCaptchaLoading={isCaptchaLoading}
      isSubmitting={isSubmitting}
      canSubmit={canSubmit}
      error={error}
      captchaError={captchaError}
      ageModeNote={`${ageModeProfile.ageLabel} · ${ageModeProfile.modeLabel}：${ageModeProfile.description}`}
      onAuthModeChange={handleAuthModeChange}
      onUsernameChange={setUsername}
      onPasswordChange={setPassword}
      onAgeRangeChange={handleAgeRangeChange}
      onCaptchaCodeChange={setCaptchaCode}
      onRefreshCaptcha={() => void handleRefreshCaptcha()}
      onSubmit={handleSubmit}
      onDebugEnterMain={import.meta.env.DEV ? onDebugEnterMain : undefined}
      onDebugEnterOnboarding={import.meta.env.DEV ? () => setIsDebugOnboarding(true) : undefined}
    />
  );
}

function getAuthErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) {
    return error.message;
  }

  return fallback;
}
