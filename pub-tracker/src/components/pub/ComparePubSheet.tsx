import { useMemo, useState } from 'react';
import { Navigation2 } from 'lucide-react';
import { BottomSheet } from '../ui/BottomSheet';
import { usePubData } from '../../context/PubDataContext';
import type { PubWithComputed } from '../../types';
import { haversineKm, formatDistance } from '../../lib/geo';
import { directionsBetween } from '../../lib/googleMaps';
import { PubImage } from '../ui/PubImage';

export function ComparePubSheet({ open, onClose, from }: { open: boolean; onClose: () => void; from: PubWithComputed }) {
  const { pubs } = usePubData();
  const [query, setQuery] = useState('');
  const [target, setTarget] = useState<PubWithComputed | null>(null);

  const results = useMemo(() => {
    if (!query.trim()) return [];
    const q = query.toLowerCase();
    return pubs.filter((p) => p.id !== from.id && p.displayName.toLowerCase().includes(q)).slice(0, 8);
  }, [pubs, query, from.id]);

  const distance = target ? haversineKm({ lat: from.lat, lon: from.lon }, { lat: target.lat, lon: target.lon }) : null;

  return (
    <BottomSheet
      open={open}
      onClose={() => {
        setTarget(null);
        setQuery('');
        onClose();
      }}
      title="Compare Two Pubs"
    >
      <div className="space-y-4 pb-4">
        {!target ? (
          <>
            <p className="text-sm text-ink-soft">
              Comparing from <span className="font-semibold text-ink">{from.displayName}</span>. Pick a second pub:
            </p>
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search for a pub…"
              className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm focus:border-brand-600 focus:outline-none"
            />
            <div className="flex flex-col gap-1">
              {results.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setTarget(p)}
                  className="flex items-center gap-3 rounded-xl p-2 text-left hover:bg-black/5"
                >
                  <PubImage src={p.displayImage} name={p.displayName} className="h-10 w-10 rounded-lg" iconSize={14} />
                  <div>
                    <div className="text-sm font-semibold text-ink">{p.displayName}</div>
                    <div className="text-xs text-ink-soft">{p.displayArea}</div>
                  </div>
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-card bg-paper-dim p-4">
              <PubMini pub={from} />
              <div className="text-center">
                <div className="font-display text-lg font-bold text-brand-800">{formatDistance(distance)}</div>
                <div className="text-[10px] uppercase tracking-wide text-ink-soft">straight-line</div>
              </div>
              <PubMini pub={target} align="right" />
            </div>
            <a
              href={directionsBetween({ lat: from.lat, lon: from.lon }, { lat: target.lat, lon: target.lon })}
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-center gap-2 rounded-xl bg-brand-800 py-3.5 text-sm font-bold text-white"
            >
              <Navigation2 size={16} /> Walking directions in Google Maps
            </a>
            <button onClick={() => setTarget(null)} className="w-full rounded-xl border border-line py-3 text-sm font-semibold text-ink">
              Choose a different pub
            </button>
          </div>
        )}
      </div>
    </BottomSheet>
  );
}

function PubMini({ pub, align = 'left' }: { pub: PubWithComputed; align?: 'left' | 'right' }) {
  return (
    <div className={align === 'right' ? 'text-right' : ''}>
      <div className="max-w-[100px] truncate text-xs font-semibold text-ink">{pub.displayName}</div>
      <div className="max-w-[100px] truncate text-[10px] text-ink-soft">{pub.displayArea}</div>
    </div>
  );
}
