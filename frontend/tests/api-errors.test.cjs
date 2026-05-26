const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadTsModule(relativePath) {
  const filePath = path.join(__dirname, "..", relativePath);
  const source = fs.readFileSync(filePath, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  });
  const module = { exports: {} };
  const compiled = new Function("require", "module", "exports", "__dirname", "__filename", outputText);
  compiled(require, module, module.exports, path.dirname(filePath), filePath);
  return module.exports;
}

test("extractApiErrorDetail reads FastAPI detail from API errors", () => {
  const { extractApiErrorDetail } = loadTsModule("src/api/errors.ts");

  assert.equal(
    extractApiErrorDetail(new Error('API 400: {"detail":"图形验证码错误或已过期。"}')),
    "图形验证码错误或已过期。",
  );
});

test("getFriendlyApiError prefers backend detail before status fallback", () => {
  const { getFriendlyApiError } = loadTsModule("src/api/errors.ts");

  assert.equal(
    getFriendlyApiError(
      new Error('API 400: {"detail":"图形验证码错误或已过期。"}'),
      "登录失败，请检查输入。",
      { 400: "请求参数有误，请检查输入。" },
    ),
    "图形验证码错误或已过期。",
  );
  assert.equal(
    getFriendlyApiError(new Error("API 401: {}"), "登录失败，请检查输入。", { 401: "用户名或密码错误。" }),
    "用户名或密码错误。",
  );
});
