import { NavLink } from 'react-router-dom';
import { Beer } from 'lucide-react';
import { ALL_NAV } from './navItems';
import { usePubData } from '../../context/PubDataContext';
import { ProgressBar } from '../ui/ProgressBar';

export function Sidebar() {
  const { pubs } = usePubData();
  const visited = pubs.filter((p) => p.status.visited).length;
  const total = pubs.length;
  const pct = total ? (visited / total) * 100 : 0;

  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-line bg-white/70 px-4 py-6 backdrop-blur lg:flex">
      <div className="mb-8 flex items-center gap-2.5 px-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-800 text-white">
          <Beer size={18} strokeWidth={2} />
        </div>
        <div>
          <div className="font-display text-[15px] font-bold leading-tight text-ink">Dublin Pub Tracker</div>
          <div className="text-[11px] text-ink-soft">Harry &amp; Ava</div>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1" aria-label="Primary navigation">
        {ALL_NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                isActive ? 'bg-brand-800 text-white shadow-card' : 'text-ink-soft hover:bg-black/[0.04] hover:text-ink'
              }`
            }
          >
            <item.icon size={18} strokeWidth={1.9} />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-6 rounded-card border border-line bg-white p-4">
        <div className="mb-1.5 flex items-baseline justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-ink-soft">Challenge</span>
          <span className="text-xs font-bold text-brand-800">{pct.toFixed(0)}%</span>
        </div>
        <ProgressBar value={pct} />
        <div className="mt-2 text-xs text-ink-soft">
          {visited} / {total} pubs visited
        </div>
      </div>
    </aside>
  );
}
