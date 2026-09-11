import type { ReactNode } from 'react';
import { BottomSheet } from '../ui/BottomSheet';
import { DEFAULT_FILTERS, type PubFilters, type VisitedFilter } from '../../lib/filters';
import { usePubData } from '../../context/PubDataContext';
import { RatingStars } from '../ui/RatingStars';
import { LocateFixed } from 'lucide-react';

interface FilterSheetProps {
  open: boolean;
  onClose: () => void;
  filters: PubFilters;
  onChange: (f: PubFilters) => void;
  hideDistance?: boolean;
}

const VISITED_OPTIONS: { value: VisitedFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'visited', label: 'Visited' },
  { value: 'unvisited', label: 'Not visited' },
];

const DISTANCE_OPTIONS = [
  { value: 0.5, label: '500m' },
  { value: 1, label: '1km' },
  { value: 2, label: '2km' },
  { value: 5, label: '5km' },
];

export function FilterSheet({ open, onClose, filters, onChange, hideDistance = false }: FilterSheetProps) {
  const { areas, districts, userLocation, locationStatus, requestLocation } = usePubData();

  function set<K extends keyof PubFilters>(key: K, value: PubFilters[K]) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <BottomSheet open={open} onClose={onClose} title="Filters" maxHeight="90vh">
      <div className="space-y-6 pb-6">
        <section>
          <FieldLabel>Status</FieldLabel>
          <SegmentedControl options={VISITED_OPTIONS} value={filters.visited} onChange={(v) => set('visited', v)} />
        </section>

        <section>
          <FieldLabel>Shortlists</FieldLabel>
          <div className="flex flex-wrap gap-2">
            <Chip active={filters.favourites} onClick={() => set('favourites', !filters.favourites)}>
              ♥ Favourites
            </Chip>
            <Chip active={filters.wantToVisit} onClick={() => set('wantToVisit', !filters.wantToVisit)}>
              🔖 Want to visit
            </Chip>
            <Chip active={filters.harryRated} onClick={() => set('harryRated', !filters.harryRated)}>
              Harry rated
            </Chip>
            <Chip active={filters.avaRated} onClick={() => set('avaRated', !filters.avaRated)}>
              Ava rated
            </Chip>
          </div>
        </section>

        <section>
          <FieldLabel>Minimum combined rating</FieldLabel>
          <div className="flex items-center gap-3">
            <RatingStars
              value={filters.minRating}
              interactive
              size={26}
              onChange={(v) => set('minRating', v)}
            />
            {filters.minRating > 0 && (
              <button onClick={() => set('minRating', 0)} className="text-xs font-semibold text-brand-700">
                Clear
              </button>
            )}
          </div>
        </section>

        <section>
          <FieldLabel>Area</FieldLabel>
          <select
            value={filters.area ?? ''}
            onChange={(e) => set('area', e.target.value || null)}
            className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm text-ink"
          >
            <option value="">All areas</option>
            {areas.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </section>

        <section>
          <FieldLabel>Dublin postal district</FieldLabel>
          <select
            value={filters.district ?? ''}
            onChange={(e) => set('district', e.target.value || null)}
            className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm text-ink"
          >
            <option value="">All districts</option>
            {districts.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </section>

        {!hideDistance && (
          <section>
            <FieldLabel>Distance</FieldLabel>
            {userLocation ? (
              <div className="flex flex-wrap gap-2">
                {DISTANCE_OPTIONS.map((d) => (
                  <Chip
                    key={d.value}
                    active={filters.maxDistanceKm === d.value}
                    onClick={() => set('maxDistanceKm', filters.maxDistanceKm === d.value ? null : d.value)}
                  >
                    Within {d.label}
                  </Chip>
                ))}
              </div>
            ) : (
              <button
                onClick={requestLocation}
                disabled={locationStatus === 'requesting'}
                className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-line py-3 text-sm font-medium text-brand-700"
              >
                <LocateFixed size={16} />
                {locationStatus === 'requesting' ? 'Getting your location…' : 'Enable location for "Pubs near me"'}
              </button>
            )}
          </section>
        )}

        <div className="flex gap-3 pt-2">
          <button
            onClick={() => onChange(DEFAULT_FILTERS)}
            className="flex-1 rounded-xl border border-line py-3 text-sm font-semibold text-ink"
          >
            Reset all
          </button>
          <button onClick={onClose} className="flex-1 rounded-xl bg-brand-800 py-3 text-sm font-semibold text-white">
            Show results
          </button>
        </div>
      </div>
    </BottomSheet>
  );
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">{children}</div>;
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3.5 py-2 text-xs font-semibold transition active:scale-95 ${
        active ? 'border-brand-700 bg-brand-800 text-white' : 'border-line bg-white text-ink'
      }`}
    >
      {children}
    </button>
  );
}

function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-1 rounded-xl bg-black/5 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-lg py-2 text-xs font-semibold transition ${
            value === o.value ? 'bg-white text-ink shadow-card' : 'text-ink-soft'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
