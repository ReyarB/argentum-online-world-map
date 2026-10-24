const fs = require("fs");
const path = require("path");

const htmlPath = path.resolve(process.argv[2] || "dist-web/index.htm");
const html = fs.readFileSync(htmlPath, "utf8");
let position = 0;
let scripts = 0;

for (;;) {
  const start = html.indexOf("<script", position);
  if (start < 0) break;
  const bodyStart = html.indexOf(">", start);
  const end = html.indexOf("</script>", bodyStart);
  if (bodyStart < 0 || end < 0) throw new Error("Etiqueta script sin cierre");
  Function(html.slice(bodyStart + 1, end));
  scripts += 1;
  position = end + 9;
}

const references = Array.from(
  html.matchAll(/(?:src|data-src)="([^"]+)"/g),
  (match) => match[1],
).filter((reference) => !reference.includes("${"));
const missing = references.filter(
  (reference) => !fs.existsSync(path.resolve(path.dirname(htmlPath), reference)),
);

if (scripts === 0) throw new Error("No se encontró JavaScript embebido");
if (missing.length > 0) {
  throw new Error(`Referencias inexistentes:\n${missing.join("\n")}`);
}
console.log(JSON.stringify({ scripts, references: references.length, missing: missing.length }));
