const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const cssPath = path.join(__dirname, "..", "src", "app", "ningyu", "NingyuAppShell.css");
const shellPath = path.join(__dirname, "..", "src", "app", "ningyu", "NingyuAppShell.tsx");
const css = fs.readFileSync(cssPath, "utf8");
const shell = fs.readFileSync(shellPath, "utf8");

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

test("main chat stage avoids notebook page ornaments and ruled paper texture", () => {
  assert.doesNotMatch(shell, /ningyu-chat-paper/);
  assert.doesNotMatch(shell, /ningyu-chat-corner/);
  assert.doesNotMatch(css, /ningyu-chat-paper/);
  assert.doesNotMatch(css, /ningyu-chat-corner/);
  assert.doesNotMatch(css, /--ningyu-chat-line/);
});
