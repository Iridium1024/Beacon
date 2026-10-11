import type { ClientContext } from "@deepseek-ai/dsh-client-runtime/client";
import type {} from "@deepseek-ai/dsh-client-ui-layout/client";

import { ConsoleSidebar } from "./ConsoleSidebar.js";
import { ConsoleSurface } from "./ConsoleSurface.js";
import { consoleStore } from "./console-store.js";
import { CONSOLE_STYLE_ID, CONSOLE_STYLES } from "./styles.js";

export const inject = ["slots"];

/** DSH Client half: fill only the public layout seats owned by ui-layout. */
export function apply(ctx: ClientContext): void {
  ctx.effect(() => {
    const existing = document.querySelector<HTMLStyleElement>(
      `style[data-beacon-console-style="${CONSOLE_STYLE_ID}"]`,
    );
    if (existing !== null) {
      return () => undefined;
    }
    const style = document.createElement("style");
    style.dataset.beaconConsoleStyle = CONSOLE_STYLE_ID;
    style.textContent = CONSOLE_STYLES;
    document.head.append(style);
    return () => { style.remove(); };
  }, "beacon-console: scoped visual tokens");

  ctx.slots.inject("sidebar", () => ctx.slots.register(
    { name: "sidebar" },
    ConsoleSidebar,
  ));
  ctx.slots.inject("conversation", () => ctx.slots.register(
    { name: "conversation" },
    ConsoleSurface,
  ));

  ctx.effect(() => {
    consoleStore.start();
    return () => { consoleStore.stop(); };
  }, "beacon-console: bounded polling lifecycle");
}

