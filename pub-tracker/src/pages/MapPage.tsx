import { useMemo, useState } from 'react';
import { MapContainer, Marker, TileLayer, useMap } from 'react-leaflet';
import { LocateFixed } from 'lucide-react';
import { usePubData } from '../context/PubDataContext';
import { ClusterLayer } from '../components/map/ClusterLayer';
import { MapLegend } from '../components/map/MapLegend';
import { PubPreviewCard } from '../components/map/PubPreviewCard';
import { userLocationIcon } from '../components/map/markerIcons';
import { BottomSheet } from '../components/ui/BottomSheet';
import { SearchBar } from '../components/pub/SearchBar';
import { FilterSheet } from '../components/pub/FilterSheet';
import { DEFAULT_FILTERS, applyFilters, countActiveFilters, type PubFilters } from '../lib/filters';
import type { PubWithComputed } from '../types';

const DUBLIN_CENTER: [number, number] = [53.3498, -6.2603];

function LocateButton() {
  const map = useMap();
  const { userLocation, requestLocation, locationStatus } = usePubData();

  return (
    <button
      onClick={() => {
        requestLocation();
        if (userLocation) map.flyTo([userLocation.lat, userLocation.lon], 15, { duration: 0.8 });
      }}
      aria-label="Find my location"
      className="absolute right-3 top-28 z-[400] flex h-11 w-11 items-center justify-center rounded-full bg-white shadow-card active:scale-90"
    >
      <LocateFixed size={19} className={locationStatus === 'requesting' ? 'animate-pulse text-brand-700' : 'text-ink'} />
    </button>
  );
}

export function MapPage() {
  const { pubs, userLocation } = usePubData();
  const [filters, setFilters] = useState<PubFilters>(DEFAULT_FILTERS);
  const [filterOpen, setFilterOpen] = useState(false);
  const [selectedPub, setSelectedPub] = useState<PubWithComputed | null>(null);

  const filtered = useMemo(() => applyFilters(pubs, filters), [pubs, filters]);

  return (
    <div className="relative h-dvh w-full lg:h-[calc(100dvh-0px)]">
      <div className="absolute inset-x-0 top-0 z-[400] p-3 safe-top">
        <SearchBar
          value={filters.search}
          onChange={(v) => setFilters((f) => ({ ...f, search: v }))}
          onFilterClick={() => setFilterOpen(true)}
          activeFilterCount={countActiveFilters(filters)}
          placeholder="Search pubs on the map…"
        />
        <div className="mt-2 text-center">
          <span className="inline-block rounded-full bg-white/95 px-3 py-1 text-xs font-medium text-ink-soft shadow-card">
            {filtered.length} of {pubs.length} pubs shown
          </span>
        </div>
      </div>

      <MapContainer center={DUBLIN_CENTER} zoom={13} scrollWheelZoom className="h-full w-full" zoomControl={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClusterLayer pubs={filtered} onMarkerClick={setSelectedPub} />
        {userLocation && <Marker position={[userLocation.lat, userLocation.lon]} icon={userLocationIcon} />}
        <LocateButton />
      </MapContainer>

      <MapLegend />

      <FilterSheet open={filterOpen} onClose={() => setFilterOpen(false)} filters={filters} onChange={setFilters} />

      <BottomSheet open={!!selectedPub} onClose={() => setSelectedPub(null)} maxHeight="80vh">
        {selectedPub && <PubPreviewCard pub={selectedPub} onClose={() => setSelectedPub(null)} />}
      </BottomSheet>
    </div>
  );
}
