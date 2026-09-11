import { useMemo, useState } from 'react';
import { LayoutGrid, List, MapPin } from 'lucide-react';
import { Link } from 'react-router-dom';
import { usePubData } from '../context/PubDataContext';
import { PageHeader } from '../components/layout/PageHeader';
import { SearchBar } from '../components/pub/SearchBar';
import { FilterSheet } from '../components/pub/FilterSheet';
import { PubCard } from '../components/pub/PubCard';
import { PubListRow } from '../components/pub/PubListRow';
import { EmptyState } from '../components/ui/EmptyState';
import { DEFAULT_FILTERS, applyFilters, countActiveFilters, type PubFilters } from '../lib/filters';
import { Beer } from 'lucide-react';

type SortKey = 'name' | 'distance' | 'rating' | 'area';

const PAGE_SIZE = 60;

export function AllPubsPage() {
  const { pubs, areas, userLocation } = usePubData();
  const [filters, setFilters] = useState<PubFilters>(DEFAULT_FILTERS);
  const [filterOpen, setFilterOpen] = useState(false);
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [sort, setSort] = useState<SortKey>('name');
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const filtered = useMemo(() => {
    const result = applyFilters(pubs, filters);
    const sorted = [...result];
    if (sort === 'name') sorted.sort((a, b) => a.displayName.localeCompare(b.displayName));
    if (sort === 'area') sorted.sort((a, b) => a.displayArea.localeCompare(b.displayArea));
    if (sort === 'rating') sorted.sort((a, b) => (b.combinedRating ?? -1) - (a.combinedRating ?? -1));
    if (sort === 'distance') sorted.sort((a, b) => (a.distanceKm ?? Infinity) - (b.distanceKm ?? Infinity));
    return sorted;
  }, [pubs, filters, sort]);

  const visible = filtered.slice(0, visibleCount);
  const topAreas = useMemo(() => areas.slice(0, 12), [areas]);

  return (
    <div>
      <PageHeader title="All Pubs" subtitle={`${pubs.length} pubs across Dublin`} />
      <div className="space-y-4 px-4 pb-6 pt-4 sm:px-6">
        <SearchBar
          value={filters.search}
          onChange={(v) => {
            setFilters((f) => ({ ...f, search: v }));
            setVisibleCount(PAGE_SIZE);
          }}
          onFilterClick={() => setFilterOpen(true)}
          activeFilterCount={countActiveFilters(filters)}
        />

        <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          {topAreas.map((area) => (
            <Link
              key={area}
              to={`/areas/${encodeURIComponent(area)}`}
              className="flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-white px-3.5 py-2 text-xs font-semibold text-ink-soft transition active:scale-95"
            >
              <MapPin size={12} /> {area}
            </Link>
          ))}
        </div>

        <div className="flex items-center justify-between">
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="h-9 rounded-full border border-line bg-white px-3 text-xs font-semibold text-ink"
            aria-label="Sort pubs"
          >
            <option value="name">Sort: Name</option>
            <option value="area">Sort: Area</option>
            <option value="rating">Sort: Top rated</option>
            {userLocation && <option value="distance">Sort: Nearest</option>}
          </select>
          <div className="flex items-center gap-1 rounded-full bg-black/5 p-1">
            <button
              onClick={() => setView('grid')}
              aria-label="Grid view"
              aria-pressed={view === 'grid'}
              className={`flex h-8 w-8 items-center justify-center rounded-full ${view === 'grid' ? 'bg-white shadow-card' : ''}`}
            >
              <LayoutGrid size={15} />
            </button>
            <button
              onClick={() => setView('list')}
              aria-label="List view"
              aria-pressed={view === 'list'}
              className={`flex h-8 w-8 items-center justify-center rounded-full ${view === 'list' ? 'bg-white shadow-card' : ''}`}
            >
              <List size={15} />
            </button>
          </div>
        </div>

        {filtered.length === 0 ? (
          <EmptyState icon={Beer} title="No pubs match" description="Try widening your filters or clearing the search." />
        ) : view === 'grid' ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {visible.map((pub) => (
              <PubCard key={pub.id} pub={pub} />
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {visible.map((pub) => (
              <PubListRow key={pub.id} pub={pub} />
            ))}
          </div>
        )}

        {visibleCount < filtered.length && (
          <button
            onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}
            className="mx-auto block rounded-full border border-line bg-white px-5 py-2.5 text-sm font-semibold text-ink"
          >
            Load more ({filtered.length - visibleCount} remaining)
          </button>
        )}
      </div>

      <FilterSheet open={filterOpen} onClose={() => setFilterOpen(false)} filters={filters} onChange={setFilters} />
    </div>
  );
}
