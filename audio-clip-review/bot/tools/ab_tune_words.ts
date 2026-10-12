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

export default defineTool({
  description: prompt`
    Single-token A/B retune for weak/fail listen words.
    Tries punctuation × speed × voice (emma/alice/isabella/lewis).
    NEVER adds carrier words — spoken text must be only the on-screen token.
    Writes winners JSON for apply_winners / regen_clips.
  `,
  effect: "read",
  inputSchema: z.object({
    auditPath: z
      .string()
      .optional()
      .describe("Audit JSON from audit_clips (uses fail+weak)"),
    words: z
      .array(z.string())
      .optional()
      .describe("Explicit word list (overrides auditPath targets)"),
    passes: z.number().int().min(1).max(5).optional().default(3),
    outPath: z
      .string()
      .optional()
      .default("/tmp/audio_winners.json"),
  }),
  async execute({ auditPath, words, passes, outPath }) {
    const args = ["ab-tune", "--passes", String(passes), "--out", outPath];
    if (words?.length) {
      args.push("--words", ...words);
    } else if (auditPath) {
      args.push("--audit", auditPath);
    } else {
      args.push("--audit", "/tmp/audio_audit.json");
    }
    const result = await runReview(args, { timeoutMs: 120 * 60 * 1000 });
    let winners: Json = null;
    try {
      winners = parseJsonObject(readFileSync(outPath, "utf8"));
    } catch {
      winners = null;
    }
    const obj =
      winners && typeof winners === "object" && !Array.isArray(winners)
        ? winners
        : null;
    const entries = obj ? Object.entries(obj) : [];
    const slim: { [key: string]: Json } = {};
    let ge2 = 0;
    for (const [word, value] of entries) {
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      const hits = Number(value.hits ?? 0);
      if (hits >= 2) ge2 += 1;
      slim[word] = {
        spoken: String(value.spoken ?? ""),
        speed: Number(value.speed ?? 0),
        voice: String(value.voice ?? ""),
        hits,
        filler: Number(value.filler ?? 0),
      };
    }
    return {
      ...summarizeRun(result),
      outPath,
      winnerCount: entries.length,
      winnersAtLeast2: ge2,
      winners: obj ? slim : null,
    };
  },
});
