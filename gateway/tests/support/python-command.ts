import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export interface PythonCommand {
  command: string;
  args: string[];
}

export const findPythonCommand = (): PythonCommand => {
  const candidates = candidatePythonCommands();
  for (const candidate of candidates) {
    const probe = spawnSync(candidate.command, [...candidate.args, "--version"], {
      encoding: "utf8",
      windowsHide: true,
    });
    if (probe.status === 0) {
      return candidate;
    }
  }
  throw new Error("No usable Python command found for local platform bridge tests.");
};

const candidatePythonCommands = (): PythonCommand[] => {
  const candidates: PythonCommand[] = [];
  const explicitCommand =
    process.env.LOCAL_PLATFORM_TEST_PYTHON_COMMAND ?? process.env.LOCAL_PLATFORM_PYTHON_COMMAND;
  if (explicitCommand !== undefined && explicitCommand.trim() !== "") {
    candidates.push({
      command: explicitCommand.trim(),
      args: parseArgs(
        process.env.LOCAL_PLATFORM_TEST_PYTHON_ARGS ?? process.env.LOCAL_PLATFORM_PYTHON_ARGS,
      ),
    });
  }

  const bundledPython = join(
    homedir(),
    ".cache",
    "codex-runtimes",
    "codex-primary-runtime",
    "dependencies",
    "python",
    "python.exe",
  );
  if (existsSync(bundledPython)) {
    candidates.push({ command: bundledPython, args: [] });
  }

  candidates.push({ command: "python", args: [] });
  candidates.push({ command: "py", args: ["-3"] });
  return candidates;
};

const parseArgs = (value: string | undefined): string[] => {
  if (value === undefined || value.trim() === "") {
    return [];
  }
  return value.trim().split(/\s+/u);
};
