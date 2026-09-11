import Schema from "@deepseek-ai/schemastery";
import { JsonRpcLineTransport } from "@deepseek-ai/dsh-sdk-protocol";
import { SessionId } from "@deepseek-ai/dsh-session";
import { HarnessSdkJsonRpcServer } from "@deepseek-ai/dsh-sdk-jsonrpc-server";

export const name = "beacon-sdk-jsonrpc-server";
export const inject = ["agents", "sessionPersistence"];
export const Config = Schema.object({
  maxTokensAsSuccess: Schema.boolean().default(false),
});

function requiredEnvironment(name) {
  const value = process.env[name];
  if (typeof value !== "string" || value.length === 0 || value.includes("\0")) {
    throw new Error(`${name} must be non-empty text without null bytes`);
  }
  return value;
}

class BeaconHarnessSdkJsonRpcServer extends HarnessSdkJsonRpcServer {
  constructor(ctx, transport, options) {
    super(ctx, transport, options);
    this.beaconSessionId = requiredEnvironment("DSH_SESSION_ID");
    this.beaconSessionStartMode = requiredEnvironment("DSH_SESSION_START_MODE");
    if (!new Set(["create", "resume"]).has(this.beaconSessionStartMode)) {
      throw new Error("DSH_SESSION_START_MODE must be create or resume");
    }
  }

  async initialize(params) {
    const result = await super.initialize(params);
    // The upstream SDK server creates lazily on the first prompt. Beacon opens
    // during initialize so an unknown/corrupt resume fails before it publishes
    // an Agent, handle, or endpoint in the platform registry.
    await this.getOrCreateSession(this.beaconSessionId);
    return result;
  }

  async createSession(sessionId) {
    if (sessionId !== this.beaconSessionId) {
      throw new Error(
        `SDK prompt sessionId does not match the launcher-owned identity: ${sessionId}`,
      );
    }
    if (this.beaconSessionStartMode === "create") {
      return super.createSession(sessionId);
    }
    const rec = {
      handle: await this.ctx.agents.resume({
        resumeSessionId: SessionId(sessionId),
        agentOptions: {
          provider: this.provider,
          model: this.model,
          ...(this.maxTokens === undefined ? {} : { maxTokens: this.maxTokens }),
        },
      }),
    };
    this.sessions.set(sessionId, rec);
    return rec;
  }
}

export function apply(ctx, config) {
  const rootFiber = ctx.root.fiber;
  const input = config.input ?? process.stdin;
  const output = config.output ?? process.stdout;
  const exit = config.exit ?? ((code) => process.exit(code));
  const transport = new JsonRpcLineTransport(input, output);
  const server = new BeaconHarnessSdkJsonRpcServer(ctx, transport, {
    maxTokensAsSuccess: config.maxTokensAsSuccess,
  });
  let exitTask;
  const disposeAndExit = () => {
    exitTask ??= (async () => {
      await Promise.allSettled([Promise.resolve().then(() => transport.flush())]);
      await Promise.allSettled([Promise.resolve().then(() => rootFiber.dispose())]);
      exit(0);
    })();
    return exitTask;
  };
  transport.onRequest(async (method, params) => {
    if (method === "initialize") await ctx.get("loader")?.await();
    const result = await server.handleRequest(method, params);
    if (method === "shutdown") setImmediate(disposeAndExit);
    return result;
  });
  ctx.effect(() => {
    transport.start();
    return async () => {
      await server.shutdown();
      transport.close();
    };
  }, "beacon-jsonrpc.serve");
}
