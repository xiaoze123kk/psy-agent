import { useState, type FormEvent } from "react";
import { api } from "../../api";
import type { PasswordResetQuestionResponse } from "../../types/api";
import loginBack from "../../imports/login_back.png";
import wcbg from "../../imports/wcbg.png";
import { Lock, User, Leaf } from "lucide-react";

const PASSWORD_MIN_LENGTH = 8;

interface PasswordResetPageProps {
  onBack: () => void;
  onComplete: () => void;
}

type Step = "username" | "question" | "new_password" | "success";

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

function extractErrorDetail(err: unknown, fallback: string): string {
  if (!(err instanceof Error)) return fallback;
  const match = err.message.match(/API \d+: (.+)/);
  if (!match) return fallback;
  try {
    const body = JSON.parse(match[1]);
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // not JSON
  }
  return fallback;
}

export function PasswordResetPage({ onBack, onComplete }: PasswordResetPageProps) {
  const [step, setStep] = useState<Step>("username");
  const [username, setUsername] = useState("");
  const [questionData, setQuestionData] = useState<PasswordResetQuestionResponse | null>(null);
  const [answer, setAnswer] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleQueryQuestion = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!username.trim()) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const response = await api.getPasswordResetQuestion({ username: username.trim() });
      setQuestionData(response);
      setStep("question");
    } catch (err) {
      setError(extractErrorDetail(err, "查询失败，请检查用户名。"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleVerifyAnswer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!answer.trim() || !questionData) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const response = await api.verifyPasswordResetAnswer({
        username: questionData.username,
        answer: answer.trim(),
      });
      setResetToken(response.reset_token);
      setStep("new_password");
    } catch (err) {
      setError(extractErrorDetail(err, "密保答案错误。"));
      setAnswer("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResetPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!resetToken || !newPassword) return;

    const pwError = validatePassword(newPassword);
    if (pwError) {
      setPasswordError(pwError);
      return;
    }

    if (newPassword !== confirmPassword) {
      setPasswordError("两次输入的密码不一致。");
      return;
    }

    setIsSubmitting(true);
    setError(null);
    setPasswordError(null);

    try {
      await api.resetPassword({ reset_token: resetToken, new_password: newPassword });
      setStep("success");
    } catch (err) {
      setError(extractErrorDetail(err, "重置失败，请重试。"));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="loading-auth" aria-labelledby="password-reset-title">
      <img className="loading-auth__background" src={wcbg} alt="" />
      <div className="loading-auth__shade" />

      <section className="loading-auth__frame">
        <img className="loading-auth__paper" src={loginBack} alt="" />
        <div className="loading-auth__content">
          <div className="loading-auth__intro">
            <h1 id="password-reset-title">
              找回密码
              <Leaf aria-hidden="true" />
            </h1>
            <p>
              {step === "username" && "请输入你的风语号"}
              {step === "question" && "请回答密保问题"}
              {step === "new_password" && "设置新密码"}
              {step === "success" && "密码重置成功"}
            </p>
            <button className="loading-auth__debug" type="button" onClick={onBack}>
              返回登录
            </button>
          </div>

          {step === "username" ? (
            <form className="loading-auth__form" onSubmit={handleQueryQuestion}>
              <div className="loading-auth__fields">
                <label className="loading-auth__field">
                  <User aria-hidden="true" />
                  <input
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    type="text"
                    placeholder="风语号"
                    autoComplete="username"
                  />
                </label>
              </div>
              {error ? <p className="loading-auth__error">{error}</p> : null}
              <button className="loading-auth__submit" type="submit" disabled={!username.trim() || isSubmitting}>
                {isSubmitting ? "查询中..." : "下一步"}
              </button>
            </form>
          ) : step === "question" ? (
            <form className="loading-auth__form" onSubmit={handleVerifyAnswer}>
              <div className="loading-auth__fields">
                <div className="loading-auth__note" style={{ marginBottom: 8 }}>
                  密保问题：{questionData?.security_question}
                </div>
                <label className="loading-auth__field">
                  <Lock aria-hidden="true" />
                  <input
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    type="text"
                    placeholder="输入答案"
                    autoComplete="off"
                  />
                </label>
              </div>
              {error ? <p className="loading-auth__error">{error}</p> : null}
              <button className="loading-auth__submit" type="submit" disabled={!answer.trim() || isSubmitting}>
                {isSubmitting ? "验证中..." : "验证"}
              </button>
            </form>
          ) : step === "new_password" ? (
            <form className="loading-auth__form" onSubmit={handleResetPassword}>
              <div className="loading-auth__fields">
                <label className="loading-auth__field">
                  <Lock aria-hidden="true" />
                  <input
                    value={newPassword}
                    onChange={(e) => {
                      setNewPassword(e.target.value);
                      setPasswordError(null);
                    }}
                    type="password"
                    placeholder="新密码"
                    autoComplete="new-password"
                  />
                </label>
                <label className="loading-auth__field">
                  <Lock aria-hidden="true" />
                  <input
                    value={confirmPassword}
                    onChange={(e) => {
                      setConfirmPassword(e.target.value);
                      setPasswordError(null);
                    }}
                    type="password"
                    placeholder="确认新密码"
                    autoComplete="new-password"
                  />
                </label>
                {!passwordError ? (
                  <p className="loading-auth__password-hint">需包含大写字母、小写字母和数字，至少 8 位</p>
                ) : (
                  <p className="loading-auth__password-error">{passwordError}</p>
                )}
              </div>
              {error ? <p className="loading-auth__error">{error}</p> : null}
              <button
                className="loading-auth__submit"
                type="submit"
                disabled={!newPassword || !confirmPassword || isSubmitting}
              >
                {isSubmitting ? "重置中..." : "重置密码"}
              </button>
            </form>
          ) : step === "success" ? (
            <div className="loading-auth__form" style={{ justifyContent: "center", textAlign: "center" }}>
              <p style={{ color: "#3a5a4a", fontSize: 16, marginBottom: 24 }}>你的新密码已生效。</p>
              <button className="loading-auth__submit" type="button" onClick={onComplete}>
                返回登录
              </button>
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
