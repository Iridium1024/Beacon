import { LlmAdapter } from "@deepseek-ai/dsh-llm";
import { createHash } from "node:crypto";

export const name = "beacon-offline-fake-llm";
export const inject = ["llm"];

class OfflineFakeAdapter extends LlmAdapter {
  async *stream(options) {
    const history = options.messages.map((message) => ({
      role: message.role,
      text: message.content
        .filter((block) => block.type === "text")
        .map((block) => block.text)
        .join(""),
    }));
    const historyEvidence = history.map((message) => ({
      role: message.role,
      markers: [...new Set(message.text.match(/OFFICIAL_[A-Z0-9_]+/g) ?? [])],
      textSha256: createHash("sha256").update(message.text).digest("hex"),
      textLength: message.text.length,
    }));
    const text = JSON.stringify({
      provider: options.provider,
      model: options.model,
      history: historyEvidence,
    });
    const block = { type: "text", text };
    yield { type: "block-start", index: 0, blockType: "text" };
    yield { type: "text-delta", index: 0, text };
    yield { type: "block-end", index: 0, block };
    yield {
      type: "usage",
      usage: { inputTokens: history.length, outputTokens: 1 },
    };
    yield { type: "finish", reason: { kind: "stop" } };
  }
}

export function apply(ctx) {
  return ctx.llm.registerAdapter(["beacon-offline"], new OfflineFakeAdapter());
}
