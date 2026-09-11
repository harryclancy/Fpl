import { NavLink } from 'react-router-dom';
import { BottomSheet } from '../ui/BottomSheet';
import type { NavItem } from './navItems';

export function MoreSheet({ open, onClose, items }: { open: boolean; onClose: () => void; items: NavItem[] }) {
  return (
    <BottomSheet open={open} onClose={onClose} title="More">
      <div className="grid grid-cols-2 gap-3 pb-4">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onClose}
            className={({ isActive }) =>
              `flex flex-col items-center gap-2 rounded-card border p-4 text-center text-sm font-semibold transition active:scale-95 ${
                isActive ? 'border-brand-700 bg-brand-50 text-brand-800' : 'border-line bg-white text-ink'
              }`
            }
          >
            <item.icon size={24} strokeWidth={1.8} />
            {item.label}
          </NavLink>
        ))}
      </div>
    </BottomSheet>
  );
}
