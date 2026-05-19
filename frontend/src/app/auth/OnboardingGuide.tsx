import { ArrowRight, Battery, Ear, Heart, Moon, ShieldAlert, Sparkles, User, Wind } from "lucide-react";
import { useState } from "react";

import logGuide from "../../imports/log_guide.png";
import wcbg from "../../imports/wcbg.png";
import type { MemoryMode } from "../../types/api";
import { getOnboardingSafetyNoteCopy } from "./onboardingSafetyNotice";
import "./DebugOnboardingGuide.css";

export type OnboardingTone = "gentle" | "direct" | "encourage" | "listen";

export interface OnboardingDraft {
  nickname: string;
  callMe: string;
  goals: string[];
  otherGoal: string;
  tone: OnboardingTone;
  activeness: number;
  memoryMode: MemoryMode;
  moodScore: number;
  anxietyScore: number;
  energyScore: number;
  sleepQuality: number;
  moodNote: string;
}

interface OnboardingGuideProps {
  onBack: () => void;
  onComplete: (draft: OnboardingDraft) => void;
  backLabel?: string;
  completeLabel?: string;
}

const goals = ["情绪陪伴", "学习压力", "人际关系", "睡眠/作息", "自我了解", "考前焦虑", "随便聊聊"];

const tones = [
  { id: "gentle", label: "温柔一点", icon: Wind },
  { id: "direct", label: "直接一点", icon: Sparkles },
  { id: "encourage", label: "多鼓励我", icon: Heart },
  { id: "listen", label: "先安静听", icon: Ear },
] satisfies Array<{ id: OnboardingTone; label: string; icon: typeof Wind }>;

const defaultDraft: OnboardingDraft = {
  nickname: "",
  callMe: "",
  goals: [],
  otherGoal: "",
  tone: "gentle",
  activeness: 3,
  memoryMode: "summary_only",
  moodScore: 3,
  anxietyScore: 3,
  energyScore: 3,
  sleepQuality: 3,
  moodNote: "",
};

export function OnboardingGuide({ onBack, onComplete, backLabel = "回到登录", completeLabel = "完成设置" }: OnboardingGuideProps) {
  const [step, setStep] = useState(1);
  const [draft, setDraft] = useState<OnboardingDraft>(defaultDraft);
  const safetyNoteCopy = getOnboardingSafetyNoteCopy();

  const toggleGoal = (goal: string) => {
    setDraft((current) => ({
      ...current,
      goals: current.goals.includes(goal) ? current.goals.filter((item) => item !== goal) : [...current.goals, goal],
    }));
  };

  const updateDraft = <Key extends keyof OnboardingDraft>(key: Key, value: OnboardingDraft[Key]) => {
    setDraft((current) => ({
      ...current,
      [key]: value,
    }));
  };

  const nextStep = () => setStep((current) => Math.min(6, current + 1));
  const prevStep = () => setStep((current) => Math.max(1, current - 1));

  return (
    <main className="debug-guide" aria-labelledby="onboarding-guide-title">
      <img className="debug-guide__background" src={wcbg} alt="" />
      <div className="debug-guide__shade" />

      <section className="debug-guide__frame">
        <img className="debug-guide__paper" src={logGuide} alt="" />
        <div className="debug-guide__content">
          <div className="debug-guide__progress" aria-label={`第 ${step} 步，共 6 步`}>
            {[1, 2, 3, 4, 5, 6].map((item) => (
              <span key={item} className={item === step ? "is-current" : item < step ? "is-done" : ""} />
            ))}
          </div>

          <div className="debug-guide__body">
            {step === 1 ? (
              <div className="debug-guide__split">
                <div>
                  <ShieldAlert className="debug-guide__hero-icon" aria-hidden="true" />
                  <h1 id="onboarding-guide-title">欢迎来到宁语</h1>
                  <p>在这段旅程开始前，我们需要达成几个共识。</p>
                </div>
                <div className="debug-guide__note-card">
                  <ul>
                    {safetyNoteCopy.bullets.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                  <p className="debug-guide__boundary-note">{safetyNoteCopy.boundaryNote}</p>
                </div>
              </div>
            ) : null}

            {step === 2 ? (
              <div className="debug-guide__split">
                <div>
                  <h1>怎么称呼你？</h1>
                  <p>一个让你觉得舒服的名字。</p>
                </div>
                <div className="debug-guide__fields">
                  <label>
                    <span>你的昵称</span>
                    <div>
                      <User aria-hidden="true" />
                      <input value={draft.nickname} onChange={(event) => updateDraft("nickname", event.target.value)} placeholder="例如：小风" />
                    </div>
                  </label>
                  <label>
                    <span>希望宁语平时怎么叫你？</span>
                    <div>
                      <Heart aria-hidden="true" />
                      <input value={draft.callMe} onChange={(event) => updateDraft("callMe", event.target.value)} placeholder="例如：叫我阿风就好" />
                    </div>
                  </label>
                </div>
              </div>
            ) : null}

            {step === 3 ? (
              <div className="debug-guide__split">
                <div>
                  <h1>陪伴目标</h1>
                  <p>你最近想被怎样陪伴？可以多选。</p>
                </div>
                <div className="debug-guide__chips">
                  {goals.map((goal) => (
                    <button key={goal} className={draft.goals.includes(goal) ? "is-active" : ""} type="button" onClick={() => toggleGoal(goal)}>
                      {goal}
                    </button>
                  ))}
                  <input value={draft.otherGoal} onChange={(event) => updateDraft("otherGoal", event.target.value)} placeholder="还有别的吗？写下你想说的话..." />
                </div>
              </div>
            ) : null}

            {step === 4 ? (
              <div className="debug-guide__split">
                <div>
                  <h1>宁语语气</h1>
                  <p>单选，之后也可以再改。</p>
                </div>
                <div className="debug-guide__tone-grid">
                  {tones.map((item) => {
                    const Icon = item.icon;
                    return (
                      <button key={item.id} className={draft.tone === item.id ? "is-active" : ""} type="button" onClick={() => updateDraft("tone", item.id)}>
                        <Icon aria-hidden="true" />
                        {item.label}
                      </button>
                    );
                  })}
                  <label>
                    <span>回应主动程度</span>
                    <input type="range" min="1" max="5" value={draft.activeness} onChange={(event) => updateDraft("activeness", Number(event.target.value))} />
                  </label>
                </div>
              </div>
            ) : null}

            {step === 5 ? (
              <div className="debug-guide__split">
                <div>
                  <h1>隐私设置</h1>
                  <p>决定宁语能记住什么，之后可在设置里修改。</p>
                </div>
                <div className="debug-guide__privacy">
                  <button className={draft.memoryMode === "off" ? "is-active" : ""} type="button" onClick={() => updateDraft("memoryMode", "off")}>
                    关闭记忆
                  </button>
                  <button className={draft.memoryMode === "summary_only" ? "is-active" : ""} type="button" onClick={() => updateDraft("memoryMode", "summary_only")}>
                    只存摘要
                  </button>
                  <button className={draft.memoryMode === "long_term" ? "is-active" : ""} type="button" onClick={() => updateDraft("memoryMode", "long_term")}>
                    长期记忆
                  </button>
                </div>
              </div>
            ) : null}

            {step === 6 ? (
              <div className="debug-guide__split debug-guide__split--checkin">
                <div>
                  <h1>心情签到</h1>
                  <p>进入主界面前，给宁语一点上下文吧。</p>
                </div>
                <div className="debug-guide__scores">
                  {[
                    { key: "moodScore", label: "整体心情", icon: Heart },
                    { key: "anxietyScore", label: "焦虑程度", icon: Wind },
                    { key: "energyScore", label: "精力状态", icon: Battery },
                    { key: "sleepQuality", label: "睡眠质量", icon: Moon },
                  ].map((item) => {
                    const Icon = item.icon;
                    return (
                      <div key={item.label}>
                        <span>
                          <Icon aria-hidden="true" />
                          {item.label}
                        </span>
                        {[1, 2, 3, 4, 5].map((score) => (
                          <button
                            key={score}
                            className={draft[item.key as "moodScore" | "anxietyScore" | "energyScore" | "sleepQuality"] === score ? "is-active" : ""}
                            type="button"
                            aria-pressed={draft[item.key as "moodScore" | "anxietyScore" | "energyScore" | "sleepQuality"] === score}
                            onClick={() => updateDraft(item.key as "moodScore" | "anxietyScore" | "energyScore" | "sleepQuality", score)}
                          >
                            {score}
                          </button>
                        ))}
                      </div>
                    );
                  })}
                  <textarea value={draft.moodNote} onChange={(event) => updateDraft("moodNote", event.target.value)} placeholder="今天辛苦啦..." rows={2} />
                </div>
              </div>
            ) : null}
          </div>

          <div className="debug-guide__actions">
            {step > 1 ? (
              <button type="button" onClick={prevStep}>
                返回
              </button>
            ) : (
              <button type="button" onClick={onBack}>
                {backLabel}
              </button>
            )}
            {step < 6 ? (
              <button className="is-primary" type="button" onClick={nextStep}>
                下一步 <ArrowRight aria-hidden="true" />
              </button>
            ) : (
              <button className="is-primary" type="button" onClick={() => onComplete(draft)}>
                {completeLabel} <Sparkles aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
