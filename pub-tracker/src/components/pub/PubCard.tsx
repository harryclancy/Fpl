import { Link } from 'react-router-dom';
import { Heart, Bookmark, MapPin } from 'lucide-react';
import type { PubWithComputed } from '../../types';
import { PubImage } from '../ui/PubImage';
import { StatusBadge } from '../ui/StatusBadge';
import { formatDistance } from '../../lib/geo';
import { formatRating } from '../../lib/rating';
import { toggleFavourite, toggleWantToVisit } from '../../db/actions';
import { IconToggle } from '../ui/IconToggle';

export function PubCard({ pub, compact = false }: { pub: PubWithComputed; compact?: boolean }) {
  const isFav = pub.status.favouriteHarry || pub.status.favouriteAva;

  return (
    <Link
      to={`/pub/${pub.id}`}
      className="group block overflow-hidden rounded-card bg-white shadow-card transition-transform active:scale-[0.98]"
    >
      <div className="relative h-32 w-full overflow-hidden">
        <PubImage src={pub.displayImage} name={pub.displayName} className="h-full w-full" />
        <div className="absolute left-2 top-2">
          <StatusBadge visited={pub.status.visited} size="sm" />
        </div>
        <div className="absolute right-2 top-2 flex gap-1.5">
          <IconToggle
            icon={Heart}
            active={isFav}
            onClick={() => toggleFavourite(pub.id, 'harry')}
            label={isFav ? 'Remove favourite' : 'Add to favourites'}
            className="h-8 w-8"
            size={15}
          />
          <IconToggle
            icon={Bookmark}
            active={pub.status.wantToVisit}
            onClick={() => toggleWantToVisit(pub.id)}
            label={pub.status.wantToVisit ? 'Remove from want to visit' : 'Add to want to visit'}
            activeColor="var(--color-want)"
            className="h-8 w-8"
            size={15}
          />
        </div>
      </div>
      <div className="p-3">
        <h3 className="truncate font-display text-[15px] font-semibold leading-tight text-ink">{pub.displayName}</h3>
        <div className="mt-1 flex items-center gap-1 text-xs text-ink-soft">
          <MapPin size={12} />
          <span className="truncate">{pub.displayArea}</span>
          {pub.distanceKm != null && <span className="ml-auto shrink-0 font-medium text-brand-700">{formatDistance(pub.distanceKm)}</span>}
        </div>
        {!compact && (
          <div className="mt-2 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <RatingChip label="H" value={pub.harryReview?.rating ?? null} />
              <RatingChip label="A" value={pub.avaReview?.rating ?? null} />
            </div>
            {pub.combinedRating != null && (
              <span className="rounded-full bg-brand-50 px-2 py-0.5 font-semibold text-brand-800">
                ★ {formatRating(pub.combinedRating)}
              </span>
            )}
          </div>
        )}
      </div>
    </Link>
  );
}

function RatingChip({ label, value }: { label: string; value: number | null }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] font-semibold ${value != null ? 'bg-black/5 text-ink' : 'text-ink-soft/50'}`}>
      {label} {value != null ? formatRating(value) : '–'}
    </span>
  );
}
