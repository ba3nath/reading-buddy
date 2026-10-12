import { prompt } from "@cursor/bdk";
import { defineTool } from "@cursor/bdk/tools";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

const here = dirname(fileURLToPath(import.meta.url));
const checkPy = resolve(here, "../../check.py");

function runCheck(phase: string): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolvePromise, reject) => {
    const child = spawn("python3", [checkPy, "--phase", phase], {
      cwd: resolve(here, "../.."),
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      resolvePromise({ code: code ?? 1, stdout, stderr });
    });
  });
}

export default defineTool({
  description: prompt`
    Run the Design consistency gate for one phase.
    Phase is 1, 2, fluency, 3, or 4.
    A non-empty failures list fails the gate.
  `,
  effect: "read",
  inputSchema: z.object({
    phase: z.enum(["1", "2", "fluency", "3", "4"]),
  }),
  async execute({ phase }) {
    const result = await runCheck(phase);
    let report: unknown = null;
    try {
      report = JSON.parse(result.stdout);
    } catch {
      report = null;
    }
    return {
      exitCode: result.code,
      report,
      stderr: result.stderr,
    };
  },
});
