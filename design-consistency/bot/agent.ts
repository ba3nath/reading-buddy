import { defineAgent } from "@cursor/bdk";
import { resolve } from "node:path";

const cacheCwd = resolve(
  process.env.HOME ?? "/tmp",
  ".cache/design-consistency-workspaces",
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
