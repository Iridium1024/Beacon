import React from "react";
import { createRoot } from "react-dom/client";

import { ConsoleSidebar } from "../client/ConsoleSidebar.js";
import { ConsoleSurface } from "../client/ConsoleSurface.js";
import { CONSOLE_STYLES } from "../client/styles.js";

const DEMO_STYLES = `
html,body,#root{height:100%;margin:0;min-width:320px}
body{background:#f3f1ec;overflow:hidden}
.bc-demo-shell{display:grid;grid-template-columns:252px minmax(0,1fr);height:100%;min-height:0}
@media (max-width:760px){body{overflow:auto}.bc-demo-shell{display:block;height:auto;min-height:100%}.bc-demo-shell>.bc-sidebar{border-bottom:1px solid var(--bc-border);border-right:0;height:auto;max-height:none}.bc-session-section{max-height:240px}.bc-demo-shell>.bc-surface{height:auto;min-height:700px}}
`;

function Demo(): JSX.Element {
  return (
    <>
      <style>{CONSOLE_STYLES}{DEMO_STYLES}</style>
      <div className="bc-demo-shell">
        <ConsoleSidebar />
        <ConsoleSurface />
      </div>
    </>
  );
}

const root = document.getElementById("root");
if (root === null) {
  throw new Error("Demo root is missing.");
}
createRoot(root).render(
  <React.StrictMode>
    <Demo />
  </React.StrictMode>,
);

