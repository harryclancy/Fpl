import { useEffect, useState } from 'react';
import { RatingStars } from '../ui/RatingStars';
import { upsertReview } from '../../db/actions';
import type { Person, Review } from '../../types';
import { Check } from 'lucide-react';

interface ReviewCardProps {
  pubId: string;
  person: Person;
  review: Review | null;
}

const PERSON_LABEL: Record<Person, string> = { harry: 'Harry', ava: 'Ava' };

export function ReviewCard({ pubId, person, review }: ReviewCardProps) {
  const [rating, setRating] = useState<number | null>(review?.rating ?? null);
  const [comment, setComment] = useState(review?.comment ?? '');
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setRating(review?.rating ?? null);
    setComment(review?.comment ?? '');
    setDirty(false);
  }, [review?.rating, review?.comment]);

  async function save(nextRating: number | null, nextComment: string) {
    await upsertReview(pubId, person, nextRating, nextComment.trim() || null);
    setSaved(true);
    setDirty(false);
    setTimeout(() => setSaved(false), 1500);
  }

  return (
    <div className="rounded-card bg-white p-4 shadow-card">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-display text-sm font-bold text-ink">{PERSON_LABEL[person]}</h3>
        {saved && (
          <span className="flex items-center gap-1 text-[11px] font-semibold text-visited">
            <Check size={12} /> Saved
          </span>
        )}
      </div>
      <RatingStars
        value={rating}
        interactive
        size={24}
        onChange={(v) => {
          const next = v === 0 ? null : v;
          setRating(next);
          save(next, comment);
        }}
      />
      <textarea
        value={comment}
        onChange={(e) => {
          setComment(e.target.value);
          setDirty(true);
        }}
        onBlur={() => dirty && save(rating, comment)}
        placeholder={`${PERSON_LABEL[person]}'s thoughts on this pub…`}
        rows={2}
        className="mt-3 w-full resize-none rounded-xl border border-line bg-paper-dim/50 p-2.5 text-sm text-ink placeholder:text-ink-soft/60 focus:border-brand-600 focus:outline-none"
      />
    </div>
  );
}
