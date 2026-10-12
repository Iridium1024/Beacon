import React from "react";
import { createRoot } from "react-dom/client";

import { CONSOLE_STYLES } from "@beacon-console/client/styles.js";

import { DesktopApp } from "./app/DesktopApp.js";
import "./styles.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("Beacon Desktop root is missing.");
}

createRoot(root).render(
  <React.StrictMode>
    <style>{CONSOLE_STYLES}</style>
    <DesktopApp />
  </React.StrictMode>,
);
