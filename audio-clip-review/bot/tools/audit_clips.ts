import { prompt } from "@cursor/bdk";
import { defineTool } from "@cursor/bdk/tools";
import { readFileSync } from "node:fs";
import { z } from "zod";

import {
  parseJsonObject,
  runReview,
  summarizeRun,
  type Json,
} from "../lib/readingBuddy.js";

type AuditRow = { word?: string };

function wordsFrom(bucket: Json | undefined): string[] {
  if (!Array.isArray(bucket)) return [];
  return bucket
    .map((row) =>
      row && typeof row === "object" && !Array.isArray(row)
        ? String((row as AuditRow).word ?? "")
        : "",
    )
    .filter(Boolean);
}

export default defineTool({
  description: prompt`
    Whisper-audit Reading Buddy listen word clips (float32 ndarray path).
    Classifies each word OK (hits>=2/3), weak (1/3), or fail (0/3).
    Use before proposing TTS retunes. Never invent carriers.
  `,
  effect: "read",
  inputSchema: z.object({
    words: z
      .array(z.string())
      .optional()
      .describe("Optional subset of words; default = all kind=word items"),
    passes: z.number().int().min(1).max(5).optional().default(3),
    outPath: z
      .string()
      .optional()
      .default("/tmp/audio_audit.json")
      .describe("Where to write the audit JSON"),
  }),
  async execute({ words, passes, outPath }) {
    const args = ["audit", "--passes", String(passes), "--out", outPath];
    if (words?.length) args.push("--words", ...words);
    const result = await runReview(args);
    let summary: Json = null;
    try {
      summary = parseJsonObject(readFileSync(outPath, "utf8"));
    } catch {
      summary = null;
    }
    const obj =
      summary && typeof summary === "object" && !Array.isArray(summary)
        ? summary
        : null;
    return {
      ...summarizeRun(result),
      outPath,
      counts: obj
        ? {
            ok: Number(obj.ok_count ?? 0),
            weak: Number(obj.weak_count ?? 0),
            fail: Number(obj.fail_count ?? 0),
            total: Number(obj.total ?? 0),
          }
        : null,
      failWords: wordsFrom(obj?.fail),
      weakWords: wordsFrom(obj?.weak),
    };
  },
});
