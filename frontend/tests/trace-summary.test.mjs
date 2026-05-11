import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import ts from "typescript";

async function loadTraceModule() {
  const source = await readFile(new URL("../src/utils/trace.ts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
      importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    },
  });
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
  return import(moduleUrl);
}

test("normalizeTraceSummary keeps safe structured trace fields", async () => {
  const { normalizeTraceSummary, traceHeadline, traceMemoryRefs } = await loadTraceModule();
  const trace = normalizeTraceSummary({
    node_count: 3,
    mode: { intent: "soothe", route_priority: "P2_support", risk_level: "L1" },
    memory: {
      retrieved_count: 2,
      referenced_count: 1,
      referenced_memories: [{ memory_id: "m1", memory_type: "support_strategy", content: "晚上先做呼吸练习" }],
    },
    rag: { used: true, retrieved_example_count: 2 },
    validator: { checked: true, blocked: false, reasons: [] },
    steps: [{ node_name: "memory_retrieval", duration_ms: 7 }],
  });

  assert.equal(trace.node_count, 3);
  assert.equal(trace.steps[0].node_name, "memory_retrieval");
  assert.equal(traceHeadline(trace), "安抚陪伴模式 · 引用了 1 条记忆 · 已通过校验");
  assert.equal(traceMemoryRefs(trace)[0].content, "晚上先做呼吸练习");
});

test("mergeTraceGraphUpdate turns live graph updates into Chinese-readable summary", async () => {
  const { mergeTraceGraphUpdate, traceFallbackText, traceValidatorText } = await loadTraceModule();
  const trace = mergeTraceGraphUpdate(null, {
    node: "response_validator",
    status: "completed",
    risk_level: "L2",
    validator_blocked: true,
    validator_reasons: ["rag_copy_leak"],
    delivery_status: "safety_fallback",
    failure_reason: "validator_blocked:rag_copy_leak",
    duration_ms: 12,
  });

  assert.equal(trace.steps.length, 1);
  assert.equal(trace.validator.blocked, true);
  assert.equal(traceValidatorText(trace), "校验后降级");
  assert.equal(traceFallbackText(trace), "触发安全降级");
});
