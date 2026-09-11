import { CheckCircle2, CircleDashed } from 'lucide-react';

export function StatusBadge({ visited, size = 'md' }: { visited: boolean; size?: 'sm' | 'md' }) {
  const pad = size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs';
  const iconSize = size === 'sm' ? 12 : 14;
  return visited ? (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full font-semibold ${pad}`}
      style={{ background: 'var(--color-visited-bg)', color: 'var(--color-visited-dark)' }}
    >
      <CheckCircle2 size={iconSize} strokeWidth={2.5} />
      Visited
    </span>
  ) : (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full font-semibold ${pad}`}
      style={{ background: 'var(--color-unvisited-bg)', color: 'var(--color-unvisited-dark)' }}
    >
      <CircleDashed size={iconSize} strokeWidth={2.5} />
      Not visited
    </span>
  );
}
