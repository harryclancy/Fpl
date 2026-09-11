import { Link } from 'react-router-dom';
import { Heart, Bookmark } from 'lucide-react';
import type { PubWithComputed } from '../../types';
import { PubImage } from '../ui/PubImage';
import { StatusBadge } from '../ui/StatusBadge';
import { formatDistance } from '../../lib/geo';
import { formatRating } from '../../lib/rating';
import { toggleFavourite, toggleWantToVisit } from '../../db/actions';
import { IconToggle } from '../ui/IconToggle';

export function PubListRow({ pub }: { pub: PubWithComputed }) {
  const isFav = pub.status.favouriteHarry || pub.status.favouriteAva;
  return (
    <Link
      to={`/pub/${pub.id}`}
      className="flex items-center gap-3 rounded-card bg-white p-2.5 shadow-card transition active:scale-[0.99]"
    >
      <PubImage src={pub.displayImage} name={pub.displayName} className="h-16 w-16 shrink-0 rounded-xl" iconSize={20} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="truncate font-display text-[15px] font-semibold text-ink">{pub.displayName}</h3>
        </div>
        <div className="mt-0.5 truncate text-xs text-ink-soft">
          {pub.displayArea} · {pub.district}
        </div>
        <div className="mt-1 flex items-center gap-2">
          <StatusBadge visited={pub.status.visited} size="sm" />
          {pub.combinedRating != null && (
            <span className="text-xs font-semibold text-brand-800">★ {formatRating(pub.combinedRating)}</span>
          )}
          {pub.distanceKm != null && <span className="text-xs text-ink-soft">{formatDistance(pub.distanceKm)}</span>}
        </div>
      </div>
      <div className="flex shrink-0 flex-col gap-1.5">
        <IconToggle icon={Heart} active={isFav} onClick={() => toggleFavourite(pub.id, 'harry')} label="Favourite" className="h-8 w-8" size={14} />
        <IconToggle
          icon={Bookmark}
          active={pub.status.wantToVisit}
          onClick={() => toggleWantToVisit(pub.id)}
          label="Want to visit"
          activeColor="var(--color-want)"
          className="h-8 w-8"
          size={14}
        />
      </div>
    </Link>
  );
}
