const fs = require("node:fs");
const path = require("node:path");

module.exports = async function restoreLegacyComponents(core) {
  const cache = require(path.join(process.env.RUNNER_TEMP, "bluray-cache-client/node_modules/@actions/cache"));
  const root = process.env.BLURAY_SETUP_CACHE_DIR;
  const directory = path.join(root, "components");
  const plan = JSON.parse(fs.readFileSync(process.env.BLURAY_MACOS_CACHE_PLAN));
  const entries = Object.entries(plan.components);
  fs.mkdirSync(directory, {recursive: true});

  async function worker() {
    while (entries.length) {
      const [name, input] = entries.pop();
      if (!/^[a-z0-9._-]+$/.test(name) || !/^[a-f0-9]{64}$/.test(input)) {
        throw new Error("Unexpected component in cache plan: " + name);
      }
      const base = path.join(directory, name + "-" + input);
      const files = [base + ".tar.gz", base + ".tar.sha256"];
      const prefix = "bluraysubtitle-macos-v2-" + process.env.RUNNER_ARCH + "-" + name + "-" + input + "-";
      try {
        await cache.restoreCache(files, prefix + "lookup", [prefix]);
      } catch (error) {
        core.warning(name + " cache: " + error.message);
      }
    }
  }
  await Promise.all(Array.from({length: 4}, worker));
};
