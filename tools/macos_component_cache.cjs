const fs = require("node:fs");
const path = require("node:path");

module.exports = async function componentCaches(mode, core) {
  const cache = require(path.join(process.env.RUNNER_TEMP, "bluray-cache-client/node_modules/@actions/cache"));
  const root = process.env.BLURAY_SETUP_CACHE_DIR;
  const directory = path.join(root, "components");
  const plan = JSON.parse(fs.readFileSync(process.env.BLURAY_MACOS_CACHE_PLAN));
  const saved = mode === "save";
  const selected = saved ? JSON.parse(process.env.COMPLETED_COMPONENTS || "{}") : plan.components;
  const restoredFile = path.join(process.env.RUNNER_TEMP, "macos-restored-components.json");
  const restored = saved ? JSON.parse(fs.readFileSync(restoredFile)) : {};
  const verifiedHits = {};
  const entries = Object.entries(selected);
  if (saved) core.info(`Completed native components: ${entries.length}/${Object.keys(plan.components).length}`);
  fs.mkdirSync(directory, {recursive: true});

  async function worker() {
    while (entries.length) {
      const [name, input] = entries.pop();
      if (!/^[a-z0-9._-]+$/.test(name) || !/^[a-f0-9]{64}$/.test(input) || input !== plan.components[name]) {
        throw new Error("Unexpected component in cache plan: " + name);
      }
      const base = path.join(directory, name + "-" + input);
      const files = [base + ".tar.gz", base + ".tar.sha256"];
      const prefix = "bluraysubtitle-macos-v2-" + process.env.RUNNER_ARCH + "-" + name + "-" + input + "-";
      try {
        if (saved) {
          const digest = fs.readFileSync(files[1], "utf8").trim();
          if (!/^[a-f0-9]{64}$/.test(digest)) throw new Error("Invalid archive checksum");
          if (restored[name] === prefix + digest) {
            verifiedHits[name] = restored[name];
          } else {
            const archive = fs.statSync(files[0]);
            if (!archive.isFile() || !archive.size) throw new Error("Missing component archive");
            await cache.saveCache(files, prefix + digest);
          }
        } else {
          // The prefix includes every build input. An older version of this exact
          // component can be restored even after a newer upstream release was built.
          restored[name] = await cache.restoreCache(files, prefix + "lookup", [prefix]) || "";
        }
      } catch (error) {
        core.warning(name + " cache: " + error.message);
      }
    }
  }
  await Promise.all(Array.from({length: 4}, worker));
  if (!saved) {
    fs.writeFileSync(restoredFile, JSON.stringify(restored));
  } else {
    core.setOutput("restored", JSON.stringify(verifiedHits));
  }
};
