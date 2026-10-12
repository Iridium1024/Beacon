import type { SVGProps } from "react";

export type IconName =
  | "activity"
  | "agent"
  | "beacon"
  | "capability"
  | "check"
  | "chevron"
  | "close"
  | "help"
  | "refresh"
  | "settings"
  | "timeline"
  | "workspace";

const paths: Record<IconName, string[]> = {
  activity: ["M4 12h3l2-6 4 12 2-6h5"],
  agent: ["M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z", "M5 21a7 7 0 0 1 14 0"],
  beacon: ["M12 4v4", "M12 16v4", "M4 12h4", "M16 12h4", "M7 7l2 2", "M15 15l2 2", "M17 7l-2 2", "M9 15l-2 2", "M12 12h.01"],
  capability: ["M12 3 4.5 7v5c0 4.6 3.2 7.5 7.5 9 4.3-1.5 7.5-4.4 7.5-9V7L12 3Z", "m9.5 12 1.7 1.7 3.6-3.7"],
  check: ["M5 12.5 9.5 17 19 7.5"],
  chevron: ["m8 10 4 4 4-4"],
  close: ["M6 6l12 12", "M18 6 6 18"],
  help: ["M9.1 9a3 3 0 1 1 4.7 2.5c-1.2.8-1.8 1.3-1.8 2.5", "M12 18h.01", "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"],
  refresh: ["M20 11a8 8 0 1 0-2.3 5.7", "M20 5v6h-6"],
  settings: ["M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z", "M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2 3.4-.2-.1a1.7 1.7 0 0 0-1.9.1l-.5.3a1.7 1.7 0 0 0-.9 1.6v.2h-4v-.2a1.7 1.7 0 0 0-.9-1.6l-.5-.3a1.7 1.7 0 0 0-1.9-.1l-.2.1-2-3.4.1-.1A1.7 1.7 0 0 0 5.2 15v-.6a1.7 1.7 0 0 0-1.2-1.6h-.2v-4H4a1.7 1.7 0 0 0 1.2-1.6v-.6a1.7 1.7 0 0 0-.3-1.9l-.1-.1 2-3.4.2.1a1.7 1.7 0 0 0 1.9-.1l.5-.3a1.7 1.7 0 0 0 .9-1.6V1h4v.2a1.7 1.7 0 0 0 .9 1.6l.5.3a1.7 1.7 0 0 0 1.9.1l.2-.1 2 3.4-.1.1a1.7 1.7 0 0 0-.3 1.9v.6a1.7 1.7 0 0 0 1.2 1.6h.2v4h-.2a1.7 1.7 0 0 0-1.2 1.6v.6Z"],
  timeline: ["M5 5h14", "M5 12h9", "M5 19h12", "M3 5h.01", "M3 12h.01", "M3 19h.01"],
  workspace: ["M4 6.5h6l2 2h8v10H4Z", "M4 6.5V5h6l2 1.5"],
};

export const Icon = ({
  name,
  size = 18,
  ...props
}: { name: IconName; size?: 16 | 18 | 20 | 24 | 28 | 32 } & SVGProps<SVGSVGElement>): JSX.Element => (
  <svg
    aria-hidden="true"
    fill="none"
    height={size}
    viewBox="0 0 24 24"
    width={size}
    {...props}
  >
    {paths[name].map((path) => (
      <path
        d={path}
        key={path}
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
        vectorEffect="non-scaling-stroke"
      />
    ))}
  </svg>
);
