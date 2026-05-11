import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import ts from "typescript";

async function loadCompanionStylesModule() {
  const source = await readFile(new URL("../src/utils/companionStyles.ts", import.meta.url), "utf8");
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

test("parseCustomCompanionStyles normalizes legacy localStorage payloads", async () => {
  const { parseCustomCompanionStyles } = await loadCompanionStylesModule();
  const styles = parseCustomCompanionStyles(JSON.stringify([
    { id: "local-a", title: "  Calm first  ", definition: "  Start with warmth.  " },
    { id: "local-b", title: "Legacy preset", definition: "gentle" },
    { id: "local-a", title: "Duplicate", definition: "Should be ignored." },
  ]));

  assert.equal(styles.length, 1);
  assert.deepEqual(styles[0], {
    id: "local-a",
    title: "Calm first",
    definition: "Start with warmth.",
  });
});

test("buildCompanionStyleReplacePayload preserves server ids and carries client ids for migration", async () => {
  const { buildCompanionStyleReplacePayload } = await loadCompanionStylesModule();
  const payload = buildCompanionStyleReplacePayload(
    [
      {
        id: "custom-local",
        title: "Local style",
        definition: "Local migrated style.",
      },
      {
        id: "2c8d1d6e-935c-4e78-a01f-ecb1017429df",
        title: "Server style",
        definition: "Existing server style.",
      },
    ],
    "custom-local",
  );

  assert.equal(payload.selected_style_id, "custom-local");
  assert.equal(payload.items[0].style_id, undefined);
  assert.equal(payload.items[0].client_id, "custom-local");
  assert.equal(payload.items[1].style_id, "2c8d1d6e-935c-4e78-a01f-ecb1017429df");
});
