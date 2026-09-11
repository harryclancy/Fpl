import type { LucideIcon } from 'lucide-react';
import { motion } from 'framer-motion';

interface IconToggleProps {
  icon: LucideIcon;
  active: boolean;
  onClick: () => void;
  label: string;
  activeColor?: string;
  size?: number;
  className?: string;
}

export function IconToggle({ icon: Icon, active, onClick, label, activeColor = 'var(--color-favourite)', size = 20, className = '' }: IconToggleProps) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onClick();
      }}
      aria-pressed={active}
      aria-label={label}
      title={label}
      className={`inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/90 shadow-card backdrop-blur transition-transform active:scale-90 ${className}`}
    >
      <motion.span
        key={active ? 'on' : 'off'}
        initial={{ scale: 0.6 }}
        animate={{ scale: 1 }}
        transition={{ type: 'spring', stiffness: 500, damping: 15 }}
        className="inline-flex"
      >
        <Icon size={size} color={active ? activeColor : '#8a8377'} fill={active ? activeColor : 'none'} strokeWidth={1.8} />
      </motion.span>
    </button>
  );
}
