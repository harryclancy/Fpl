import { Link } from 'react-router-dom';
import { ExternalLink, Navigation2, Heart, Bookmark } from 'lucide-react';
import type { PubWithComputed } from '../../types';
import { PubImage } from '../ui/PubImage';
import { StatusBadge } from '../ui/StatusBadge';
import { RatingStars } from '../ui/RatingStars';
import { formatDistance } from '../../lib/geo';
import { formatRating } from '../../lib/rating';
import { toggleFavourite, toggleWantToVisit } from '../../db/actions';
import { IconToggle } from '../ui/IconToggle';

export function PubPreviewCard({ pub, onClose }: { pub: PubWithComputed; onClose?: () => void }) {
  const isFav = pub.status.favouriteHarry || pub.status.favouriteAva;
  return (
    <div className="overflow-hidden rounded-card bg-white shadow-pop">
      <div className="relative h-36 w-full">
        <PubImage src={pub.displayImage} name={pub.displayName} className="h-full w-full" />
        <div className="absolute right-2 top-2 flex gap-1.5">
          <IconToggle icon={Heart} active={isFav} onClick={() => toggleFavourite(pub.id, 'harry')} label="Favourite" className="h-8 w-8" size={15} />
          <IconToggle
            icon={Bookmark}
            active={pub.status.wantToVisit}
            onClick={() => toggleWantToVisit(pub.id)}
            label="Want to visit"
            activeColor="var(--color-want)"
            className="h-8 w-8"
            size={15}
          />
        </div>
      </div>
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-display text-lg font-bold text-ink">{pub.displayName}</h3>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-soft">
          <span>{pub.displayArea}</span>
          <span>·</span>
          <span>{pub.district}</span>
          {pub.distanceKm != null && (
            <>
              <span>·</span>
              <span className="font-semibold text-brand-700">{formatDistance(pub.distanceKm)} away</span>
            </>
          )}
        </div>
        <div className="mt-2">
          <StatusBadge visited={pub.status.visited} size="sm" />
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-paper-dim p-2.5">
          <RatingRow label="Harry" value={pub.harryReview?.rating ?? null} />
          <RatingRow label="Ava" value={pub.avaReview?.rating ?? null} />
        </div>
        {pub.combinedRating != null && (
          <div className="mt-2 flex items-center justify-between text-sm">
            <span className="font-medium text-ink-soft">Combined</span>
            <span className="flex items-center gap-1.5 font-bold text-brand-800">
              <RatingStars value={pub.combinedRating} size={14} /> {formatRating(pub.combinedRating)}
            </span>
          </div>
        )}

        <div className="mt-4 grid grid-cols-3 gap-2">
          <Link
            to={`/pub/${pub.id}`}
            onClick={onClose}
            className="col-span-1 flex items-center justify-center rounded-xl bg-brand-800 py-2.5 text-xs font-bold text-white active:scale-95"
          >
            View Pub
          </Link>
          <a
            href={pub.googleMapsUrl}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-center gap-1 rounded-xl border border-line py-2.5 text-xs font-semibold text-ink active:scale-95"
          >
            <ExternalLink size={13} /> Maps
          </a>
          <a
            href={pub.directionsUrl}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-center gap-1 rounded-xl border border-line py-2.5 text-xs font-semibold text-ink active:scale-95"
          >
            <Navigation2 size={13} /> Directions
          </a>
        </div>
      </div>
    </div>
  );
}

function RatingRow({ label, value }: { label: string; value: number | null }) {
  return (
    <div>
      <div className="text-[11px] font-semibold text-ink-soft">{label}</div>
      <div className="mt-0.5 flex items-center gap-1">
        <RatingStars value={value} size={13} />
        <span className="text-xs font-semibold text-ink">{formatRating(value)}</span>
      </div>
    </div>
  );
}
