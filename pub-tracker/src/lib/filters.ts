import type { PubWithComputed } from '../types';

export type VisitedFilter = 'all' | 'visited' | 'unvisited';

export interface PubFilters {
  search: string;
  visited: VisitedFilter;
  favourites: boolean;
  wantToVisit: boolean;
  harryRated: boolean;
  avaRated: boolean;
  minRating: number;
  area: string | null;
  district: string | null;
  maxDistanceKm: number | null;
}

export const DEFAULT_FILTERS: PubFilters = {
  search: '',
  visited: 'all',
  favourites: false,
  wantToVisit: false,
  harryRated: false,
  avaRated: false,
  minRating: 0,
  area: null,
  district: null,
  maxDistanceKm: null,
};

export function isFiltersActive(f: PubFilters): boolean {
  return (
    f.search.trim() !== '' ||
    f.visited !== 'all' ||
    f.favourites ||
    f.wantToVisit ||
    f.harryRated ||
    f.avaRated ||
    f.minRating > 0 ||
    !!f.area ||
    !!f.district ||
    f.maxDistanceKm != null
  );
}

export function countActiveFilters(f: PubFilters): number {
  let n = 0;
  if (f.visited !== 'all') n++;
  if (f.favourites) n++;
  if (f.wantToVisit) n++;
  if (f.harryRated) n++;
  if (f.avaRated) n++;
  if (f.minRating > 0) n++;
  if (f.area) n++;
  if (f.district) n++;
  if (f.maxDistanceKm != null) n++;
  return n;
}

export function applyFilters(pubs: PubWithComputed[], f: PubFilters): PubWithComputed[] {
  const q = f.search.trim().toLowerCase();
  return pubs.filter((p) => {
    if (q && !p.displayName.toLowerCase().includes(q) && !p.displayArea.toLowerCase().includes(q)) return false;
    if (f.visited === 'visited' && !p.status.visited) return false;
    if (f.visited === 'unvisited' && p.status.visited) return false;
    if (f.favourites && !(p.status.favouriteHarry || p.status.favouriteAva)) return false;
    if (f.wantToVisit && !p.status.wantToVisit) return false;
    if (f.harryRated && p.harryReview?.rating == null) return false;
    if (f.avaRated && p.avaReview?.rating == null) return false;
    if (f.minRating > 0 && (p.combinedRating ?? 0) < f.minRating) return false;
    if (f.area && p.displayArea !== f.area) return false;
    if (f.district && p.district !== f.district) return false;
    if (f.maxDistanceKm != null && (p.distanceKm == null || p.distanceKm > f.maxDistanceKm)) return false;
    return true;
  });
}
