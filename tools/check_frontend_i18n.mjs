// Ověří úplnost anglického překladu frontendu.
//   node tools/check_frontend_i18n.mjs          – kontrola (exit 1 při chybě)
//   node tools/check_frontend_i18n.mjs --keys   – vypíše chybějící klíče jako JSON
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(path.resolve("frontend/package.json"));
const ts = require("typescript");
const SRC = "frontend/src";
const CZECH = /[áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]/;
// Záměrně nepřekládané texty (názvy jazyků v přepínači).
const ALLOWED_CZECH = new Set(["Čeština"]);

function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    return e.isDirectory() ? files(p) : /\.(tsx|ts)$/.test(e.name) ? [p] : [];
  });
}

const enSource = fs.readFileSync(path.join(SRC, "lib/i18n-en.ts"), "utf8");
const enFile = ts.createSourceFile("en.ts", enSource, ts.ScriptTarget.Latest, true);
const en = new Map();
enFile.forEachChild(function walk(node) {
  if (ts.isPropertyAssignment(node) && ts.isStringLiteral(node.name) && ts.isStringLiteral(node.initializer)) {
    en.set(node.name.text, node.initializer.text);
  }
  ts.forEachChild(node, walk);
});

const keys = new Map();
const untranslated = [];
for (const file of files(SRC)) {
  const rel = path.relative(SRC, file);
  if (rel === "lib/i18n-en.ts") continue;
  const text = fs.readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const covered = new Set();
  const visit = (node) => {
    if (ts.isCallExpression(node) && ["t", "N_"].includes(node.expression.getText()) && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) {
      const key = node.arguments[0].text;
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart());
      if (!keys.has(key)) keys.set(key, `${rel}:${line + 1}`);
      covered.add(node.arguments[0]);
    }
    const literal = ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateExpression(node) || ts.isJsxText(node);
    if (literal && !covered.has(node) && CZECH.test(node.getText()) && !ALLOWED_CZECH.has(node.getText().trim()) && !ALLOWED_CZECH.has(node.getText().slice(1, -1))) {
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart());
      untranslated.push(`${rel}:${line + 1}: ${node.getText().trim().slice(0, 90)}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
}

const missing = [...keys.keys()].filter((k) => !en.has(k));
const unused = [...en.keys()].filter((k) => !keys.has(k));
const badParams = [...keys.keys()].filter((k) => en.has(k)).filter((k) => {
  const a = (k.match(/\{\w+\}/g) ?? []).sort().join();
  const b = (en.get(k).match(/\{\w+\}/g) ?? []).sort().join();
  return a !== b;
});

if (process.argv.includes("--keys")) {
  console.log(JSON.stringify(missing.map((k) => [k, keys.get(k)]), null, 1));
  process.exit(0);
}
for (const k of missing) console.log(`chybí překlad: ${JSON.stringify(k)}  (${keys.get(k)})`);
for (const k of badParams) console.log(`nesouhlasí proměnné: ${JSON.stringify(k)} → ${JSON.stringify(en.get(k))}`);
for (const k of unused) console.log(`nepoužitý překlad: ${JSON.stringify(k)}`);
for (const u of untranslated) console.log(`český text mimo t(): ${u}`);
const failed = missing.length + badParams.length + untranslated.length;
console.log(`${failed ? "CHYBA" : "OK"} – klíčů ${keys.size}, chybí ${missing.length}, nepoužité ${unused.length}, mimo t() ${untranslated.length}`);
process.exit(failed ? 1 : 0);
