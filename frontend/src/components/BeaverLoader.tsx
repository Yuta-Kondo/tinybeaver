import { useEffect, useState } from "react";

type Size = "sm" | "md" | "lg";

interface Props {
  size?: Size;
  className?: string;
}

interface Dot {
  x: number;
  y: number;
  fill: string;
}

const VIEW = 48;
const STEP = 4;
const R = 1.75;

const SIZES: Record<Size, number> = { sm: 16, md: 22, lg: 36 };

/** Logo palette — snapped to favicon colors for a crisp dot-matrix look. */
const PALETTE: [number, number, number][] = [
  [36, 60, 84],    // navy outline
  [116, 84, 68],   // body brown
  [84, 68, 52],    // tail / dark brown
  [116, 148, 76],  // stump green
  [204, 180, 148], // stump top / snout
];

let cachedDots: Dot[] | null = null;
let loadPromise: Promise<Dot[]> | null = null;

function snapColor(r: number, g: number, b: number): string {
  let best = PALETTE[0];
  let bestDist = Infinity;
  for (const c of PALETTE) {
    const dr = r - c[0];
    const dg = g - c[1];
    const db = b - c[2];
    const dist = dr * dr + dg * dg + db * db;
    if (dist < bestDist) {
      bestDist = dist;
      best = c;
    }
  }
  return `rgb(${best[0]},${best[1]},${best[2]})`;
}

function sampleDots(img: HTMLImageElement): Dot[] {
  const canvas = document.createElement("canvas");
  canvas.width = VIEW;
  canvas.height = VIEW;
  const ctx = canvas.getContext("2d");
  if (!ctx) return [];

  ctx.drawImage(img, 0, 0, VIEW, VIEW);
  const { data } = ctx.getImageData(0, 0, VIEW, VIEW);
  const dots: Dot[] = [];

  for (let y = STEP / 2; y < VIEW; y += STEP) {
    for (let x = STEP / 2; x < VIEW; x += STEP) {
      const px = Math.min(VIEW - 1, Math.round(x));
      const py = Math.min(VIEW - 1, Math.round(y));
      const i = (py * VIEW + px) * 4;
      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      const a = data[i + 3];
      if (a < 100) continue;
      if (r + g + b < 40) continue;

      dots.push({ x: px, y: py, fill: snapColor(r, g, b) });
    }
  }
  return dots;
}

function loadDots(): Promise<Dot[]> {
  if (cachedDots) return Promise.resolve(cachedDots);
  if (!loadPromise) {
    loadPromise = new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        cachedDots = sampleDots(img);
        resolve(cachedDots);
      };
      img.onerror = () => resolve([]);
      img.src = "/favicon.png";
    });
  }
  return loadPromise;
}

/** Dot-matrix beaver from favicon colors — two-frame walk cycle. */
export default function BeaverLoader({ size = "md", className = "" }: Props) {
  const px = SIZES[size];
  const [dots, setDots] = useState<Dot[] | null>(() => cachedDots);

  useEffect(() => {
    if (cachedDots) return;
    loadDots().then(setDots);
  }, []);

  return (
    <span
      className={`beaver-loader beaver-loader--${size} ${className}`.trim()}
      aria-hidden="true"
      style={{ width: px, height: px }}
    >
      <svg viewBox={`0 0 ${VIEW} ${VIEW}`} width={px} height={px}>
        {dots && dots.length > 0 && (
          <g className="beaver-loader__track">
            <g className="beaver-loader__step beaver-loader__step--a">
              {dots.map((d, i) => (
                <circle key={`a-${i}`} cx={d.x} cy={d.y} r={R} fill={d.fill} />
              ))}
            </g>
            <g className="beaver-loader__step beaver-loader__step--b">
              {dots.map((d, i) => (
                <circle key={`b-${i}`} cx={d.x} cy={d.y} r={R} fill={d.fill} />
              ))}
            </g>
          </g>
        )}
      </svg>
    </span>
  );
}
