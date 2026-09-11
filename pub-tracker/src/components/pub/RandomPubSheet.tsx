import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Dices, LocateFixed } from 'lucide-react';
import { motion } from 'framer-motion';
import { BottomSheet } from '../ui/BottomSheet';
import { usePubData } from '../../context/PubDataContext';
import type { PubWithComputed } from '../../types';
import { PubImage } from '../ui/PubImage';
import { formatDistance } from '../../lib/geo';

type Scope = 'anywhere' | 'nearby' | 'wantToVisit' | 'favourites';

export function RandomPubSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { pubs, userLocation, requestLocation, locationStatus } = usePubData();
  const [scope, setScope] = useState<Scope>('anywhere');
  const [area, setArea] = useState<string>('');
  const [result, setResult] = useState<PubWithComputed | null>(null);
  const [noMatches, setNoMatches] = useState(false);
  const navigate = useNavigate();

  const areas = Array.from(new Set(pubs.map((p) => p.displayArea))).sort();

  function pick() {
    let pool = pubs.filter((p) => !p.status.visited);
    if (area) pool = pool.filter((p) => p.displayArea === area);
    if (scope === 'nearby' && userLocation) {
      pool = [...pool].sort((a, b) => (a.distanceKm ?? Infinity) - (b.distanceKm ?? Infinity)).slice(0, 20);
    }
    if (scope === 'wantToVisit') pool = pool.filter((p) => p.status.wantToVisit);
    if (scope === 'favourites') pool = pool.filter((p) => p.status.favouriteHarry || p.status.favouriteAva);

    if (pool.length === 0) {
      setResult(null);
      setNoMatches(true);
      return;
    }
    setNoMatches(false);
    setResult(pool[Math.floor(Math.random() * pool.length)]);
  }

  return (
    <BottomSheet
      open={open}
      onClose={() => {
        setResult(null);
        onClose();
      }}
      title="Pick Our Next Pub"
    >
      <div className="space-y-5 pb-4">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Choose from</div>
          <div className="grid grid-cols-2 gap-2">
            {(
              [
                { v: 'anywhere', label: 'Anywhere unvisited' },
                { v: 'nearby', label: 'Near me' },
                { v: 'wantToVisit', label: 'Want to visit' },
                { v: 'favourites', label: 'Favourites' },
              ] as { v: Scope; label: string }[]
            ).map((opt) => (
              <button
                key={opt.v}
                onClick={() => {
                  setScope(opt.v);
                  if (opt.v === 'nearby' && !userLocation) requestLocation();
                }}
                className={`rounded-xl border px-3 py-2.5 text-xs font-semibold ${
                  scope === opt.v ? 'border-brand-700 bg-brand-800 text-white' : 'border-line bg-white text-ink'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          {scope === 'nearby' && !userLocation && (
            <button onClick={requestLocation} className="mt-2 flex items-center gap-1.5 text-xs font-semibold text-brand-700">
              <LocateFixed size={13} />
              {locationStatus === 'requesting' ? 'Getting location…' : 'Enable location'}
            </button>
          )}
        </div>

        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Area (optional)</div>
          <select value={area} onChange={(e) => setArea(e.target.value)} className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm">
            <option value="">Any area</option>
            {areas.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>

        <button
          onClick={pick}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-800 py-3.5 text-sm font-bold text-white active:scale-95"
        >
          <Dices size={17} /> Pick a pub
        </button>

        {result && (
          <motion.div
            initial={{ opacity: 0, y: 12, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ type: 'spring', stiffness: 300, damping: 22 }}
            className="overflow-hidden rounded-card bg-white shadow-pop"
          >
            <PubImage src={result.displayImage} name={result.displayName} className="h-28 w-full" />
            <div className="p-4">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-brand-700">Tonight's pub</div>
              <div className="font-display text-lg font-bold text-ink">{result.displayName}</div>
              <div className="text-sm text-ink-soft">
                {result.displayArea}
                {result.distanceKm != null && ` · ${formatDistance(result.distanceKm)} away`}
              </div>
              <div className="mt-3 flex gap-2">
                <button onClick={pick} className="flex-1 rounded-xl border border-line py-2.5 text-xs font-semibold text-ink">
                  Pick again
                </button>
                <button
                  onClick={() => {
                    navigate(`/pub/${result.id}`);
                    onClose();
                  }}
                  className="flex-1 rounded-xl bg-brand-800 py-2.5 text-xs font-semibold text-white"
                >
                  View pub
                </button>
              </div>
            </div>
          </motion.div>
        )}
        {noMatches && (
          <p className="text-center text-sm text-ink-soft" aria-live="polite">
            No unvisited pubs match those filters — try widening your choice.
          </p>
        )}
      </div>
    </BottomSheet>
  );
}
