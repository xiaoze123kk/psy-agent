import { useEffect, useMemo, useState } from "react";

import bgDay from "../../imports/wcbg.png";
import bgNight from "../../imports/wcbg_night.png";
import logo from "../../imports/wind-chat-logo.png";
import { useAppState } from "../state";
import "./NingyuAppShell.css";
import type { MemoryMode, UserMode } from "../../types/api";

type IconName =
  | "moon"
  | "sun"
  | "shield"
  | "plus"
  | "clock"
  | "spark"
  | "settings"
  | "heart"
  | "phone"
  | "message"
  | "light"
  | "wind"
  | "leaf"
  | "send";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

type ShellPhase = "loading" | "ready" | "error";
type SafetyTone = "loading" | "stable" | "watch" | "support" | "error";

const conversations = [
  { id: "1", title: "今天的压力", time: "10分钟前", preview: "我感觉有点喘不过气..." },
  { id: "2", title: "关于学习", time: "昨天", preview: "考试让我很焦虑" },
  { id: "3", title: "和朋友的事", time: "3天前", preview: "我不知道该怎么开口..." },
];
const suggestions = ["试试深呼吸练习", "写下今天的感受", "听一段舒缓音乐"];
const userModeLabels: Record<UserMode, string> = {
  teen: "青少年模式",
  adult: "标准模式",
};
const memoryModeLabels: Record<MemoryMode, string> = {
  off: "记忆关闭",
  summary_only: "摘要记忆",
  long_term: "长时记忆",
};
const voiceStyleLabels: Record<string, string> = {
  gentle: "温柔陪伴",
};

function formatVoiceStyleLabel(style: string): string {
  return voiceStyleLabels[style] ?? (style || "默认陪伴");
}

export function NingyuAppShell() {
  const {
    currentUser,
    userMode,
    memoryMode,
    voiceSettings,
    privacySettings,
    isNight,
    toggleThemeMode,
  } = useAppState();
  const [messages, setMessages] = useState<Message[]>([]);
  const [shellPhase, setShellPhase] = useState<ShellPhase>("loading");
  const [isSafetyEntryOpen, setIsSafetyEntryOpen] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setShellPhase("ready");
    }, 720);

    return () => window.clearTimeout(timer);
  }, []);

  const safetyState = useMemo(() => {
    if (shellPhase === "loading") {
      return {
        tone: "loading" as SafetyTone,
        label: "安全空间载入中",
        detail: "正在检查陪伴空间与安全入口。",
      };
    }

    if (shellPhase === "error") {
      return {
        tone: "error" as SafetyTone,
        label: "安全状态暂不可用",
        detail: "先停一下，我们重新恢复安全入口。",
      };
    }

    if (isSafetyEntryOpen) {
      return {
        tone: "support" as SafetyTone,
        label: "安全支持已展开",
        detail: "你现在可以直接查看支持资源和提醒。",
      };
    }

    if (messages.length >= 3) {
      return {
        tone: "watch" as SafetyTone,
        label: "安全状态留意中",
        detail: "如果你想暂停一下，也可以随时打开安全入口。",
      };
    }

    return {
      tone: "stable" as SafetyTone,
      label: "安全陪伴在线",
      detail: "这里保持可见，随时可以打开支持入口。",
    };
  }, [isSafetyEntryOpen, messages.length, shellPhase]);

  const displayName = currentUser?.nickname || currentUser?.username || "正在倾听你";
  const statusTags = useMemo(
    () => [
      userModeLabels[userMode],
      memoryModeLabels[memoryMode],
      voiceSettings.voiceEnabled ? "语音已开启" : "语音已关闭",
      voiceSettings.saveVoiceAudio ? "保存语音音频" : "不保存语音音频",
      privacySettings.saveTranscript ? "保存转写" : "不保存转写",
      formatVoiceStyleLabel(voiceSettings.companionStyle),
    ],
    [
      memoryMode,
      privacySettings.saveTranscript,
      userMode,
      voiceSettings.companionStyle,
      voiceSettings.saveVoiceAudio,
      voiceSettings.voiceEnabled,
    ],
  );

  const handleToggleSafetyEntry = () => {
    setIsSafetyEntryOpen((current) => !current);
  };

  const handleRetrySafetyState = () => {
    setShellPhase("loading");
    window.setTimeout(() => {
      setShellPhase("ready");
    }, 720);
  };

  const handleSend = (content: string) => {
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "user",
        content,
        timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
      },
    ]);
  };

  return (
    <GentleLoginTransition isNight={isNight}>
      <div className={`ningyu-shell ${isNight ? "is-night" : "is-day"}`}>
        <Background isNight={isNight} />
        <Header
          isNight={isNight}
          displayName={displayName}
          userModeLabel={userModeLabels[userMode]}
          safetyState={safetyState}
          onToggleNight={toggleThemeMode}
          onToggleSafetyEntry={handleToggleSafetyEntry}
          isSafetyEntryOpen={isSafetyEntryOpen}
        />
        <div className="ningyu-shell__body">
          <LeftSidebar isNight={isNight} userModeLabel={userModeLabels[userMode]} memoryModeLabel={memoryModeLabels[memoryMode]} />
          <ChatWorkspace isNight={isNight} messages={messages} onSend={handleSend} />
          <RightPanel
            isNight={isNight}
            currentUserLabel={displayName}
            statusTags={statusTags}
            safetyState={safetyState}
            isSafetyEntryOpen={isSafetyEntryOpen}
            onToggleSafetyEntry={handleToggleSafetyEntry}
            onRetrySafetyState={handleRetrySafetyState}
          />
        </div>
      </div>
    </GentleLoginTransition>
  );
}

function Background({ isNight }: { isNight: boolean }) {
  return (
    <div className="ningyu-bg" aria-hidden="true">
      <img className={`ningyu-bg__image ${isNight ? "is-hidden" : ""}`} src={bgDay} alt="" />
      <img className={`ningyu-bg__image ${isNight ? "" : "is-hidden"}`} src={bgNight} alt="" />
      <div className="ningyu-bg__wash" />
    </div>
  );
}

function GentleLoginTransition({ children, isNight }: { children: React.ReactNode; isNight: boolean }) {
  const [isFinished, setIsFinished] = useState(false);

  return (
    <div className={`ningyu-transition ${isNight ? "is-night" : "is-day"}`}>
      {children}
      {!isFinished ? (
        <div className="ningyu-login" aria-labelledby="ningyu-login-title">
          <div className="ningyu-login__mist" />
          <section className="ningyu-login__box">
            <div className="ningyu-login__logo">
              <img src={logo} alt="宁语 Logo" />
            </div>
            <h2 id="ningyu-login-title">深呼吸，感受微风</h2>
            <input type="text" placeholder="你的名字..." aria-label="你的名字" />
            <button type="button" onClick={() => setIsFinished(true)}>
              开启陪伴
            </button>
          </section>
        </div>
      ) : null}
    </div>
  );
}

function Header({
  isNight,
  displayName,
  userModeLabel,
  safetyState,
  onToggleNight,
  onToggleSafetyEntry,
  isSafetyEntryOpen,
}: {
  isNight: boolean;
  displayName: string;
  userModeLabel: string;
  safetyState: { tone: SafetyTone; label: string; detail: string };
  onToggleNight: () => void;
  onToggleSafetyEntry: () => void;
  isSafetyEntryOpen: boolean;
}) {
  return (
    <header className="ningyu-header">
      <div className="ningyu-brand">
        <img src={logo} alt="宁语 Logo" />
        <div>
          <h1>宁语 · 心灵陪伴</h1>
          <p>
            <span className="ningyu-brand__dot" />
            微风正在倾听 · {displayName} · {userModeLabel}
          </p>
        </div>
      </div>
      <div className="ningyu-header__actions">
        <button
          className="ningyu-round-button"
          type="button"
          onClick={onToggleNight}
          aria-label={isNight ? "切换到日间模式" : "切换到夜间模式"}
        >
          <Icon name={isNight ? "moon" : "sun"} />
        </button>
        <SafetyIndicator
          isNight={isNight}
          safetyState={safetyState}
          isExpanded={isSafetyEntryOpen}
          onToggle={onToggleSafetyEntry}
        />
      </div>
    </header>
  );
}

function LeftSidebar({
  isNight,
  userModeLabel,
  memoryModeLabel,
}: {
  isNight: boolean;
  userModeLabel: string;
  memoryModeLabel: string;
}) {
  return (
    <aside className="ningyu-sidebar ningyu-sidebar--left" aria-label="会话与功能入口">
      <div className="ningyu-sidebar__top">
        <button className="ningyu-new-chat" type="button">
          <Icon name="plus" />
          开始新对话
        </button>
      </div>

      <div className="ningyu-thread-list">
        <div className="ningyu-section-label">
          <Icon name="clock" />
          最近对话
        </div>
        {conversations.map((conversation) => (
          <button className="ningyu-thread" key={conversation.id} type="button">
            <span className="ningyu-thread__dot" />
            <span className="ningyu-thread__content">
              <strong>{conversation.title}</strong>
              <span>{conversation.preview}</span>
              <small>{conversation.time}</small>
            </span>
          </button>
        ))}
      </div>

      <div className="ningyu-sidebar__bottom">
        <button type="button">
          <Icon name="spark" />
          情绪记录
        </button>
        <button type="button">
          <Icon name="settings" />
          设置
        </button>
      </div>
      <span className="ningyu-sidebar__mode">
        {isNight ? "夜间陪伴" : "日间陪伴"} · {userModeLabel} · {memoryModeLabel}
      </span>
    </aside>
  );
}

function ChatWorkspace({
  isNight,
  messages,
  onSend,
}: {
  isNight: boolean;
  messages: Message[];
  onSend: (content: string) => void;
}) {
  return (
    <section className="ningyu-chat" aria-label="聊天工作区">
      <div className="ningyu-chat__scroll">
        <div className="ningyu-chat__inner">
          {messages.length === 0 ? (
            <WelcomeState isNight={isNight} />
          ) : (
            <div className="ningyu-chat__messages">
              {messages.map((message) => (
                <ChatMessage key={message.id} message={message} isNight={isNight} />
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="ningyu-chat__input">
        <ChatInput isNight={isNight} onSend={onSend} />
      </div>
    </section>
  );
}

function WelcomeState({ isNight }: { isNight: boolean }) {
  return (
    <div className="ningyu-welcome">
      <Icon name="leaf" className="ningyu-welcome__leaf ningyu-welcome__leaf--one" />
      <Icon name="leaf" className="ningyu-welcome__leaf ningyu-welcome__leaf--two" />
      <img src={logo} alt="" aria-hidden="true" />
      <h2>
        <Icon name="leaf" />
        宁语陪伴
        <Icon name="leaf" />
      </h2>
      <p>这是一个安静的角落。你可以放心地分享你的感受，我会像微风一样，陪伴在这里倾听。</p>
      <span>
        <Icon name="spark" />
        {isNight ? "夜色很轻，慢慢说就好" : "随时可以开始"}
      </span>
    </div>
  );
}

function ChatInput({ isNight, onSend }: { isNight: boolean; onSend: (content: string) => void }) {
  const [value, setValue] = useState("");

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextValue = value.trim();
    if (!nextValue) return;
    onSend(nextValue);
    setValue("");
  };

  return (
    <form className="ningyu-input" onSubmit={handleSubmit}>
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={isNight ? "夜风很安静，慢慢写..." : "随便写点什么吧，风在听..."}
        aria-label="输入聊天内容"
      />
      <button className={value.trim() ? "is-active" : ""} type="submit" disabled={!value.trim()} aria-label="发送">
        <Icon name="send" />
      </button>
    </form>
  );
}

function ChatMessage({ message, isNight }: { message: Message; isNight: boolean }) {
  const isUser = message.role === "user";

  return (
    <article className={`ningyu-message ${isUser ? "is-user" : "is-assistant"} ${isNight ? "is-night" : ""}`}>
      <div className="ningyu-message__meta">{isUser ? "你" : "宁语"}</div>
      <div className="ningyu-message__bubble">
        <Icon name={isUser ? "leaf" : "wind"} />
        <p>{message.content}</p>
      </div>
      <time>{message.timestamp}</time>
    </article>
  );
}

function RightPanel({
  isNight,
  currentUserLabel,
  statusTags,
  safetyState,
  isSafetyEntryOpen,
  onToggleSafetyEntry,
  onRetrySafetyState,
}: {
  isNight: boolean;
  currentUserLabel: string;
  statusTags: string[];
  safetyState: { tone: SafetyTone; label: string; detail: string };
  isSafetyEntryOpen: boolean;
  onToggleSafetyEntry: () => void;
  onRetrySafetyState: () => void;
}) {
  return (
    <aside className="ningyu-sidebar ningyu-sidebar--right" aria-label="状态、安全与建议">
      <section className="ningyu-panel-section ningyu-panel-section--safety">
        <h2>
          <Icon name="wind" />
          安全入口
        </h2>
        <button
          className={`ningyu-safety-entry is-${safetyState.tone}`}
          type="button"
          onClick={onToggleSafetyEntry}
          aria-expanded={isSafetyEntryOpen}
        >
          <span className="ningyu-safety-entry__badge">
            <Icon name="shield" />
          </span>
          <span className="ningyu-safety-entry__content">
            <strong>{safetyState.label}</strong>
            <small>{safetyState.detail}</small>
          </span>
        </button>
        <div className="ningyu-safety-actions">
          <button type="button" onClick={onToggleSafetyEntry}>
            {isSafetyEntryOpen ? "收起支持" : "展开支持"}
          </button>
          <button type="button" onClick={onRetrySafetyState}>
            重新检查
          </button>
        </div>
      </section>

      <section className={`ningyu-panel-section ${isSafetyEntryOpen ? "is-open" : ""}`}>
        <h2>
          <Icon name="heart" />
          当前状态 · {currentUserLabel}
        </h2>
        <div className="ningyu-tags">
          {statusTags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      </section>

      <section className="ningyu-panel-section">
        <h2>
          <Icon name="heart" />
          安全支持
        </h2>
        <button className="ningyu-support-card" type="button">
          <Icon name="phone" />
          <span>
            <small>24小时热线</small>
            400-xxx-xxxx
          </span>
        </button>
        <button className="ningyu-support-card" type="button">
          <Icon name="message" />
          <span>
            <small>紧急咨询</small>
            立即连接
          </span>
        </button>
      </section>

      <section className="ningyu-panel-section">
        <h2>
          <Icon name="light" />
          可以试试
        </h2>
        <div className="ningyu-suggestions">
          {suggestions.map((suggestion) => (
            <button key={suggestion} type="button">
              {suggestion}
            </button>
          ))}
        </div>
      </section>
      <span className="ningyu-sidebar__mode">
        {isNight ? "夜间保持安全入口可见" : "白天保持安全入口可见"}
      </span>
    </aside>
  );
}

function SafetyIndicator({
  isNight,
  safetyState,
  isExpanded,
  onToggle,
}: {
  isNight: boolean;
  safetyState: { tone: SafetyTone; label: string; detail: string };
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      className={`ningyu-safety is-${safetyState.tone} ${isExpanded ? "is-expanded" : ""}`}
      type="button"
      onClick={onToggle}
      aria-expanded={isExpanded}
      aria-label={isExpanded ? "收起安全入口" : "展开安全入口"}
    >
      <Icon name="shield" />
      <span className="ningyu-safety__content">
        <strong>{isNight ? "夜间安全陪伴" : "安全陪伴空间"}</strong>
        <small>{safetyState.label}</small>
      </span>
    </button>
  );
}

function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  const paths: Record<IconName, React.ReactNode> = {
    moon: <path d="M19.5 15.2A7.2 7.2 0 0 1 8.8 4.5 8 8 0 1 0 19.5 15.2Z" />,
    sun: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.4 1.4M17.6 17.6 19 19M19 5l-1.4 1.4M6.4 17.6 5 19" />
      </>
    ),
    shield: <path d="M12 22s7-3.5 7-10V5l-7-3-7 3v7c0 6.5 7 10 7 10Z" />,
    plus: <path d="M12 5v14M5 12h14" />,
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    spark: <path d="m12 2 1.6 6.4L20 10l-6.4 1.6L12 18l-1.6-6.4L4 10l6.4-1.6L12 2Z" />,
    settings: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.7-1L14.5 3h-5l-.4 3.1a7 7 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.7 1l.4 3.1h5l.4-3.1a7 7 0 0 0 1.7-1l2.4 1 2-3.4-2-1.5c.1-.3.1-.7.1-1Z" />
      </>
    ),
    heart: <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z" />,
    phone: <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.4 19.4 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7l.5 3a2 2 0 0 1-.6 1.8L7.7 9.7a16 16 0 0 0 6.6 6.6l1.2-1.2a2 2 0 0 1 1.8-.6l3 .5a2 2 0 0 1 1.7 1.9Z" />,
    message: <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v8Z" />,
    light: (
      <>
        <path d="M9 18h6" />
        <path d="M10 22h4" />
        <path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2Z" />
      </>
    ),
    wind: <path d="M3 8h11a3 3 0 1 0-3-3M4 12h15a3 3 0 1 1-3 3M3 16h8" />,
    leaf: <path d="M5 21c7-1 13-7 14-14-7 1-13 7-14 14ZM5 21c2-4 6-8 10-10" />,
    send: <path d="m22 2-7 20-4-9-9-4 20-7Z" />,
  };

  return (
    <svg className={`ningyu-icon ${className}`} viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}
