#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const RUNTIME_ROOT = "/opt/agentteams/testweaver-native-worker/dsh-runtime";
const PROFILE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const MAX_PROFILE_LENGTH = 128;

function fail(message) {
  throw new Error(message);
}

function validateProfile(profile) {
  if (
    typeof profile !== "string" ||
    profile.length === 0 ||
    profile.length > MAX_PROFILE_LENGTH ||
    !PROFILE_PATTERN.test(profile)
  ) {
    fail("unsafe profile name");
  }
  return profile;
}

export function profileFromArgs(args) {
  if (!Array.isArray(args)) {
    fail("argv must be an array");
  }
  const delimiter = args.indexOf("--");
  const options = delimiter === -1 ? args : args.slice(0, delimiter);
  const profileIndexes = options.reduce((indexes, value, index) => {
    if (value === "--profile") indexes.push(index);
    return indexes;
  }, []);
  if (profileIndexes.length !== 1) {
    fail("exactly one --profile is required");
  }
  return validateProfile(options[profileIndexes[0] + 1]);
}

function ensureDirectory(directory, label) {
  let stat;
  try {
    stat = fs.lstatSync(directory);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    try {
      fs.mkdirSync(directory, { mode: 0o700 });
    } catch (createError) {
      if (createError?.code !== "EEXIST") throw createError;
    }
    stat = fs.lstatSync(directory);
  }
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    fail(`${label} must be a real directory`);
  }
}

function ensureHome(home) {
  if (typeof home !== "string" || !path.isAbsolute(home)) {
    fail("HOME must be an absolute directory");
  }
  let stat;
  try {
    stat = fs.lstatSync(home);
  } catch {
    fail("HOME must be an absolute directory");
  }
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    fail("HOME must be an absolute directory");
  }
  return path.resolve(home);
}

function ensureForest(forest) {
  if (typeof forest !== "string" || !path.isAbsolute(forest)) {
    fail("fixed DSH module forest must be absolute");
  }
  let stat;
  try {
    stat = fs.lstatSync(forest);
  } catch {
    fail("fixed DSH module forest is unavailable");
  }
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    fail("fixed DSH module forest is invalid");
  }
  return path.resolve(forest);
}

function ensureProjection(link, forest) {
  let stat;
  try {
    stat = fs.lstatSync(link);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    try {
      fs.symlinkSync(forest, link, "dir");
    } catch (createError) {
      if (createError?.code !== "EEXIST") throw createError;
      stat = fs.lstatSync(link);
    }
  }
  if (!stat) return;
  if (!stat.isSymbolicLink() || fs.readlinkSync(link) !== forest) {
    fail("profile node_modules projection conflicts with existing path");
  }
}

export function projectProfile({ home, profile, forest }) {
  const safeHome = ensureHome(home);
  const safeProfile = validateProfile(profile);
  const safeForest = ensureForest(forest);
  const dshDir = path.join(safeHome, ".dsh");
  const profilesDir = path.join(dshDir, "profiles");
  const profileDir = path.join(profilesDir, safeProfile);
  const nodeModules = path.join(profileDir, "node_modules");

  ensureDirectory(dshDir, "$HOME/.dsh");
  ensureDirectory(profilesDir, "$HOME/.dsh/profiles");
  ensureDirectory(profileDir, "profile");
  ensureProjection(nodeModules, safeForest);
  return { profileDir, nodeModules, forest: safeForest };
}

export function launch({
  args = process.argv.slice(2),
  env = process.env,
  runtimeRoot = RUNTIME_ROOT,
  spawn = spawnSync,
} = {}) {
  const profile = profileFromArgs(args);
  const root = path.resolve(runtimeRoot);
  const forest = path.join(root, "node_modules", ".pnpm", "node_modules");
  projectProfile({ home: env?.HOME, profile, forest });

  const require = createRequire(import.meta.url);
  const entrypoint = require.resolve("@deepseek-ai/dsh/lib/bin.js", {
    paths: [root],
  });
  const child = spawn(process.execPath, [entrypoint, ...args], {
    stdio: "inherit",
  });
  if (child.error) {
    throw child.error;
  }
  return child.status ?? 1;
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) {
  try {
    process.exitCode = launch();
  } catch {
    process.stderr.write("dsh: profile setup or launch failed\n");
    process.exitCode = 1;
  }
}
