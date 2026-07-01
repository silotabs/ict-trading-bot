import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import ts from "typescript";

const root = new URL("..", import.meta.url).pathname;

function read(relativePath) {
  return readFileSync(join(root, relativePath), "utf8");
}

function extractExportedFunction(source, name) {
  const start = source.indexOf(`export function ${name}`);
  assert.notEqual(start, -1, `Expected exported function ${name} to exist`);

  const bodyStart = source.indexOf("{", start);
  assert.notEqual(bodyStart, -1, `Expected exported function ${name} to have a body`);

  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index];
    if (char === "{") {
      depth += 1;
    } else if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        return source.slice(start, index + 1);
      }
    }
  }

  assert.fail(`Expected exported function ${name} body to close`);
}

function compileExportedFunction(source, name, dependencies = {}) {
  const compiled = ts.transpileModule(extractExportedFunction(source, name), {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText.replace(/^export /m, "");

  return Function(...Object.keys(dependencies), `${compiled}; return ${name};`)(...Object.values(dependencies));
}

test("runtime API client targets current backend surfaces", () => {
  const source = read("src/lib/api-runtime.ts");
  for (const endpoint of [
    "/ready",
    "/v1/signal-traces",
    "/v1/execution-intents",
    "/v1/execution-risk-checks",
    "/v1/shadow-review/summary",
  ]) {
    assert.match(source, new RegExp(endpoint.replaceAll("/", "\\/")));
  }
});

test("dashboard renders the current operator runtime panels", () => {
  const source = read("src/App.tsx");
  for (const label of [
    "Public Event Stream",
    "Shadow Review",
    "Signal Traces",
    "Execution Intents",
    "Risk Checks",
    "Not executable",
  ]) {
    assert.match(source, new RegExp(label));
  }

  assert.match(source, /formatOperatorStatusLabel\(item\.decision/);
  assert.match(source, /formatOperatorStatusLabel\(item\.opportunity_state/);
  assert.match(source, /formatBlockerClassLabel\(item\.blocker_class/);
  assert.match(source, /rawStatusTitle\("risk state", item\.state\)/);
});

test("executable decision checks remain verified-only", () => {
  const support = read("src/dashboard/app-support.tsx");
  const legacyDecisionMatches = support.match(/(?<!verified_)paper_trade/g) ?? [];

  assert.match(support, /return decision === "verified_paper_trade";/);
  assert.equal(legacyDecisionMatches.length, 0);
});

test("risk control allow state renders as a positive operator status", () => {
  const support = read("src/dashboard/app-support.tsx");
  const cleanLabel = compileExportedFunction(support, "cleanLabel");
  const formatOperatorStatusLabel = compileExportedFunction(support, "formatOperatorStatusLabel", { cleanLabel });
  const riskCheckBadgeStatus = compileExportedFunction(support, "riskCheckBadgeStatus");

  assert.equal(riskCheckBadgeStatus("allow"), "good");
  assert.equal(riskCheckBadgeStatus("allowed"), "good");
  assert.equal(formatOperatorStatusLabel("allow"), "Risk allowed");
  assert.equal(formatOperatorStatusLabel("allowed"), "Risk allowed");
});
