#!/usr/bin/env node
import { Context } from "@deepseek-ai/cordis";
import SessionStore from "@deepseek-ai/dsh-session";
import JsonlSessionPersistence from "@deepseek-ai/dsh-session-persistence-jsonl";

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error("usage: session-probe --root <path> --session <id> --compression <zstd|none>");
    }
    values[key.slice(2)] = value;
  }
  return values;
}

const root = new Context();
try {
  const args = parseArgs(process.argv.slice(2));
  if (!args.root || !args.session) throw new Error("root and session are required");
  if (!new Set(["zstd", "none"]).has(args.compression)) {
    throw new Error("compression must be zstd or none");
  }
  await root.plugin(SessionStore, {});
  await root.plugin(JsonlSessionPersistence, {
    root: args.root,
    compression: args.compression,
  });
  const headers = await root.sessionPersistence.list();
  const matches = headers.filter((header) => String(header.id) === args.session);
  const session = matches.length === 1 ? matches[0] : undefined;
  process.stdout.write(`${JSON.stringify({
    schema: "deepseek_harness_session_probe.v1",
    ok: matches.length === 1,
    found: matches.length === 1,
    failureCategory:
      matches.length === 0
        ? "session_not_found"
        : matches.length > 1
          ? "session_identity_ambiguous"
          : null,
    session: session
      ? {
          id: String(session.id),
          version: session.version,
          cwd: session.cwd,
          createdAt: session.createdAt,
          parentSession:
            session.parentSession === undefined ? null : String(session.parentSession),
        }
      : null,
    headerCount: headers.length,
    fullSessionHistoryRead: false,
  })}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify({
    schema: "deepseek_harness_session_probe.v1",
    ok: false,
    found: false,
    failureCategory: "session_store_incompatible_or_unreadable",
    failureReason: error instanceof Error ? `${error.name}: ${error.message}` : String(error),
    fullSessionHistoryRead: false,
  })}\n`);
  process.exitCode = 2;
} finally {
  await root.fiber.dispose();
}
