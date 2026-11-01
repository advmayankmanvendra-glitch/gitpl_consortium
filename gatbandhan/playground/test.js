// Tests for the JavaScript interpreter: node playground/test.js
//
// tests/parity.json holds programs with the output the Python reference
// interpreter gives (the Python tests check that file). The JavaScript
// version must give exactly the same output.
const fs = require("fs");
const path = require("path");
const G = require("./gatbandhan.js");

const root = path.join(__dirname, "..");
let failed = 0;
let passed = 0;

async function runProgram(src, clock) {
  const lines = [];
  const it = new G.Interpreter({ print: l => lines.push(l), clock });
  try {
    await it.run(src);
  } catch (e) {
    if (!(e instanceof G.GatbandhanError)) throw e;
    lines.push(`${e.constructor.name}: ${e.message}`);
  }
  return lines.length ? lines.join("\n") + "\n" : "";
}

function check(name, ok, detail) {
  if (ok) { passed++; return; }
  failed++;
  console.log(`FAIL ${name}\n${detail || ""}`);
}

(async () => {
  const cases = JSON.parse(fs.readFileSync(path.join(root, "tests", "parity.json"), "utf8"));
  for (const c of cases) {
    const got = await runProgram(c.source, () => "T");
    check(c.source.slice(0, 60), got === c.output, `expected:\n${c.output}got:\n${got}`);
  }

  const dirs = [path.join(root, "examples"), path.join(__dirname, "examples")];
  for (const dir of dirs) {
    for (const name of fs.readdirSync(dir).filter(n => n.endsWith(".gbn")).sort()) {
      const out = await runProgram(fs.readFileSync(path.join(dir, name), "utf8"));
      const refused = out.includes("BondError: ");
      const errored = /Gbn\w+Error: /.test(out);
      if (name.startsWith("refused_")) check(name, refused, out);
      else check(name, !refused && !errored, out);
    }
  }

  // a kept bond continues across runs and refuses a changed vow
  const store = new G.MemoryStore();
  const kept = vow => `member s(q) { return "yes" }
    bond us { human: "M" ai: s keep: "k" vow honesty: "${vow}" }
    remember us "visit" print(len(memory(us)))`;
  const runKept = async vow => {
    const lines = [];
    const it = new G.Interpreter({ print: l => lines.push(l), store });
    try { await it.run(kept(vow)); } catch (e) { lines.push(e.constructor.name); }
    return lines.join(" ");
  };
  check("kept bond, first run", (await runKept("truth")) === "3");
  check("kept bond, second run", (await runKept("truth")) === "4");
  check("kept bond, changed vow", (await runKept("lies")) === "BondError");
  const raw = store.getItem("gatbandhan:k");
  store.setItem("gatbandhan:k", raw.replace('"visit"', '"rewritten"'));
  const it = new G.Interpreter({ print: () => {}, store });
  let msg = "";
  try { await it.run(kept("truth")); } catch (e) { msg = e.message; }
  check("hand-edited memory is refused", msg.includes("changed by hand"), msg);

  // the human partner answers through the ask callback
  const answers = ["yes", "glad", ""];
  const lines = [];
  const it2 = new G.Interpreter({ print: l => lines.push(l), ask: async () => answers.shift() });
  await it2.run(`member s(q) { return "yes" } bond us { human: "M" ai: s }
    let a = us("one?") print(a.gate, a.feelings) print(us("two?").reason)`);
  check("human answers through ask", lines.join("|") === '1 ∧ 1 = 1 {M: "glad"}|no consent: M did not answer', lines.join("|"));

  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
