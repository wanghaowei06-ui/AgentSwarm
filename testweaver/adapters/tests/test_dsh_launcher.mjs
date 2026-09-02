import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { launch, projectProfile } from "../dsh-launcher.mjs";

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "testweaver-dsh-launcher-"));
  const home = path.join(root, "home");
  const runtimeRoot = path.join(root, "runtime");
  const forest = path.join(runtimeRoot, "node_modules", ".pnpm", "node_modules");
  fs.mkdirSync(home);
  fs.mkdirSync(forest, { recursive: true });
  const entrypoint = path.join(
    runtimeRoot,
    "node_modules",
    "@deepseek-ai",
    "dsh",
    "lib",
    "bin.js",
  );
  fs.mkdirSync(path.dirname(entrypoint), { recursive: true });
  fs.writeFileSync(entrypoint, "", "utf8");
  return { root, home, runtimeRoot, forest };
}

function writePackage(root, packageName, manifest, files = {}) {
  const packageDir = path.join(root, "node_modules", ...packageName.split("/"));
  fs.mkdirSync(packageDir, { recursive: true });
  fs.writeFileSync(path.join(packageDir, "package.json"), JSON.stringify(manifest), "utf8");
  for (const [relativePath, contents] of Object.entries(files)) {
    const file = path.join(packageDir, relativePath);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, contents, "utf8");
  }
  return packageDir;
}

test("projects a profile node_modules symlink to the fixed forest", () => {
  const paths = fixture();
  try {
    const projection = projectProfile({
      home: paths.home,
      profile: "headless",
      forest: paths.forest,
    });
    const link = path.join(paths.home, ".dsh", "profiles", "headless", "node_modules");
    assert.equal(projection.nodeModules, link);
    assert.equal(fs.readlinkSync(link), paths.forest);
  } finally {
    fs.rmSync(paths.root, { recursive: true, force: true });
  }
});

test("accepts an exact existing projection without replacing it", () => {
  const paths = fixture();
  try {
    const first = projectProfile({ home: paths.home, profile: "headless", forest: paths.forest });
    const second = projectProfile({ home: paths.home, profile: "headless", forest: paths.forest });
    assert.equal(second.nodeModules, first.nodeModules);
    assert.equal(fs.readlinkSync(second.nodeModules), paths.forest);
  } finally {
    fs.rmSync(paths.root, { recursive: true, force: true });
  }
});

test("rejects a conflicting existing projection", () => {
  const paths = fixture();
  try {
    const profileDir = path.join(paths.home, ".dsh", "profiles", "headless");
    fs.mkdirSync(profileDir, { recursive: true });
    fs.mkdirSync(path.join(profileDir, "node_modules"));
    assert.throws(
      () => projectProfile({ home: paths.home, profile: "headless", forest: paths.forest }),
      /node_modules/,
    );
  } finally {
    fs.rmSync(paths.root, { recursive: true, force: true });
  }
});

test("rejects a non-identical existing symlink", () => {
  const paths = fixture();
  try {
    const profileDir = path.join(paths.home, ".dsh", "profiles", "headless");
    const otherForest = path.join(paths.root, "other-forest");
    fs.mkdirSync(profileDir, { recursive: true });
    fs.mkdirSync(otherForest);
    const link = path.join(profileDir, "node_modules");
    fs.symlinkSync(otherForest, link, "dir");
    assert.throws(
      () => projectProfile({ home: paths.home, profile: "headless", forest: paths.forest }),
      /node_modules/,
    );
    assert.equal(fs.readlinkSync(link), otherForest);
  } finally {
    fs.rmSync(paths.root, { recursive: true, force: true });
  }
});

test("rejects unsafe HOME and profile values", () => {
  const paths = fixture();
  try {
    assert.throws(
      () => projectProfile({ home: "relative-home", profile: "headless", forest: paths.forest }),
      /HOME/,
    );
    assert.throws(
      () => projectProfile({ home: paths.home, profile: "../escape", forest: paths.forest }),
      /profile/,
    );
    const homeFile = path.join(paths.root, "home-file");
    fs.writeFileSync(homeFile, "", "utf8");
    assert.throws(
      () => projectProfile({ home: homeFile, profile: "headless", forest: paths.forest }),
      /HOME/,
    );
  } finally {
    fs.rmSync(paths.root, { recursive: true, force: true });
  }
});

test("projects the runtime root before spawning DSH", () => {
  const paths = fixture();
  try {
    let spawnArgs;
    const status = launch({
      args: ["--profile", "headless", "--", "probe"],
      env: { HOME: paths.home },
      runtimeRoot: paths.runtimeRoot,
      spawn: (...args) => {
        spawnArgs = args;
        return { status: 0 };
      },
    });
    assert.equal(status, 0);
    assert.equal(
      fs.readlinkSync(path.join(paths.home, ".dsh", "profiles", "headless", "node_modules")),
      path.join(paths.runtimeRoot, "node_modules"),
    );
    assert.equal(spawnArgs[0], "/opt/agentteams/testweaver-native-worker/bin/node");
    assert.deepEqual(spawnArgs[1].slice(1, 3), ["--profile", "headless"]);
  } finally {
    fs.rmSync(paths.root, { recursive: true, force: true });
  }
});

test("boots a bare package through the Node cascaded loader from the profile anchor", () => {
  const paths = fixture();
  try {
    const rootModules = path.join(paths.runtimeRoot, "node_modules");
    writePackage(paths.runtimeRoot, "@deepseek-ai/dsh", {
      name: "@deepseek-ai/dsh",
      type: "module",
      main: "lib/bin.js",
    }, {
      "lib/bin.js": `
        import { createRequire } from "node:module";
        import { pathToFileURL } from "node:url";
        const require = createRequire(import.meta.url);
        const loader = require("internal/modules/esm/loader").getOrInitializeCascadedLoader();
        const loaded = await loader.import("@fixture/loader", pathToFileURL(process.cwd() + "/cordis.yml").href, {});
        if (loaded.marker !== "root") process.exitCode = 7;
      `,
    });
    writePackage(paths.runtimeRoot, "@fixture/loader", {
      name: "@fixture/loader",
      type: "module",
      exports: { ".": "./lib/index.js" },
    }, {
      "lib/index.js": 'import { marker as nested } from "@fixture/transitive"; if (nested !== "ok") throw new Error("bad marker"); export const marker = "root";',
    });
    writePackage(paths.runtimeRoot, "@fixture/transitive", {
      name: "@fixture/transitive",
      type: "module",
      exports: { ".": "./lib/index.js" },
    }, {
      "lib/index.js": 'export const marker = "ok";',
    });

    // The old .pnpm forest contains the package manifest but not its declared entry.
    // This models a collected package instance that exists yet cannot boot through Cordis.
    const forestLoader = path.join(paths.forest, "@fixture", "loader");
    fs.mkdirSync(forestLoader, { recursive: true });
    fs.writeFileSync(
      path.join(forestLoader, "package.json"),
      JSON.stringify({ name: "@fixture/loader", type: "module", exports: { ".": "./lib/index.js" } }),
      "utf8",
    );
    fs.mkdirSync(path.join(forestLoader, "lib"), { recursive: true });
    fs.writeFileSync(path.join(forestLoader, "lib/index.js"), 'export const marker = "forest";', "utf8");

    let spawnArgs;
    const profileDir = path.join(paths.home, ".dsh", "profiles", "headless");
    const status = launch({
      args: ["--profile", "headless", "--", "probe"],
      env: { HOME: paths.home },
      runtimeRoot: paths.runtimeRoot,
      spawn: (executable, childArgs) => {
        spawnArgs = [executable, childArgs];
        const child = spawnSync(process.execPath, ["--expose-internals", ...childArgs], {
          cwd: profileDir,
          env: { ...process.env, HOME: paths.home },
          stdio: "ignore",
        });
        return { status: child.status, error: child.error };
      },
    });

    assert.equal(status, 0);
    assert.equal(
      fs.readlinkSync(path.join(profileDir, "node_modules")),
      rootModules,
    );
    assert.equal(spawnArgs[0], "/opt/agentteams/testweaver-native-worker/bin/node");
  } finally {
    fs.rmSync(paths.root, { recursive: true, force: true });
  }
});
