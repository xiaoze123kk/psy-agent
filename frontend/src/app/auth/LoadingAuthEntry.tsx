import { Frown, Leaf, Lock, Meh, RefreshCw, Smile, User } from "lucide-react";
import type { FormEvent } from "react";

import loginBack from "../../imports/login_back.png";
import wcbg from "../../imports/wcbg.png";
import type { AgeRange } from "../../types/api";
import "./LoadingAuthEntry.css";

type AuthMode = "login" | "register";

interface CaptchaView {
  imageDataUrl: string;
}

interface LoadingAuthEntryProps {
  authMode: AuthMode;
  username: string;
  password: string;
  ageRange: AgeRange;
  captchaCode: string;
  captcha: CaptchaView | null;
  isCaptchaLoading: boolean;
  isSubmitting: boolean;
  canSubmit: boolean;
  error: string | null;
  captchaError: string | null;
  ageModeNote: string;
  onAuthModeChange: (mode: AuthMode) => void;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onAgeRangeChange: (value: AgeRange) => void;
  onCaptchaCodeChange: (value: string) => void;
  onRefreshCaptcha: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onDebugEnterOnboarding?: () => void;
}

const moods = [
  { id: "sunny", icon: Smile, label: "晴朗" },
  { id: "calm", icon: Meh, label: "平静" },
  { id: "rainy", icon: Frown, label: "低落" },
] as const;

export function LoadingAuthEntry({
  authMode,
  username,
  password,
  ageRange,
  captchaCode,
  captcha,
  isCaptchaLoading,
  isSubmitting,
  canSubmit,
  error,
  captchaError,
  ageModeNote,
  onAuthModeChange,
  onUsernameChange,
  onPasswordChange,
  onAgeRangeChange,
  onCaptchaCodeChange,
  onRefreshCaptcha,
  onSubmit,
  onDebugEnterOnboarding,
}: LoadingAuthEntryProps) {
  const isLogin = authMode === "login";

  return (
    <main className="loading-auth" aria-labelledby="loading-auth-title">
      <img className="loading-auth__background" src={wcbg} alt="" />
      <div className="loading-auth__shade" />

      <section className="loading-auth__frame">
        <img className="loading-auth__paper" src={loginBack} alt="" />
        <div className="loading-auth__content">
          <div className="loading-auth__intro">
            <h1 id="loading-auth-title">
              {isLogin ? "心之日记" : "遇见新风"}
              <Leaf aria-hidden="true" />
            </h1>
            <p>{isLogin ? "翻开属于你的那一页" : "在这里种下你的第一颗种子"}</p>
            <span>宁语陪着你，你并不孤单 ♥</span>
          </div>

          <form className="loading-auth__form" onSubmit={onSubmit}>
            <div className="loading-auth__tabs" role="tablist" aria-label="认证方式">
              <button
                className={isLogin ? "is-active" : ""}
                type="button"
                role="tab"
                aria-selected={isLogin}
                onClick={() => onAuthModeChange("login")}
              >
                登录
              </button>
              <button
                className={!isLogin ? "is-active" : ""}
                type="button"
                role="tab"
                aria-selected={!isLogin}
                onClick={() => onAuthModeChange("register")}
              >
                注册
              </button>
            </div>

            <div className="loading-auth__fields">
              <label className="loading-auth__field">
                <User aria-hidden="true" />
                <input
                  value={username}
                  onChange={(event) => onUsernameChange(event.target.value)}
                  type="text"
                  placeholder={isLogin ? "风语号/昵称" : "设置风语号"}
                  autoComplete="username"
                />
              </label>

              <label className="loading-auth__field">
                <Lock aria-hidden="true" />
                <input
                  value={password}
                  onChange={(event) => onPasswordChange(event.target.value)}
                  type="password"
                  placeholder="日记本秘密"
                  autoComplete={isLogin ? "current-password" : "new-password"}
                />
              </label>

              {!isLogin ? (
                <>
                  <div className="loading-auth__age" aria-label="年龄范围">
                    <button className={ageRange === "13_15" ? "is-active" : ""} type="button" onClick={() => onAgeRangeChange("13_15")}>
                      13-15
                    </button>
                    <button className={ageRange === "16_17" ? "is-active" : ""} type="button" onClick={() => onAgeRangeChange("16_17")}>
                      16-17
                    </button>
                    <button className={ageRange === "18_plus" ? "is-active" : ""} type="button" onClick={() => onAgeRangeChange("18_plus")}>
                      18+
                    </button>
                  </div>
                  <p className="loading-auth__note">{ageModeNote}</p>
                </>
              ) : (
                <div className="loading-auth__remember">
                  <span aria-hidden="true" />
                  <p>记住我</p>
                  <button type="button">忘记密码?</button>
                </div>
              )}

              <div className="loading-auth__captcha" aria-busy={isCaptchaLoading}>
                <label className="loading-auth__field">
                  <input
                    value={captchaCode}
                    onChange={(event) => onCaptchaCodeChange(event.target.value)}
                    type="text"
                    placeholder="验证码"
                    autoComplete="off"
                    disabled={isSubmitting}
                  />
                </label>
                <button
                  className={isCaptchaLoading ? "is-loading" : ""}
                  type="button"
                  onClick={onRefreshCaptcha}
                  disabled={isCaptchaLoading || isSubmitting}
                  aria-label={isCaptchaLoading ? "验证码加载中" : "刷新验证码"}
                >
                  {captcha?.imageDataUrl && !isCaptchaLoading ? <img src={captcha.imageDataUrl} alt="验证码" /> : <RefreshCw aria-hidden="true" />}
                </button>
              </div>
              {captchaError ? <p className="loading-auth__captcha-error">{captchaError}</p> : null}
            </div>

            {error ? <p className="loading-auth__error">{error}</p> : null}

            <button className="loading-auth__submit" type="submit" disabled={!canSubmit}>
              {isSubmitting ? "处理中..." : isLogin ? "翻开日记" : "写下第一页"}
            </button>

            {onDebugEnterOnboarding ? (
              <button className="loading-auth__debug" type="button" onClick={onDebugEnterOnboarding}>
                调试进入引导页
              </button>
            ) : null}

            {!isLogin ? (
              <div className="loading-auth__moods" aria-label="此刻心情颜色">
                <p>此刻心情颜色？</p>
                <div>
                  {moods.map((mood) => {
                    const Icon = mood.icon;
                    return (
                      <button key={mood.id} type="button" aria-label={mood.label}>
                        <Icon aria-hidden="true" />
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </form>
        </div>
      </section>
    </main>
  );
}
