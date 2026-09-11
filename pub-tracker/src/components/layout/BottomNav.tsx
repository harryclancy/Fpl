import { NavLink } from 'react-router-dom';
import { MoreHorizontal } from 'lucide-react';
import { useState } from 'react';
import { PRIMARY_NAV, SECONDARY_NAV } from './navItems';
import { MoreSheet } from './MoreSheet';

export function BottomNav() {
  const [moreOpen, setMoreOpen] = useState(false);

  return (
    <>
      <nav
        className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-white/95 backdrop-blur safe-bottom lg:hidden"
        aria-label="Primary navigation"
      >
        <div className="mx-auto flex max-w-md items-stretch justify-between px-1">
          {PRIMARY_NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition-colors ${
                  isActive ? 'text-brand-800' : 'text-ink-soft'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon size={22} strokeWidth={isActive ? 2.3 : 1.8} />
                  {item.label}
                </>
              )}
            </NavLink>
          ))}
          <button
            onClick={() => setMoreOpen(true)}
            className="flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-medium text-ink-soft"
            aria-label="More navigation options"
          >
            <MoreHorizontal size={22} strokeWidth={1.8} />
            More
          </button>
        </div>
      </nav>
      <MoreSheet open={moreOpen} onClose={() => setMoreOpen(false)} items={SECONDARY_NAV} />
    </>
  );
}
