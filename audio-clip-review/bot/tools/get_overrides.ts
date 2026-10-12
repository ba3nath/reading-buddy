import { prompt } from "@cursor/bdk";
import { defineTool } from "@cursor/bdk/tools";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { z } from "zod";

import { readingBuddyRoot } from "../lib/readingBuddy.js";

function parseSpokenSpeed(rest: string): { spoken: string; speed: number } | null {
  const m = rest.match(/^("(?:\\.|[^"])*"|'(?:\\.|[^'])*')\s*,\s*([0-9.]+)\s*$/);
  if (!m) return null;
  const spoken = JSON.parse(m[1]!.replaceAll("'", '"')) as string;
  return { spoken, speed: Number(m[2]) };
}

function parseVoiceLang(rest: string): { voice: string; lang: string } | null {
  const m = rest.match(
    /^("(?:\\.|[^"])*"|'(?:\\.|[^'])*')\s*,\s*("(?:\\.|[^"])*"|'(?:\\.|[^'])*')\s*$/,
  );
  if (!m) return null;
  const unquote = (s: string) => JSON.parse(s.replaceAll("'", '"')) as string;
  return { voice: unquote(m[1]!), lang: unquote(m[2]!) };
}

export default defineTool({
  description: prompt`
    Read current Reading Buddy TTS word/voice overrides from app/audio_files.py.
    Useful before/after apply_winners to confirm single-token spoken forms.
  `,
  effect: "read",
  inputSchema: z.object({
    words: z
      .array(z.string())
      .optional()
      .describe("If set, only return these words"),
  }),
  async execute({ words }) {
    const path = resolve(readingBuddyRoot(), "app/audio_files.py");
    const src = readFileSync(path, "utf8");
    const wordBlock = src.match(
      /_TTS_WORD_OVERRIDES: dict\[str, tuple\[str, float\]\] = \{([^}]+)\}/s,
    );
    const voiceBlock = src.match(
      /_TTS_VOICE_OVERRIDES: dict\[str, tuple\[str, str\]\] = \{([^}]+)\}/s,
    );
    const wordOverrides: Record<string, { spoken: string; speed: number }> = {};
    const voiceOverrides: Record<string, { voice: string; lang: string }> = {};
    for (const line of (wordBlock?.[1] ?? "").split("\n")) {
      const m = line.trim().match(/^"(\w+)":\s*\((.+)\),?\s*$/);
      if (!m) continue;
      const parsed = parseSpokenSpeed(m[2]!);
      if (parsed) wordOverrides[m[1]!] = parsed;
    }
    for (const line of (voiceBlock?.[1] ?? "").split("\n")) {
      const m = line.trim().match(/^"(\w+)":\s*\((.+)\),?\s*$/);
      if (!m) continue;
      const parsed = parseVoiceLang(m[2]!);
      if (parsed) voiceOverrides[m[1]!] = parsed;
    }
    const filter = words?.length
      ? new Set(words.map((w) => w.toLowerCase()))
      : null;
    const pick = <T extends Record<string, unknown>>(obj: T): T => {
      if (!filter) return obj;
      return Object.fromEntries(
        Object.entries(obj).filter(([k]) => filter.has(k)),
      ) as T;
    };
    return {
      path,
      wordCount: Object.keys(wordOverrides).length,
      voiceCount: Object.keys(voiceOverrides).length,
      wordOverrides: pick(wordOverrides),
      voiceOverrides: pick(voiceOverrides),
      rules: {
        carriersBanned: true,
        levers: ["punctuation", "speed", "voice"],
        defaultVoice: "bf_isabella",
        postprocess: "loudnorm then adelay/apad",
      },
    };
  },
});
