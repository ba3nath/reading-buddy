import { defineEval, includes } from "@cursor/bdk/evals";

export default defineEval({
  tags: ["smoke"],
  cases: [
    {
      id: "phase-1-gate",
      description: "Runs the phase 1 Code review check and reports pass or failures.",
      async test(t) {
        await t.send("Run the phase 1 gate. Use tools. List any failures.");
        t.succeeded();
        t.calledTool("run_phase_check");
        t.check(t.reply, includes(/phase|pass|fail/i));
      },
    },
  ],
});
