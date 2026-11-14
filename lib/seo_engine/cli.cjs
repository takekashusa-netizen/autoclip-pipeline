// stdin JSON {topic, category, extra, platform} -> stdout JSON from the SEO Studio engine.
// engine.cjs is a copy of takekash-site/lib/seo/engine.cjs — keep them in sync.
const E = require("./engine.cjs");
let s = ""; process.stdin.on("data", (d) => (s += d)).on("end", () => {
  try { process.stdout.write(JSON.stringify(E.generate(JSON.parse(s)))); } catch (e) { process.stderr.write(String(e)); process.exit(1); }
});
