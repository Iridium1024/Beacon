import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID,
  HEARTBEAT_TERMINAL_PROTOCOL_KIND,
  HEARTBEAT_TERMINAL_PROTOCOL_VERSION,
  decodeHeartbeatTerminalExport,
  parseHeartbeatTerminalProtocolEnvelope,
} from "../src/domain/contracts/heartbeat-terminal-export.js";
import { consumeHeartbeatTerminalEnvelope } from "../src/application/services/heartbeat-terminal-consumer.js";

const currentDir = dirname(fileURLToPath(import.meta.url));
const fixtureDir = resolve(
  currentDir,
  "../../tests/fixtures/heartbeat_terminal_contract",
);

const FIXTURE_CASES = [
  "continue",
  "converged",
  "no_eligible_participants",
  "converged_with_reservations",
  "blocker_driven_continue",
  "forced_non_terminal_continue",
] as const;

type FixtureCaseName = (typeof FIXTURE_CASES)[number];

type FixtureBundle = {
  export: Record<string, unknown>;
  envelope: Record<string, unknown>;
};

const loadFixture = (caseName: FixtureCaseName): FixtureBundle =>
  JSON.parse(
    readFileSync(resolve(fixtureDir, `${caseName}.json`), "utf-8"),
  ) as FixtureBundle;

const cloneJson = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

test("gateway heartbeat terminal consumer parses every golden fixture", async (t) => {
  for (const caseName of FIXTURE_CASES) {
    await t.test(caseName, () => {
      const fixture = loadFixture(caseName);
      const parsedEnvelope = parseHeartbeatTerminalProtocolEnvelope(
        fixture.envelope,
      );
      const decodedPayload = decodeHeartbeatTerminalExport(fixture.envelope);
      const consumedPayload = consumeHeartbeatTerminalEnvelope(fixture.envelope);

      assert.equal(parsedEnvelope.kind, HEARTBEAT_TERMINAL_PROTOCOL_KIND);
      assert.equal(
        parsedEnvelope.protocol_version,
        HEARTBEAT_TERMINAL_PROTOCOL_VERSION,
      );
      assert.equal(parsedEnvelope.payload.schema_id, HEARTBEAT_TERMINAL_EXPORT_SCHEMA_ID);
      assert.deepEqual(parsedEnvelope.payload, fixture.export);
      assert.deepEqual(decodedPayload, fixture.export);
      assert.deepEqual(consumedPayload, fixture.export);
      assert.deepEqual(
        parsedEnvelope.payload.display_sections,
        fixture.export.display_sections,
      );
      assert.deepEqual(
        parsedEnvelope.payload.display_metadata,
        fixture.export.display_metadata,
      );
      assert.deepEqual(
        parsedEnvelope.payload.top_retained_items,
        fixture.export.top_retained_items,
      );
      assert.deepEqual(
        parsedEnvelope.payload.recommended_next_actions,
        fixture.export.recommended_next_actions,
      );
      assert.deepEqual(
        parsedEnvelope.payload.decision_rationale,
        fixture.export.decision_rationale,
      );
    });
  }
});

test("gateway heartbeat terminal consumer rejects invalid protocol envelope headers", () => {
  const fixture = loadFixture("continue");

  const invalidKindEnvelope = cloneJson(fixture.envelope);
  invalidKindEnvelope.kind = "heartbeat.other";
  assert.throws(
    () => parseHeartbeatTerminalProtocolEnvelope(invalidKindEnvelope),
    /ProtocolEnvelope\.kind/,
  );

  const invalidProtocolVersionEnvelope = cloneJson(fixture.envelope);
  invalidProtocolVersionEnvelope.protocol_version = "2.0";
  assert.throws(
    () => parseHeartbeatTerminalProtocolEnvelope(invalidProtocolVersionEnvelope),
    /protocol_version/,
  );
});

test("gateway heartbeat terminal consumer rejects invalid payload location and schema id", () => {
  const fixture = loadFixture("converged");

  const missingPayloadEnvelope = cloneJson(fixture.envelope);
  delete missingPayloadEnvelope.payload;
  missingPayloadEnvelope.body = fixture.export;
  assert.throws(
    () => parseHeartbeatTerminalProtocolEnvelope(missingPayloadEnvelope),
    /payload/,
  );

  const invalidSchemaEnvelope = cloneJson(fixture.envelope);
  (
    invalidSchemaEnvelope.payload as { schema_id: string }
  ).schema_id = "heartbeat_terminal_export_v2";
  assert.throws(
    () => parseHeartbeatTerminalProtocolEnvelope(invalidSchemaEnvelope),
    /schema_id/,
  );
});

test("gateway heartbeat terminal consumer rejects missing required payload fields", () => {
  const fixture = loadFixture("blocker_driven_continue");
  const missingCandidateEnvelope = cloneJson(fixture.envelope);
  delete (missingCandidateEnvelope.payload as Record<string, unknown>).candidate;
  assert.throws(
    () => parseHeartbeatTerminalProtocolEnvelope(missingCandidateEnvelope),
    /candidate/,
  );
});
