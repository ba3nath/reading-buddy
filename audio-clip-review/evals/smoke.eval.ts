import { defineEval, includes } from "@cursor/bdk/evals";

export default defineEval({
  tags: ["smoke"],
  cases: [
    {
      id: "overrides-read",
      description: "Reads current TTS overrides via get_overrides.",
      async test(t) {
        await t.send(
          "Show me the current TTS overrides for cat and pen. Use tools.",
        );
        t.succeeded();
        t.calledTool("get_overrides");
        t.notCalledTool("apply_winners");
        t.check(t.reply, includes(/cat|pen|override/i));
      },
    },
  ],
});
