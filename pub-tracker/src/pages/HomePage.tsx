import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Dices, Map as MapIcon } from 'lucide-react';
import { usePubData } from '../context/PubDataContext';
import { ProgressBar } from '../components/ui/ProgressBar';
import { PubScrollRow } from '../components/pub/PubScrollRow';
import { RandomPubSheet } from '../components/pub/RandomPubSheet';
import { useRecentPhotos } from '../hooks/useRecentPhotos';
import { blobUrl } from '../lib/photos';

export function HomePage() {
  const { pubs, userLocation, requestLocation, locationStatus } = usePubData();
  const [randomOpen, setRandomOpen] = useState(false);
  const recentPhotos = useRecentPhotos(8);

  const visited = useMemo(() => pubs.filter((p) => p.status.visited), [pubs]);
  const pct = pubs.length ? (visited.length / pubs.length) * 100 : 0;

  const nearbyUnvisited = useMemo(() => {
    if (!userLocation) return [];
    return [...pubs]
      .filter((p) => !p.status.visited)
      .sort((a, b) => (a.distanceKm ?? Infinity) - (b.distanceKm ?? Infinity))
      .slice(0, 10);
  }, [pubs, userLocation]);

  const recentlyVisited = useMemo(
    () =>
      [...visited]
        .sort((a, b) => (b.status.firstVisitDate ?? '').localeCompare(a.status.firstVisitDate ?? ''))
        .slice(0, 10),
    [visited]
  );

  const wantToVisit = useMemo(() => pubs.filter((p) => p.status.wantToVisit).slice(0, 10), [pubs]);

  const highestRated = useMemo(
    () =>
      [...pubs]
        .filter((p) => p.combinedRating != null)
        .sort((a, b) => b.combinedRating! - a.combinedRating!)
        .slice(0, 10),
    [pubs]
  );

  return (
    <div className="pb-6">
      <div className="safe-top px-4 sm:px-6">
        <div className="flex items-center justify-between pt-6">
          <div>
            <p className="text-sm text-ink-soft">Sláinte, Harry &amp; Ava</p>
            <h1 className="font-display text-2xl font-bold text-ink">Dublin Pub Challenge</h1>
          </div>
        </div>

        <div className="mt-4 rounded-card bg-brand-800 p-5 text-white shadow-pop">
          <div className="flex items-end justify-between">
            <div>
              <div className="font-display text-3xl font-bold">
                {visited.length} <span className="text-brand-100/70 text-lg">/ {pubs.length}</span>
              </div>
              <div className="text-sm text-brand-100/90">Dublin pubs visited</div>
            </div>
            <div className="text-2xl font-bold">{pct.toFixed(1)}%</div>
          </div>
          <div className="mt-3">
            <ProgressBar value={pct} color="#e4f6ea" />
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <button
            onClick={() => setRandomOpen(true)}
            className="flex items-center justify-center gap-2 rounded-card bg-ink py-4 text-sm font-bold text-white shadow-card active:scale-95"
          >
            <Dices size={18} /> Pick Our Next Pub
          </button>
          <Link
            to="/map"
            className="flex items-center justify-center gap-2 rounded-card border border-line bg-white py-4 text-sm font-bold text-ink shadow-card active:scale-95"
          >
            <MapIcon size={18} /> Explore the Map
          </Link>
        </div>

        {!userLocation && (
          <button
            onClick={requestLocation}
            className="mt-3 w-full rounded-card border border-dashed border-line bg-white/60 py-3 text-xs font-medium text-brand-700"
          >
            {locationStatus === 'requesting' ? 'Getting your location…' : 'Enable location to see pubs near you'}
          </button>
        )}
      </div>

      <div className="mt-6 space-y-6">
        {userLocation && (
          <PubScrollRow title="Nearby Unvisited Pubs" pubs={nearbyUnvisited} seeAllHref="/map" emptyText="No unvisited pubs found nearby." />
        )}
        <PubScrollRow
          title="Recently Visited"
          pubs={recentlyVisited}
          seeAllHref="/visited"
          emptyText="Mark your first pub visited to see it here."
        />
        <PubScrollRow
          title="Want to Visit"
          pubs={wantToVisit}
          seeAllHref="/want-to-visit"
          emptyText="Bookmark pubs you'd like to try next."
        />
        <PubScrollRow title="Highest Rated" pubs={highestRated} seeAllHref="/pubs" emptyText="Rate a pub to see your top picks here." />

        {recentPhotos && recentPhotos.length > 0 && (
          <section>
            <div className="mb-2.5 px-4 sm:px-6">
              <h2 className="font-display text-base font-bold text-ink">Recent Pint Photos</h2>
            </div>
            <div className="no-scrollbar flex gap-2.5 overflow-x-auto px-4 pb-1 sm:px-6">
              {recentPhotos.map((photo) => (
                <Link key={photo.id} to={`/pub/${photo.pubId}`} className="block h-28 w-28 shrink-0 overflow-hidden rounded-xl shadow-card">
                  <img src={blobUrl(photo.thumbBlob)} alt={photo.drinkName} className="h-full w-full object-cover" loading="lazy" />
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>

      <RandomPubSheet open={randomOpen} onClose={() => setRandomOpen(false)} />
    </div>
  );
}
