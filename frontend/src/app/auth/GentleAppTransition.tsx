import { Cloud, CloudRain, Sun } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import logo from "../../imports/wind-chat-logo.png";
import "./GentleAppTransition.css";

interface GentleAppTransitionProps {
  children: ReactNode;
  onFinished?: () => void;
}

const moods = [
  { id: "sunny", icon: Sun, label: "晴朗" },
  { id: "calm", icon: Cloud, label: "平静" },
  { id: "rainy", icon: CloudRain, label: "低落" },
] as const;

export function GentleAppTransition({ children, onFinished }: GentleAppTransitionProps) {
  const [isFinished, setIsFinished] = useState(false);
  const [mood, setMood] = useState<string | null>(null);
  const [nickname, setNickname] = useState("");
  const [isLeaving, setIsLeaving] = useState(false);

  useEffect(() => {
    if (!isLeaving) return;

    const timer = window.setTimeout(() => {
      setIsFinished(true);
      onFinished?.();
    }, 1900);

    return () => window.clearTimeout(timer);
  }, [isLeaving, onFinished]);

  return (
    <div className={`gentle-transition ${isLeaving ? "is-leaving" : ""} ${isFinished ? "is-finished" : ""}`}>
      <div className="gentle-transition__stage">{children}</div>

      {!isFinished ? (
        <>
          <div className="gentle-transition__mist" />
          <div className="gentle-transition__center">
            <section className="gentle-transition__card" aria-labelledby="gentle-transition-title">
              <div className="gentle-transition__logo">
                <img src={logo} alt="宁语 Logo" />
              </div>

              <h2 id="gentle-transition-title">宁语 · 心灵驿站</h2>
              <p>一个安全的角落，倾听你的每一个声音</p>

              <div className="gentle-transition__moods" aria-label="今天的心情颜色">
                <span>今天的心情颜色是？</span>
                <div>
                  {moods.map((item) => {
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.id}
                        className={mood === item.id ? "is-selected" : ""}
                        type="button"
                        title={item.label}
                        aria-label={item.label}
                        onClick={() => setMood(item.id)}
                      >
                        <Icon aria-hidden="true" />
                      </button>
                    );
                  })}
                </div>
              </div>

              <input value={nickname} onChange={(event) => setNickname(event.target.value)} type="text" placeholder="怎么称呼你..." />

              <button className="gentle-transition__enter" type="button" onClick={() => setIsLeaving(true)}>
                轻轻推开门
              </button>
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}
