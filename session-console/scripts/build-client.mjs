import { build } from "esbuild";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const id = "@beacon-local/dsh-session-console";

await build({
  entryPoints: [resolve(root, "src/client/index.ts")],
  outfile: resolve(root, "lib/client.js"),
  bundle: true,
  format: "cjs",
  platform: "browser",
  target: "es2022",
  sourcemap: true,
  legalComments: "none",
  external: [
    "@deepseek-ai/cordis",
    "@deepseek-ai/dsh-client-runtime/client",
    "@deepseek-ai/dsh-client-ui-slots",
    "react",
    "react-dom",
    "react-dom/client",
    "react/jsx-runtime",
  ],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  banner: {
    js: `window.__ModuleLoader__.load({ id: ${JSON.stringify(id)}, factory: (require) => { var module = { exports: {} }; var exports = module.exports;`,
  },
  footer: {
    js: "return module.exports; } });",
  },
});

