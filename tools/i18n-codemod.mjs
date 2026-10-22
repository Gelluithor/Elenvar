// Obalí české texty ve frontendu překladovou funkcí t().
//   node tools/i18n-codemod.mjs report   – vypíše texty mimo JSX k ruční kontrole
//   node tools/i18n-codemod.mjs apply    – obalí texty v JSX a vybraných atributech
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(path.resolve("frontend/package.json"));
const ts = require("typescript");

const SRC = "frontend/src";
const SKIP_FILES = new Set(["lib/i18n.ts", "lib/i18n-en.ts"]);
const ATTRS = new Set(["title", "placeholder", "aria-label", "label", "description", "alt", "confirmLabel", "subtitle", "message", "doneLabel", "hint"]);
const LETTER = /[A-Za-zÀ-ž]/;
const CZECH = /[áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]/;

function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return files(p);
    return /\.(tsx|ts)$/.test(e.name) ? [p] : [];
  });
}

function jsxValue(raw) {
  // stejná pravidla pro bílé znaky jako React/TypeScript
  const lines = raw.split(/\r\n|\n|\r/);
  const parts = [];
  lines.forEach((line, i) => {
    let s = line.replace(/\t/g, " ");
    if (i !== 0) s = s.replace(/^\s+/, "");
    if (i !== lines.length - 1) s = s.replace(/\s+$/, "");
    if (s) parts.push(s);
  });
  return parts.join(" ");
}

function insideTag(node, names) {
  for (let p = node.parent; p; p = p.parent) {
    if (ts.isJsxElement(p)) {
      const tag = p.openingElement.tagName.getText();
      if (names.includes(tag)) return true;
    }
  }
  return false;
}

function isTopLevel(node) {
  for (let p = node.parent; p; p = p.parent) {
    if (ts.isFunctionLike(p)) return false;
  }
  return true;
}

function insideCall(node, names) {
  for (let p = node.parent; p; p = p.parent) {
    if (ts.isCallExpression(p) && names.includes(p.expression.getText())) return true;
    if (ts.isFunctionLike(p)) return false;
  }
  return false;
}

const mode = process.argv[2] ?? "report";
// Texty, které se nepřekládají (názvy produktů, klávesy, vývojářské hlášky).
const KEEP = new Set(["Escape", "Edge", "Firefox", "Chrome", "Safari", "Windows", "Android", "Linux", "useAuth musí být použit uvnitř AuthProvider"]);

function paramName(expr) {
  let e = expr;
  while (ts.isNonNullExpression(e) || ts.isParenthesizedExpression(e)) e = e.expression;
  if (ts.isPropertyAccessExpression(e)) return e.name.text;
  if (ts.isIdentifier(e)) return e.text;
  if (ts.isCallExpression(e) && e.arguments.length) return paramName(e.arguments[0]);
  return "value";
}

function templateToCall(node) {
  if (ts.isNoSubstitutionTemplateLiteral(node)) return `t(${JSON.stringify(node.text)})`;
  let key = node.head.text;
  const params = [];
  const used = new Map();
  for (const span of node.templateSpans) {
    let name = paramName(span.expression);
    const count = used.get(name) ?? 0;
    used.set(name, count + 1);
    if (count) name = `${name}${count + 1}`;
    key += `{${name}}` + span.literal.text;
    params.push(`${name}: ${span.expression.getText()}`);
  }
  return `t(${JSON.stringify(key)}, { ${params.join(", ")} })`;
}
const report = [];
for (const file of files(SRC)) {
  const rel = path.relative(SRC, file);
  if (SKIP_FILES.has(rel)) continue;
  const text = fs.readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const edits = [];
  const visit = (node) => {
    if (ts.isJsxText(node)) {
      const raw = node.getFullText();
      const value = jsxValue(raw);
      if (value.trim() && LETTER.test(value) && !insideTag(node, ["code", "pre"])) {
        const start = node.getFullStart();
        const lead = raw.length - raw.trimStart().length;
        const trail = raw.length - raw.trimEnd().length;
        const core = value.trim();
        edits.push([start + lead, start + raw.length - trail, `{t(${JSON.stringify(core)})}`]);
      }
    } else if (ts.isJsxAttribute(node) && node.initializer && ts.isStringLiteral(node.initializer)) {
      const name = node.name.getText();
      const value = node.initializer.text;
      if (ATTRS.has(name) && LETTER.test(value)) {
        edits.push([node.initializer.getStart(), node.initializer.getEnd(), `{t(${JSON.stringify(value)})}`]);
      }
    } else if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateExpression(node)) &&
               !ts.isJsxAttribute(node.parent) && !ts.isImportDeclaration(node.parent) && !ts.isLiteralTypeNode(node.parent)) {
      const value = node.getText().slice(1, -1);
      const natural = CZECH.test(value) || /^[A-ZÁ-Ž][a-zá-ž]+(\s|$|[.,:!?…])/.test(value);
      const isKey = ts.isPropertyAssignment(node.parent) && node.parent.name === node;
      if (natural && !isKey && !insideCall(node, ["t", "N_", "api", "fetch"])) {
        const { line } = sf.getLineAndCharacterOfPosition(node.getStart());
        report.push(`${rel}:${line + 1}${isTopLevel(node) ? " [modul]" : ""}  ${node.getText()}`);
        const plain = ts.isStringLiteral(node) ? node.text : null;
        if (mode === "apply-strings" && !(plain !== null && KEEP.has(plain))) {
          if (isTopLevel(node)) {
            if (plain !== null) edits.push([node.getStart(), node.getEnd(), `N_(${JSON.stringify(plain)})`]);
          } else if (ts.isTemplateExpression(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
            edits.push([node.getStart(), node.getEnd(), templateToCall(node)]);
          } else {
            edits.push([node.getStart(), node.getEnd(), `t(${JSON.stringify(plain)})`]);
          }
        }
        return;
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  if ((mode === "apply" || mode === "apply-strings") && edits.length) {
    edits.sort((a, b) => b[0] - a[0]);
    let out = text;
    for (const [s, e, r] of edits) out = out.slice(0, s) + r + out.slice(e);
    const needN = out.includes("N_(") && !/\bN_\b[^\n]*from "[./]*(lib\/)?i18n"/.test(out);
    const hasT = /import \{[^}]*\bt\b[^}]*\} from "[./]*(lib\/)?i18n"/.test(out);
    if (!hasT || needN) {
      out = out.replace(/^import \{ t \} from "([./]*(?:lib\/)?i18n)";\n/m, "");
      const depth = rel.split(path.sep).length - 1;
      const target = rel.startsWith("lib/") ? "./i18n" : `${depth ? "../".repeat(depth) : "./"}lib/i18n`;
      const names = out.includes("N_(") ? "N_, t" : "t";
      const imp = `import { ${names} } from "${target}";\n`;
      const lastImport = [...out.matchAll(/^import .*?;\n/gms)].pop();
      const at = lastImport ? lastImport.index + lastImport[0].length : 0;
      out = out.slice(0, at) + imp + out.slice(at);
    }
    fs.writeFileSync(file, out);
    console.log(`upraveno: ${rel} (${edits.length})`);
  }
}
if (mode === "report") console.log(report.join("\n"));
