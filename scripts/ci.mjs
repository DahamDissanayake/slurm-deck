// Launches scripts/ci.sh with a POSIX bash. `serenedge ci` runs commands
// through cmd.exe on Windows, where `bash` resolves to WSL rather than Git
// Bash, so this finds Git's bash there and uses plain bash everywhere else.
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

function findBash() {
  if (process.platform !== "win32") return "bash";
  // git --exec-path is <git>/mingw64/libexec/git-core; bash is <git>/bin/bash.exe.
  const execPath = execFileSync("git", ["--exec-path"], { encoding: "utf8" }).trim();
  const bash = resolve(execPath, "..", "..", "..", "bin", "bash.exe");
  if (!existsSync(bash)) {
    console.error(`Git Bash not found at ${bash}`);
    process.exit(1);
  }
  return bash;
}

const script = join(dirname(fileURLToPath(import.meta.url)), "ci.sh");
const run = spawnSync(findBash(), [script], { stdio: "inherit" });
process.exit(run.status ?? 1);
