import { readFile } from "node:fs/promises";
import type { IncomingMessage, ServerResponse } from "node:http";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const fixturePath = fileURLToPath(new URL("./fixtures/console-demo.json", import.meta.url));
const prefix = "/beacon-console/api";

export default defineConfig({
  plugins: [react(), fakeProjectionPlugin()],
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  server: {
    host: "127.0.0.1",
    port: 4178,
    strictPort: true,
  },
});

function fakeProjectionPlugin(): Plugin {
  return {
    name: "beacon-console-fake-projection",
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const url = new URL(request.url ?? "/", "http://127.0.0.1");
        if (!url.pathname.startsWith(prefix)) {
          next();
          return;
        }
        if (request.method !== "GET" && request.method !== "HEAD") {
          writeJson(response, 405, {
            schema: "beacon.console.error.v1",
            readOnly: true,
            error: { code: "method_not_allowed", message: "Only GET and HEAD are available." },
          }, request);
          return;
        }
        try {
          const fixture = JSON.parse(await readFile(fixturePath, "utf8")) as DemoFixture;
          const suffix = url.pathname.slice(prefix.length);
          let payload: object | undefined;
          if (suffix === "/workspaces") {
            payload = fixture.workspaces;
          } else if (suffix === "/provider-backends") {
            payload = fixture.providerBackends;
          } else if (suffix.startsWith("/workspaces/")) {
            const id = decodeURIComponent(suffix.slice("/workspaces/".length));
            const view = fixture.workspaceViews[id];
            payload = view === undefined
              ? undefined
              : {
                  ...pageView(view, url.searchParams),
                  providerBackends: asRecord(fixture.providerBackends).items ?? [],
                };
          }
          if (payload === undefined) {
            writeJson(response, 404, {
              schema: "beacon.console.error.v1",
              readOnly: true,
              error: { code: "not_found", message: "Projection route not found." },
            }, request);
            return;
          }
          writeJson(response, 200, payload, request);
        } catch {
          writeJson(response, 500, {
            schema: "beacon.console.error.v1",
            readOnly: true,
            error: { code: "fixture_failed", message: "Fake projection failed." },
          }, request);
        }
      });
    },
  };
}

interface DemoFixture {
  workspaces: object;
  providerBackends: object;
  workspaceViews: Record<string, Record<string, unknown>>;
}

const pageView = (
  view: Record<string, unknown>,
  params: URLSearchParams,
): object => {
  const timeline = asRecord(view.timeline);
  const events = Array.isArray(timeline.events) ? timeline.events : [];
  const match = /^ord:(\d+)$/u.exec(params.get("cursor") ?? "ord:0");
  const cursor = Number(match?.[1] ?? "0");
  const limit = Math.min(200, Math.max(1, Number(params.get("limit") ?? "50")));
  const outOfRange = cursor > events.length;
  const start = outOfRange ? 0 : cursor;
  const page = events.slice(start, start + limit);
  return {
    ...view,
    timeline: {
      ...timeline,
      events: page,
      page: {
        cursor: params.get("cursor"),
        nextCursor: `ord:${start + page.length}`,
        limit,
        returned: page.length,
        total: events.length,
        hasMore: start + page.length < events.length,
        truncated: start + page.length < events.length,
        cursorOutOfRange: outOfRange,
        rebuildRequired: outOfRange,
      },
    },
  };
};

const asRecord = (value: unknown): Record<string, unknown> => (
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
);

const writeJson = (
  response: ServerResponse,
  status: number,
  payload: object,
  request: IncomingMessage,
): void => {
  const body = JSON.stringify(payload);
  response.statusCode = status;
  response.setHeader("cache-control", "no-store");
  response.setHeader("content-type", "application/json; charset=utf-8");
  response.setHeader("content-length", Buffer.byteLength(body));
  response.end(request.method === "HEAD" ? undefined : body);
};
