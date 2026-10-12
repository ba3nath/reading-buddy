import { prompt } from "@cursor/bdk";
import { defineTool } from "@cursor/bdk/tools";
import { z } from "zod";

import {
  parseJsonObject,
  runReview,
  summarizeRun,
  type Json,
} from "../lib/readingBuddy.js";

export default defineTool({
  description: prompt`
    Force-regenerate Kokoro wavs for given words or a winners JSON file.
    Uses current tts_render / tts_voice overrides (loudnorm then pads).
  `,
  effect: "write",
  inputSchema: z.object({
    winnersPath: z.string().optional(),
    words: z.array(z.string()).optional(),
  }),
  async execute({ winnersPath, words }) {
    const args = ["regen"];
    if (words?.length) args.push("--words", ...words);
    else if (winnersPath) args.push("--winners", winnersPath);
    else args.push("--winners", "/tmp/audio_winners.json");
    const result = await runReview(args, { timeoutMs: 60 * 60 * 1000 });
    let parsed: Json = null;
    try {
      const start = result.stdout.lastIndexOf("{");
      if (start >= 0) parsed = parseJsonObject(result.stdout.slice(start));
    } catch {
      parsed = null;
    }
    return { ...summarizeRun(result), result: parsed };
  },
});
