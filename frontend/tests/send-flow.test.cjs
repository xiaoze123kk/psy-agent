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

test("shouldCreateThreadForSend allows direct send from home state", () => {
  const { shouldCreateThreadForSend } = loadTsModule("src/app/ningyu/sendFlow.ts");

  assert.equal(shouldCreateThreadForSend(null), true);
  assert.equal(shouldCreateThreadForSend({ kind: "draft" }), true);
  assert.equal(shouldCreateThreadForSend({ kind: "thread", threadId: "thread-1" }), false);
});
