import { Search, SlidersHorizontal, X } from 'lucide-react';
import { useEffect, useState } from 'react';

interface SearchBarProps {
  value: string;
  onChange: (v: string) => void;
  onFilterClick?: () => void;
  activeFilterCount?: number;
  placeholder?: string;
}

/** Debounced text input so filtering 400+ pubs never feels laggy while typing. */
export function SearchBar({ value, onChange, onFilterClick, activeFilterCount = 0, placeholder = 'Search pubs or areas…' }: SearchBarProps) {
  const [local, setLocal] = useState(value);

  useEffect(() => setLocal(value), [value]);

  useEffect(() => {
    const t = setTimeout(() => {
      if (local !== value) onChange(local);
    }, 150);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [local]);

  return (
    <div className="flex items-center gap-2">
      <div className="relative flex-1">
        <Search size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-soft" />
        <input
          type="search"
          value={local}
          onChange={(e) => setLocal(e.target.value)}
          placeholder={placeholder}
          aria-label="Search pubs"
          className="h-11 w-full rounded-full border border-line bg-white pl-10 pr-9 text-[15px] text-ink placeholder:text-ink-soft/70 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-100"
        />
        {local && (
          <button
            aria-label="Clear search"
            onClick={() => {
              setLocal('');
              onChange('');
            }}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-soft"
          >
            <X size={16} />
          </button>
        )}
      </div>
      {onFilterClick && (
        <button
          onClick={onFilterClick}
          aria-label="Filters"
          className="relative inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-line bg-white text-ink active:scale-95"
        >
          <SlidersHorizontal size={17} />
          {activeFilterCount > 0 && (
            <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-brand-700 text-[10px] font-bold text-white">
              {activeFilterCount}
            </span>
          )}
        </button>
      )}
    </div>
  );
}
