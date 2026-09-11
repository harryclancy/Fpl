import { useMemo, useState } from 'react';
import { Check } from 'lucide-react';
import { BottomSheet } from '../ui/BottomSheet';
import { usePubData } from '../../context/PubDataContext';
import { PubImage } from '../ui/PubImage';

interface PubMultiSelectSheetProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (pubIds: string[]) => void;
  initialSelected?: string[];
  title?: string;
}

export function PubMultiSelectSheet({ open, onClose, onConfirm, initialSelected = [], title = 'Select Pubs' }: PubMultiSelectSheetProps) {
  const { pubs } = usePubData();
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string[]>(initialSelected);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = q ? pubs.filter((p) => p.displayName.toLowerCase().includes(q) || p.displayArea.toLowerCase().includes(q)) : pubs;
    return base.slice(0, 100);
  }, [pubs, query]);

  function toggle(id: string) {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  }

  return (
    <BottomSheet open={open} onClose={onClose} title={title} maxHeight="92vh">
      <div className="flex flex-col gap-3 pb-4">
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search pubs to add…"
          className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm focus:border-brand-600 focus:outline-none"
        />
        <div className="max-h-[50vh] overflow-y-auto">
          {results.map((p) => {
            const isSelected = selected.includes(p.id);
            return (
              <button
                key={p.id}
                onClick={() => toggle(p.id)}
                className={`flex w-full items-center gap-3 rounded-xl p-2 text-left transition ${isSelected ? 'bg-brand-50' : 'hover:bg-black/5'}`}
              >
                <PubImage src={p.displayImage} name={p.displayName} className="h-10 w-10 rounded-lg" iconSize={14} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-ink">{p.displayName}</div>
                  <div className="truncate text-xs text-ink-soft">{p.displayArea}</div>
                </div>
                <div
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 ${
                    isSelected ? 'border-brand-700 bg-brand-700 text-white' : 'border-line'
                  }`}
                >
                  {isSelected && <Check size={13} strokeWidth={3} />}
                </div>
              </button>
            );
          })}
        </div>
        <button
          disabled={selected.length === 0}
          onClick={() => {
            onConfirm(selected);
            setSelected([]);
            setQuery('');
          }}
          className="w-full rounded-xl bg-brand-800 py-3.5 text-sm font-bold text-white disabled:opacity-40"
        >
          {selected.length === 0 ? 'Select pubs to continue' : `Add ${selected.length} pub${selected.length === 1 ? '' : 's'}`}
        </button>
      </div>
    </BottomSheet>
  );
}
