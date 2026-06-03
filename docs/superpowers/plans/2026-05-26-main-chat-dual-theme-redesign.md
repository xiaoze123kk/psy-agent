# Main Chat Dual Theme Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `main` 分支已登录后的宁语主聊天界面改为居中对话舞台，并保留日间/夜间双主题。

**Architecture:** 保留 `NingyuAppShell.tsx` 的现有数据流、发送逻辑、消息渲染和浮动入口，只做必要 markup 调整。主要通过 `NingyuAppShell.css` 重建聊天舞台、消息气泡、输入栏和响应式布局；用一个轻量 CSS 合同测试防止厚重纸页样式回归。

**Tech Stack:** Vite + React + TypeScript + CSS，测试使用 Node 内置 `node:test` 和 `node:assert`，验证使用 `npm run check`、`npm run test:unit`、浏览器截图。

---

### Task 1: Add CSS Contract Test

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/tests/chat-shell-css.test.cjs`

- [ ] **Step 1: Add the unit-test script**

Update `frontend/package.json` scripts:

```json
"test:unit": "node --test tests/*.test.cjs"
```

- [ ] **Step 2: Write failing CSS contract test**

Create `frontend/tests/chat-shell-css.test.cjs`:

```js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const cssPath = path.join(__dirname, "..", "src", "app", "ningyu", "NingyuAppShell.css");
const css = fs.readFileSync(cssPath, "utf8");

test("main chat stage uses light conversation-stage styling instead of heavy paper treatment", () => {
  assert.match(css, /\.ningyu-chat__stage-token/);
  assert.doesNotMatch(css, /\.ningyu-chat-paper::after/);
  assert.doesNotMatch(css, /clip-path:\s*polygon/);
});

test("main chat stage defines both day and night surface palettes", () => {
  assert.match(css, /--ningyu-chat-stage-bg:/);
  assert.match(css, /--ningyu-chat-stage-bg-night:/);
  assert.match(css, /\.ningyu-shell\.is-night\s+\.ningyu-chat/);
});
```

- [ ] **Step 3: Verify the test fails before implementation**

Run:

```powershell
npm run test:unit
```

Expected: FAIL because current CSS still has heavy paper selectors and does not define `.ningyu-chat__stage-token`.

### Task 2: Reshape Chat Workspace Markup

**Files:**
- Modify: `frontend/src/app/ningyu/NingyuAppShell.tsx`

- [ ] **Step 1: Rename the central paper wrapper classes**

In `ChatWorkspace`, change the central wrapper from:

```tsx
className="ningyu-chat__inner ningyu-chat-paper"
```

to:

```tsx
className="ningyu-chat__inner ningyu-chat-stage ningyu-chat__stage-token"
```

- [ ] **Step 2: Keep title/date but make ornament optional**

Keep the existing header markup so the title/date remain available:

```tsx
<div className="ningyu-chat-corner" aria-hidden="true" />
<header className="ningyu-chat-header">
  <img className="ningyu-chat-seal" src={logo} alt="" aria-hidden="true" />
  <h1 className="ningyu-chat-title">宁语手记</h1>
  <p className="ningyu-chat-date">{chatPaperDate}</p>
</header>
```

The CSS task will make this compact rather than hero-like.

### Task 3: Rebuild Main Chat CSS

**Files:**
- Modify: `frontend/src/app/ningyu/NingyuAppShell.css`

- [ ] **Step 1: Add shared chat-stage theme variables**

At the start of the `.ningyu-chat` block, add stage variables:

```css
.ningyu-chat {
  --ningyu-chat-stage-bg: linear-gradient(135deg, rgba(255, 253, 246, 0.72), rgba(237, 251, 247, 0.36));
  --ningyu-chat-stage-bg-night: linear-gradient(135deg, rgba(11, 23, 34, 0.86), rgba(17, 35, 48, 0.72));
  --ningyu-chat-stage-border: rgba(90, 130, 118, 0.28);
  --ningyu-chat-stage-border-night: rgba(125, 159, 181, 0.2);
  --ningyu-chat-line: rgba(49, 91, 82, 0.08);
  --ningyu-chat-line-night: rgba(171, 190, 211, 0.075);
}
```

- [ ] **Step 2: Replace heavy paper surface**

Replace `.ningyu-chat__inner`, `.ningyu-chat__inner::before`, `.ningyu-chat-paper::after`, `.ningyu-chat-header`, `.ningyu-chat-paper__body`, and related night selectors with the lightweight stage rules:

```css
.ningyu-chat__inner {
  position: relative;
  width: min(100%, 900px);
  min-height: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ningyu-chat-stage-border);
  border-radius: 14px;
  background: var(--ningyu-chat-stage-bg);
  box-shadow: 0 18px 52px rgba(15, 78, 71, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.35);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  overflow: hidden;
}
```

Remove the `clip-path: polygon(...)` and `.ningyu-chat-paper::after` rule entirely.

- [ ] **Step 3: Compact the chat header**

Make the stage header compact:

```css
.ningyu-chat-header {
  position: relative;
  z-index: 1;
  padding: 22px 28px 18px;
  border-bottom: 1px solid rgba(90, 130, 118, 0.16);
  text-align: center;
}
```

- [ ] **Step 4: Tune messages, graph trail, floating controls, input**

Adjust existing selectors only:

- `.ningyu-message__bubble`
- `.ningyu-message.is-user .ningyu-message__bubble`
- `.ningyu-chat__input`
- `.ningyu-input`
- `.ningyu-floating-controls`
- `.ningyu-graph-trail` / existing graph update selectors

Use the same class names and make day/night variants intentional. Do not change message data flow.

### Task 4: Responsive Pass

**Files:**
- Modify: `frontend/src/app/ningyu/NingyuAppShell.css`

- [ ] **Step 1: Update existing media queries**

In the existing mobile media query, ensure:

```css
.ningyu-chat__scroll {
  padding: 16px 12px 12px;
}

.ningyu-chat__inner {
  width: 100%;
  border-radius: 12px;
}

.ningyu-chat__input {
  padding: 10px 12px 14px;
}

.ningyu-floating-controls {
  max-width: calc(100vw - 24px);
}
```

- [ ] **Step 2: Confirm no horizontal scroll**

Run a browser mobile viewport check and verify `document.documentElement.scrollWidth <= window.innerWidth`.

### Task 5: Documentation and Verification

**Files:**
- Modify: `docs/dev-log/frontend-conversation-list.md` or create a new focused dev-log if the existing topic does not fit.

- [ ] **Step 1: Write dev-log entry**

Record:

- 日期：2026-05-26
- 背景：main 主聊天界面视觉偏厚，用户希望迁回居中对话舞台质感
- 关键改动：CSS 合同测试、聊天舞台轻量化、日夜主题、响应式调整
- 验证结果：unit/type/build/browser
- 后续事项：可继续微调图运行轨迹折叠策略

- [ ] **Step 2: Run final verification**

Run:

```powershell
npm run test:unit
npm run check
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 3: Browser verification**

Use Playwright or browser tooling:

- Desktop viewport around `1440x1000`
- Mobile viewport around `390x844`
- Verify day and night shell classes
- Verify loaded main chat screen is nonblank
- Verify no major overlap or clipped primary text

- [ ] **Step 4: Commit frontend changes only**

Stage only frontend and frontend dev-log/spec/plan files:

```powershell
git add frontend/package.json frontend/tests/chat-shell-css.test.cjs frontend/src/app/ningyu/NingyuAppShell.tsx frontend/src/app/ningyu/NingyuAppShell.css docs/dev-log/<chosen-log>.md docs/superpowers/plans/2026-05-26-main-chat-dual-theme-redesign.md
git commit -m "feat: 重塑主界面对话舞台"
```

Do not stage the existing backend registration fix unless explicitly requested.
