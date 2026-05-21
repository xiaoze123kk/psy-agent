﻿﻿﻿﻿﻿﻿import { useCallback, useEffect, useState, type ReactNode } from "react";

import { api } from "../api";
import { Spinner, VisuallyHidden } from "../components/ui";
import type { AgeRange } from "../types/api";
import { buildAgeModeProfile } from "./ageMode";
import { DebugOnboardingGuide } from "./auth/DebugOnboardingGuide";
import { markEntryTransitionSeenToday, shouldShowEntryTransitionToday } from "./auth/entryTransitionFrequency";
import { GentleAppTransition } from "./auth/GentleAppTransition";
import { LoadingAuthEntry } from "./auth/LoadingAuthEntry";
import { OnboardingGuide } from "./auth/OnboardingGuide";
import { PasswordResetPage } from "./auth/PasswordResetPage";
import "./ningyu/NingyuAppShell.css";
import { getRememberedAutoLogin, getRememberedUsername, useSession } from "./session";

type AuthMode = "login" | "register";

const PASSWORD_MIN_LENGTH = 8;

let _persistedAuthMode: AuthMode = "login";

function validatePassword(password: string): string | null {
  const errors: string[] = [];
  if (password.length < PASSWORD_MIN_LENGTH) {
    errors.push(`密码至少需要 ${PASSWORD_MIN_LENGTH} 个字符`);
  }
  if (!/[A-Z]/.test(password)) {
    errors.push("密码需要包含至少一个大写字母");
  }
  if (!/[a-z]/.test(password)) {
    errors.push("密码需要包含至少一个小写字母");
  }
  if (!/[0-9]/.test(password)) {
    errors.push("密码需要包含至少一个数字");
  }
  return errors.length > 0 ? errors.join("\n") : null;
}

interface CaptchaState {
  id: string;
  imageDataUrl: string;
}

export function ProtectedAppGate({ children }: { children: ReactNode }) {
  const session = useSession();
  const [hasEnteredAppLocally, setHasEnteredAppLocally] = useState(false);
  const [hasPlayedEntryTransition, setHasPlayedEntryTransition] = useState(() => !shouldShowEntryTransitionToday());

  const handleEntryTransitionFinished = useCallback(() => {
    markEntryTransitionSeenToday();
    setHasPlayedEntryTransition(true);
  }, []);

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
    return <AuthGate initialError={session.error} />;
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
    return <GentleAppTransition onFinished={handleEntryTransitionFinished}>{children}</GentleAppTransition>;
  }

  return <>{children}</>;
}

function AuthGate({ initialError }: { initialError: string | null }) {
  const session = useSession();
  const [isDebugOnboarding, setIsDebugOnboarding] = useState(false);
  const [isPasswordReset, setIsPasswordReset] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>(_persistedAuthMode);
  const [username, setUsername] = useState(() => getRememberedUsername() ?? "");
  const [password, setPassword] = useState("");
  const [ageRange, setAgeRange] = useState<AgeRange>("16_17");
  const [securityQuestion, setSecurityQuestion] = useState("");
  const [securityAnswer, setSecurityAnswer] = useState("");
  const [captchaCode, setCaptchaCode] = useState("");
  const [captcha, setCaptcha] = useState<CaptchaState | null>(null);
  const [isCaptchaLoading, setIsCaptchaLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(initialError);
  const [captchaError, setCaptchaError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [autoLogin, setAutoLogin] = useState(() => getRememberedAutoLogin());

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
      setCaptchaError("验证码加载失败，请稍后再试。");
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

  const canSubmit = Boolean(
    username.trim()
    && password
    && captcha?.id
    && captchaCode.trim()
    && !isSubmitting
    && !passwordError
    && (authMode === "login" ? true : securityQuestion.trim() && securityAnswer.trim()),
  );
  const ageModeProfile = buildAgeModeProfile(ageRange);

  const handleAuthModeChange = (nextMode: AuthMode) => {
    _persistedAuthMode = nextMode;
    setAuthMode(nextMode);
    setError(null);
    setPasswordError(null);
    setCaptchaCode("");
    void refreshCaptcha();
  };

  const handleAgeRangeChange = (nextAgeRange: AgeRange) => {
    setAgeRange(nextAgeRange);
    setError(null);
  };

  const handlePasswordChange = (value: string) => {
    setPassword(value);
    if (passwordError) {
      setPasswordError(null);
    }
  };

  if (isDebugOnboarding) {
    return <DebugOnboardingGuide onBack={() => setIsDebugOnboarding(false)} />;
  }

  if (isPasswordReset) {
    return (
      <PasswordResetPage
        onBack={() => setIsPasswordReset(false)}
        onComplete={() => {
          setIsPasswordReset(false);
          setAuthMode("login");
          _persistedAuthMode = "login";
          setError(null);
        }}
      />
    );
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!captcha || !canSubmit) return;

    if (authMode === "register") {
      const errorMsg = validatePassword(password);
      if (errorMsg) {
        setPasswordError(errorMsg);
        setCaptchaCode("");
        await refreshCaptcha();
        return;
      }
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const payload = {
        username: username.trim(),
        password,
        captcha_id: captcha.id,
        captcha_code: captchaCode.trim(),
        auto_login: autoLogin,
      };

      if (authMode === "register") {
        await session.register({
          ...payload,
          age_range: ageRange,
          security_question: securityQuestion.trim(),
          security_answer: securityAnswer.trim(),
        });
      } else {
        await session.login(payload);
      }
    } catch (submitError) {
      setCaptchaCode("");
      setError(authMode === "register" ? "注册失败，请检查输入。" : "登录失败，请检查输入。");
      await refreshCaptcha();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDebugEnterMain = async () => {
    if (isSubmitting) return;

    setIsSubmitting(true);
    setError(null);
    try {
      await session.startDebugSession();
    } catch (debugError) {
      setError("本地调试登录失败，请先用账号登录或注册。");
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
      securityQuestion={securityQuestion}
      securityAnswer={securityAnswer}
      captchaCode={captchaCode}
      captcha={captcha}
      isCaptchaLoading={isCaptchaLoading}
      isSubmitting={isSubmitting}
      canSubmit={canSubmit}
      error={error}
      captchaError={captchaError}
      passwordError={passwordError}
      autoLogin={autoLogin}
      ageModeNote={`${ageModeProfile.ageLabel} · ${ageModeProfile.modeLabel}：${ageModeProfile.description}`}
      onAuthModeChange={handleAuthModeChange}
      onUsernameChange={setUsername}
      onPasswordChange={handlePasswordChange}
      onAgeRangeChange={handleAgeRangeChange}
      onSecurityQuestionChange={setSecurityQuestion}
      onSecurityAnswerChange={setSecurityAnswer}
      onCaptchaCodeChange={setCaptchaCode}
      onRefreshCaptcha={() => void handleRefreshCaptcha()}
      onSubmit={handleSubmit}
      onDebugEnterMain={import.meta.env.DEV ? () => void handleDebugEnterMain() : undefined}
      onForgotPassword={() => setIsPasswordReset(true)}
      onAutoLoginChange={() => setAutoLogin((prev) => !prev)}
      onDebugEnterOnboarding={import.meta.env.DEV ? () => setIsDebugOnboarding(true) : undefined}
    />
  );
}
