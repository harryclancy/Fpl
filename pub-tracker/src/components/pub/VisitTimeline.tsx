import { useState } from 'react';
import { format, parseISO } from 'date-fns';
import { Plus, Trash2, Users } from 'lucide-react';
import type { VisitWithDrinks } from '../../hooks/usePubDetail';
import type { Drink, DrinkPhoto, PersonOrBoth } from '../../types';
import { RatingStars } from '../ui/RatingStars';
import { blobUrl } from '../../lib/photos';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { PhotoLightbox } from '../ui/PhotoLightbox';
import { AddDrinkSheet } from './AddDrinkSheet';
import { deleteDrink, deletePhoto, deleteVisit } from '../../db/actions';
import { useToast } from '../ui/Toast';

const WHO_LABEL: Record<PersonOrBoth, string> = { both: 'Harry + Ava', harry: 'Harry', ava: 'Ava' };

interface LightboxState {
  photos: DrinkPhoto[];
  index: number;
}

export function VisitTimeline({ visits }: { visits: VisitWithDrinks[] }) {
  const [addDrinkFor, setAddDrinkFor] = useState<string | null>(null);
  const [confirmDeleteVisit, setConfirmDeleteVisit] = useState<string | null>(null);
  const [confirmDeleteDrink, setConfirmDeleteDrink] = useState<Drink | null>(null);
  const [lightbox, setLightbox] = useState<LightboxState | null>(null);
  const toast = useToast();

  if (visits.length === 0) return null;

  return (
    <div className="space-y-4">
      {visits.map((visit) => (
        <div key={visit.id} className="rounded-card bg-white p-4 shadow-card">
          <div className="flex items-start justify-between">
            <div>
              <div className="font-display text-sm font-bold text-ink">
                {format(parseISO(visit.date), 'd MMMM yyyy')}
                {visit.time && <span className="ml-1.5 font-sans text-xs font-medium text-ink-soft">{visit.time}</span>}
              </div>
              <div className="mt-0.5 flex items-center gap-1 text-xs text-ink-soft">
                <Users size={12} /> {WHO_LABEL[visit.who]}
              </div>
            </div>
            <button
              onClick={() => setConfirmDeleteVisit(visit.id)}
              aria-label="Delete visit"
              className="text-ink-soft/60 transition hover:text-red-600"
            >
              <Trash2 size={15} />
            </button>
          </div>

          {visit.notes && <p className="mt-2.5 text-sm leading-relaxed text-ink-soft">{visit.notes}</p>}

          {visit.drinks.length > 0 && (
            <div className="mt-3 space-y-3">
              {visit.drinks.map((drink) => (
                <div key={drink.id} className="rounded-xl bg-paper-dim/60 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-sm font-semibold text-ink">{drink.name}</div>
                      {drink.rating != null && <RatingStars value={drink.rating} size={12} className="mt-0.5" />}
                    </div>
                    <button
                      onClick={() => setConfirmDeleteDrink(drink)}
                      aria-label={`Delete ${drink.name}`}
                      className="text-ink-soft/50 transition hover:text-red-600"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                  {drink.comment && <p className="mt-1 text-xs text-ink-soft">{drink.comment}</p>}
                  {drink.photos.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {drink.photos.map((photo, i) => (
                        <button
                          key={photo.id}
                          onClick={() => setLightbox({ photos: drink.photos, index: i })}
                          className="h-16 w-16 overflow-hidden rounded-lg"
                        >
                          <img src={blobUrl(photo.thumbBlob)} alt={`${drink.name} photo`} className="h-full w-full object-cover" loading="lazy" />
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <button
            onClick={() => setAddDrinkFor(visit.id)}
            className="mt-3 flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-xs font-semibold text-brand-700"
          >
            <Plus size={13} /> Add Pint / Drink
          </button>
        </div>
      ))}

      {addDrinkFor && <AddDrinkSheet open={!!addDrinkFor} onClose={() => setAddDrinkFor(null)} visitId={addDrinkFor} />}

      <ConfirmDialog
        open={!!confirmDeleteVisit}
        title="Delete this visit?"
        description="This removes the visit, its notes, and any drinks/photos logged for it. This cannot be undone."
        confirmLabel="Delete visit"
        destructive
        onCancel={() => setConfirmDeleteVisit(null)}
        onConfirm={async () => {
          if (confirmDeleteVisit) {
            await deleteVisit(confirmDeleteVisit);
            toast.show('Visit deleted');
          }
          setConfirmDeleteVisit(null);
        }}
      />

      <ConfirmDialog
        open={!!confirmDeleteDrink}
        title={`Delete ${confirmDeleteDrink?.name ?? 'this drink'}?`}
        description="Its photos will be removed too. This cannot be undone."
        confirmLabel="Delete drink"
        destructive
        onCancel={() => setConfirmDeleteDrink(null)}
        onConfirm={async () => {
          if (confirmDeleteDrink) {
            await deleteDrink(confirmDeleteDrink.id);
            toast.show('Drink deleted');
          }
          setConfirmDeleteDrink(null);
        }}
      />

      {lightbox && (
        <PhotoLightbox
          photos={lightbox.photos}
          startIndex={lightbox.index}
          onClose={() => setLightbox(null)}
          onDelete={async (photo) => {
            await deletePhoto(photo.id);
            toast.show('Photo deleted');
            setLightbox((lb) => {
              if (!lb) return null;
              const remaining = lb.photos.filter((p) => p.id !== photo.id);
              if (remaining.length === 0) return null;
              return { photos: remaining, index: Math.min(lb.index, remaining.length - 1) };
            });
          }}
        />
      )}
    </div>
  );
}
