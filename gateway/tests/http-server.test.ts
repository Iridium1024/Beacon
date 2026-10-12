import assert from "node:assert/strict";
import { Server as HttpServer } from "node:http";
import test from "node:test";

import { createHttpServer } from "../src/infrastructure/http/server.js";

test("Gateway creates the default HTTP/1.1 Fastify server", () => {
  const gateway = createHttpServer("127.0.0.1", 0);

  assert.ok(gateway.raw().server instanceof HttpServer);
  assert.equal(gateway.raw().server.constructor.name, "Server");
});
