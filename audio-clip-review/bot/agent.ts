import { defineAgent } from "@cursor/bdk";
import { resolve } from "node:path";

// Keep harness workspaces outside the Reading Buddy checkout; tools
// resolve the app via READING_BUDDY_ROOT / parent of this agent project.
const cacheCwd = resolve(
  process.env.HOME ?? "/tmp",
  ".cache/audio-clip-review-workspaces",
);

export default defineAgent({
  model: {
    id: "grok-4.5",
    params: [
      { id: "effort", value: "high" },
      { id: "fast", value: "true" },
    ],
  },
  local: {
    cwd: cacheCwd,
  },
});
