// Coherent inline-SVG icon set. 16×16 viewBox, inherits color via currentColor.
// Stroke icons use 1.5 width, round caps/joins for a consistent feel.

export type IconName =
  | "copy" | "check" | "regenerate" | "edit" | "trash"
  | "thumbUp" | "thumbDown" | "attach" | "send" | "stop" | "close";

interface Props {
  name: IconName;
  size?: number;
  className?: string;
}

const STROKE = {
  fill: "none" as const,
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export default function Icon({ name, size = 15, className }: Props) {
  const common = { width: size, height: size, viewBox: "0 0 16 16", className, "aria-hidden": true };
  switch (name) {
    case "copy":
      return (
        <svg {...common} {...STROKE}>
          <rect x="5.5" y="5.5" width="8" height="8" rx="2" />
          <path d="M10.5 3.5a2 2 0 00-2-2h-4a2 2 0 00-2 2v4a2 2 0 002 2" />
        </svg>
      );
    case "check":
      return (
        <svg {...common} {...STROKE}>
          <path d="M3 8.5l3.2 3.2L13 5" />
        </svg>
      );
    case "regenerate":
      return (
        <svg {...common} {...STROKE}>
          <path d="M13 8a5 5 0 11-1.6-3.7" />
          <path d="M13 2v3h-3" />
        </svg>
      );
    case "edit":
      return (
        <svg {...common} {...STROKE}>
          <path d="M11.5 2.5l2 2L6 12l-2.7.7L4 10z" />
        </svg>
      );
    case "trash":
      return (
        <svg {...common} {...STROKE}>
          <path d="M3 4.5h10M6.5 4.5V3a1 1 0 011-1h1a1 1 0 011 1v1.5M4.5 4.5l.6 8a1 1 0 001 .9h3.8a1 1 0 001-.9l.6-8" />
        </svg>
      );
    case "thumbUp":
      return (
        <svg {...common} {...STROKE}>
          <path d="M4.5 7v6M4.5 7l2.2-4.4a1.3 1.3 0 012.4.5V6h3.1a1.2 1.2 0 011.2 1.5l-1 4A1.3 1.3 0 0111.1 13H4.5" />
        </svg>
      );
    case "thumbDown":
      return (
        <svg {...common} {...STROKE}>
          <path d="M11.5 9V3M11.5 9l-2.2 4.4a1.3 1.3 0 01-2.4-.5V10H3.8a1.2 1.2 0 01-1.2-1.5l1-4A1.3 1.3 0 014.9 3h6.6" />
        </svg>
      );
    case "attach":
      return (
        <svg {...common} {...STROKE}>
          <path d="M8 3.5v9M3.5 8h9" />
        </svg>
      );
    case "send":
      return (
        <svg {...common} {...STROKE}>
          <path d="M8 13V3.5M8 3.5L4 7.5M8 3.5l4 4" />
        </svg>
      );
    case "stop":
      return (
        <svg {...common} fill="currentColor">
          <rect x="4" y="4" width="8" height="8" rx="1.5" />
        </svg>
      );
    case "close":
      return (
        <svg {...common} {...STROKE}>
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      );
  }
}
