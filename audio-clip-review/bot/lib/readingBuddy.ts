import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

/** JSON-shaped tool results (BDK rejects `interface` / `unknown`). */
export type Json =
  | string
  | number
  | boolean
  | null
  | Json[]
  | { [key: string]: Json };

export function parseJsonObject(text: string): Json {
  return JSON.parse(text) as Json;
}

/** Reading Buddy repo root (parent of this agent project by default). */
export function readingBuddyRoot(): string {
  const fromEnv = process.env.READING_BUDDY_ROOT?.trim();
  if (fromEnv) return resolve(fromEnv);
  return resolve(HERE, "../../..");
}

export function reviewScript(): string {
  return resolve(readingBuddyRoot(), "scripts/review_audio_clips.py");
}

function pythonBin(cwd: string): string {
  const venv = resolve(cwd, ".venv/bin/python");
  if (existsSync(venv)) return venv;
  // Prefer python3 on hosts without a `python` shim.
  return "python3";
}

export type RunResult = {
  ok: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  command: string[];
  cwd: string;
};

export async function runReview(
  args: string[],
  opts: { timeoutMs?: number } = {},
): Promise<RunResult> {
  const cwd = readingBuddyRoot();
  const script = reviewScript();
  const py = pythonBin(cwd);
  if (!existsSync(script)) {
    return {
      ok: false,
      exitCode: 127,
      stdout: "",
      stderr: `review script missing: ${script}`,
      command: [py, script, ...args],
      cwd,
    };
  }
  const command = [py, script, ...args];
  const timeoutMs = opts.timeoutMs ?? 30 * 60 * 1000;

  return await new Promise((resolvePromise) => {
    const child = spawn(command[0]!, command.slice(1), {
      cwd,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      stderr += `\n[timeout after ${timeoutMs}ms]`;
    }, timeoutMs);
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      const exitCode = code ?? 1;
      resolvePromise({
        ok: exitCode === 0,
        exitCode,
        stdout,
        stderr,
        command,
        cwd,
      });
    });
  });
}

export function summarizeRun(result: RunResult): {
  ok: boolean;
  exitCode: number;
  command: string[];
  cwd: string;
  stdoutTail: string;
  stderrTail: string;
  stdout: string;
  stderr: string;
} {
  const tail = (s: string, n = 4000) =>
    s.length <= n ? s : `…${s.slice(-n)}`;
  return {
    ok: result.ok,
    exitCode: result.exitCode,
    command: result.command,
    cwd: result.cwd,
    stdoutTail: tail(result.stdout),
    stderrTail: tail(result.stderr),
    stdout: result.stdout,
    stderr: result.stderr,
  };
}
