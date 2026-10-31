// Run a .gbn file with the JavaScript interpreter: node playground/run.js file.gbn
const fs = require("fs");
const G = require("./gatbandhan.js");

async function main() {
  const file = process.argv[2];
  const it = new G.Interpreter({ print: line => process.stdout.write(line + "\n") });
  try {
    await it.run(fs.readFileSync(file, "utf8"));
  } catch (e) {
    if (e instanceof G.GatbandhanError) {
      process.stderr.write(`${file}: ${e.message}\n`);
      process.exit(1);
    }
    throw e;
  }
}
main();
