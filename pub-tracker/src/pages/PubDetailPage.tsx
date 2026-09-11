import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import type { LucideIcon } from 'lucide-react';
import {
  Check,
  ChevronLeft,
  ExternalLink,
  Navigation2,
  Heart,
  Bookmark,
  Pencil,
  Plus,
  Scale,
  Phone,
  Globe,
  Clock,
  MapPin,
  CalendarCheck2,
} from 'lucide-react';
import { usePubData } from '../context/PubDataContext';
import { useVisitsForPub } from '../hooks/usePubDetail';
import { PubImage } from '../components/ui/PubImage';
import { StatusBadge } from '../components/ui/StatusBadge';
import { IconToggle } from '../components/ui/IconToggle';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { ReviewCard } from '../components/pub/ReviewCard';
import { PubMiniMap } from '../components/pub/PubMiniMap';
import { AddVisitSheet } from '../components/pub/AddVisitSheet';
import { VisitTimeline } from '../components/pub/VisitTimeline';
import { EditPubSheet } from '../components/pub/EditPubSheet';
import { ComparePubSheet } from '../components/pub/ComparePubSheet';
import { EmptyState } from '../components/ui/EmptyState';
import { setVisited, toggleFavourite, toggleWantToVisit } from '../db/actions';
import { useToast } from '../components/ui/Toast';
import { RatingStars } from '../components/ui/RatingStars';
import { formatRating } from '../lib/rating';
import { format, parseISO } from 'date-fns';

export function PubDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { pubsById } = usePubData();
  const pub = id ? pubsById.get(id) : undefined;
  const visits = useVisitsForPub(id);
  const toast = useToast();

  const [addVisitOpen, setAddVisitOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [confirmUnvisit, setConfirmUnvisit] = useState(false);

  if (!pub) {
    return (
      <div className="p-6">
        <EmptyState icon={CalendarCheck2} title="Pub not found" description="This pub may have been removed." />
      </div>
    );
  }

  const isFav = pub.status.favouriteHarry || pub.status.favouriteAva;

  async function handleVisitedToggle() {
    if (!pub) return;
    if (pub.status.visited) {
      setConfirmUnvisit(true);
    } else {
      await setVisited(pub.id, true);
      toast.show(`${pub.displayName} marked visited!`);
    }
  }

  return (
    <div className="pb-10">
      <div className="relative h-64 w-full sm:h-80">
        <PubImage src={pub.displayImage} name={pub.displayName} className="h-full w-full" iconSize={48} />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/0 to-black/20" />
        <button
          onClick={() => navigate(-1)}
          aria-label="Go back"
          style={{ top: 'calc(env(safe-area-inset-top) + 1rem)' }}
          className="absolute left-4 flex h-10 w-10 items-center justify-center rounded-full bg-white/90 text-ink active:scale-90"
        >
          <ChevronLeft size={22} />
        </button>
        <div className="absolute right-4 flex gap-2" style={{ top: 'calc(env(safe-area-inset-top) + 1rem)' }}>
          <IconToggle icon={Heart} active={isFav} onClick={() => toggleFavourite(pub.id, 'harry')} label="Favourite" />
          <IconToggle
            icon={Bookmark}
            active={pub.status.wantToVisit}
            onClick={() => toggleWantToVisit(pub.id)}
            label="Want to visit"
            activeColor="var(--color-want)"
          />
        </div>
        <div className="absolute inset-x-0 bottom-0 p-4 text-white">
          <StatusBadge visited={pub.status.visited} />
          <h1 className="mt-1.5 font-display text-2xl font-bold drop-shadow-sm sm:text-3xl">{pub.displayName}</h1>
          <p className="mt-0.5 text-sm text-white/85">
            {pub.displayArea} · {pub.district}
          </p>
        </div>
      </div>

      <div className="space-y-6 px-4 pt-5 sm:px-6">
        <motion.button
          whileTap={{ scale: 0.97 }}
          onClick={handleVisitedToggle}
          className={`flex w-full items-center justify-center gap-2 rounded-card py-4 text-base font-bold shadow-card transition ${
            pub.status.visited ? 'bg-visited text-white' : 'border-2 border-dashed border-unvisited bg-unvisited-bg text-unvisited-dark'
          }`}
          style={pub.status.visited ? { background: 'var(--color-visited)' } : undefined}
        >
          <Check size={20} strokeWidth={2.6} />
          {pub.status.visited ? "We've been here ✓" : "We've been here?"}
        </motion.button>

        {pub.status.visited && pub.status.firstVisitDate && (
          <p className="-mt-3 text-center text-xs text-ink-soft">
            First visited {format(parseISO(pub.status.firstVisitDate), 'd MMMM yyyy')}
          </p>
        )}

        <div className="grid grid-cols-3 gap-2">
          <ActionLink href={pub.directionsUrl} icon={Navigation2} label="Directions" />
          <ActionLink href={pub.googleMapsUrl} icon={ExternalLink} label="Google Maps" />
          <ActionButton icon={Scale} label="Compare" onClick={() => setCompareOpen(true)} />
        </div>

        <PubMiniMap pub={pub} />

        <div className="rounded-card bg-white p-4 shadow-card">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-sm font-bold text-ink">Details</h2>
            <button onClick={() => setEditOpen(true)} className="flex items-center gap-1 text-xs font-semibold text-brand-700">
              <Pencil size={12} /> Edit
            </button>
          </div>
          <div className="mt-3 space-y-2 text-sm text-ink-soft">
            <DetailRow icon={MapPin} text={pub.displayAddress ?? 'Address not on file yet — tap Edit to add it.'} />
            {(pub.edit?.website || pub.website) && (
              <DetailRow icon={Globe} text={pub.edit?.website || pub.website || ''} link={pub.edit?.website || pub.website || undefined} />
            )}
            {(pub.edit?.phone || pub.phone) && <DetailRow icon={Phone} text={pub.edit?.phone || pub.phone || ''} />}
            <DetailRow icon={Clock} text={pub.openingHours ?? 'Opening hours not confirmed — check Google Maps.'} />
          </div>
        </div>

        <div>
          <h2 className="mb-2.5 font-display text-base font-bold text-ink">Ratings &amp; Reviews</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <ReviewCard pubId={pub.id} person="harry" review={pub.harryReview} />
            <ReviewCard pubId={pub.id} person="ava" review={pub.avaReview} />
          </div>
          {pub.combinedRating != null && (
            <div className="mt-3 flex items-center justify-between rounded-card bg-brand-50 p-3.5">
              <span className="text-sm font-semibold text-brand-900">Combined Rating</span>
              <span className="flex items-center gap-1.5 font-bold text-brand-800">
                <RatingStars value={pub.combinedRating} size={16} /> {formatRating(pub.combinedRating)}
              </span>
            </div>
          )}
        </div>

        <div>
          <div className="mb-2.5 flex items-center justify-between">
            <h2 className="font-display text-base font-bold text-ink">Visit &amp; Pint Journal</h2>
            <button
              onClick={() => setAddVisitOpen(true)}
              className="flex items-center gap-1.5 rounded-full bg-brand-800 px-3.5 py-2 text-xs font-bold text-white active:scale-95"
            >
              <Plus size={14} /> Add Visit
            </button>
          </div>
          {visits && visits.length > 0 ? (
            <VisitTimeline visits={visits} />
          ) : (
            <EmptyState
              icon={CalendarCheck2}
              title="No visits logged yet"
              description="Add a visit to start building your pint journal with photos and notes."
            />
          )}
        </div>
      </div>

      <AddVisitSheet open={addVisitOpen} onClose={() => setAddVisitOpen(false)} pubId={pub.id} />
      <EditPubSheet open={editOpen} onClose={() => setEditOpen(false)} pub={pub} />
      <ComparePubSheet open={compareOpen} onClose={() => setCompareOpen(false)} from={pub} />

      <ConfirmDialog
        open={confirmUnvisit}
        title="Mark as not visited?"
        description="Your visit history, photos, and reviews for this pub are kept safe — this only changes the visited status."
        confirmLabel="Mark not visited"
        onCancel={() => setConfirmUnvisit(false)}
        onConfirm={async () => {
          await setVisited(pub.id, false);
          setConfirmUnvisit(false);
          toast.show('Marked as not visited');
        }}
      />
    </div>
  );
}

function ActionLink({ href, icon: Icon, label }: { href: string; icon: LucideIcon; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="flex flex-col items-center gap-1.5 rounded-card border border-line bg-white py-3 text-ink shadow-card active:scale-95"
    >
      <Icon size={18} />
      <span className="text-[11px] font-semibold">{label}</span>
    </a>
  );
}

function ActionButton({ icon: Icon, label, onClick }: { icon: LucideIcon; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col items-center gap-1.5 rounded-card border border-line bg-white py-3 text-ink shadow-card active:scale-95"
    >
      <Icon size={18} />
      <span className="text-[11px] font-semibold">{label}</span>
    </button>
  );
}

function DetailRow({ icon: Icon, text, link }: { icon: LucideIcon; text: string; link?: string }) {
  const content = (
    <div className="flex items-start gap-2.5">
      <Icon size={15} className="mt-0.5 shrink-0 text-ink-soft/70" />
      <span className={link ? 'text-brand-700 underline' : ''}>{text}</span>
    </div>
  );
  return link ? (
    <a href={link.startsWith('http') ? link : `https://${link}`} target="_blank" rel="noreferrer">
      {content}
    </a>
  ) : (
    content
  );
}
