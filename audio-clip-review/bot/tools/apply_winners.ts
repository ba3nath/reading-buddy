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
    Merge A/B winners into Reading Buddy app/audio_files.py TTS overrides.
    Defaults to dry-run preview. Set write=true only after the user confirms.
    Refuses any multi-word spoken text (carrier ban).
  `,
  effect: "write",
  inputSchema: z.object({
    winnersPath: z.string().default("/tmp/audio_winners.json"),
    write: z
      .boolean()
      .optional()
      .default(false)
      .describe("Actually write audio_files.py (default false = dry-run)"),
  }),
  async execute({ winnersPath, write }) {
    const args = ["apply-winners", "--winners", winnersPath];
    if (write) args.push("--write");
    else args.push("--dry-run");
    const result = await runReview(args);
    let parsed: Json = null;
    try {
      const start = result.stdout.indexOf("{");
      if (start >= 0) parsed = parseJsonObject(result.stdout.slice(start));
    } catch {
      parsed = null;
    }
    return { ...summarizeRun(result), result: parsed };
  },
});
