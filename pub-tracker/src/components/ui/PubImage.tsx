import { Beer } from 'lucide-react';

const PALETTE = [
  ['#0f5132', '#1c7d4f'],
  ['#7c4a1e', '#a86b32'],
  ['#5b3a86', '#7d5bb6'],
  ['#8a2b3d', '#b8455c'],
  ['#1f4e79', '#2f7bc4'],
  ['#4a5518', '#748c2c'],
];

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

interface PubImageProps {
  src?: string | null;
  name: string;
  className?: string;
  iconSize?: number;
}

/** Renders a pub's real photo when we have one, else an attractive generated
 * placeholder (deterministic per pub name) rather than a broken image or blank box. */
export function PubImage({ src, name, className = '', iconSize = 28 }: PubImageProps) {
  if (src) {
    return (
      <img
        src={src}
        alt={`${name} exterior`}
        loading="lazy"
        className={`object-cover ${className}`}
        onError={(e) => {
          (e.currentTarget as HTMLImageElement).style.display = 'none';
        }}
      />
    );
  }

  const [c1, c2] = PALETTE[hashString(name) % PALETTE.length];
  return (
    <div
      className={`flex items-center justify-center ${className}`}
      style={{ background: `linear-gradient(135deg, ${c1}, ${c2})` }}
      aria-hidden="true"
    >
      <Beer size={iconSize} color="rgba(255,255,255,0.85)" strokeWidth={1.5} />
    </div>
  );
}
