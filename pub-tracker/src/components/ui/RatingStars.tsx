import { Star, StarHalf } from 'lucide-react';

interface RatingStarsProps {
  value: number | null;
  size?: number;
  interactive?: boolean;
  onChange?: (value: number) => void;
  className?: string;
}

/** Displays (and optionally edits) a 0-5 rating in half-star steps. */
export function RatingStars({ value, size = 18, interactive = false, onChange, className = '' }: RatingStarsProps) {
  const v = value ?? 0;

  function handleClick(starIndex: number, half: boolean) {
    if (!interactive || !onChange) return;
    const newValue = starIndex + (half ? 0.5 : 1);
    onChange(newValue === value ? 0 : newValue);
  }

  return (
    <div className={`inline-flex items-center gap-0.5 ${className}`} role={interactive ? 'radiogroup' : undefined} aria-label={interactive ? 'Rating' : `Rated ${value ?? 'not rated'} out of 5`}>
      {[0, 1, 2, 3, 4].map((i) => {
        const filled = v >= i + 1;
        const halfFilled = !filled && v >= i + 0.5;
        return (
          <span key={i} className="relative inline-flex" style={{ width: size, height: size }}>
            <Star
              size={size}
              strokeWidth={1.5}
              className={filled || halfFilled ? 'text-amber-500' : 'text-line'}
              fill={filled ? 'currentColor' : 'transparent'}
              stroke={filled || halfFilled ? '#d97706' : '#d7cfc0'}
            />
            {halfFilled && (
              <StarHalf
                size={size}
                strokeWidth={1.5}
                className="absolute inset-0 text-amber-500"
                fill="currentColor"
                stroke="#d97706"
              />
            )}
            {interactive && (
              <>
                <button
                  type="button"
                  aria-label={`Rate ${i + 0.5} out of 5`}
                  className="absolute inset-y-0 left-0 w-1/2 cursor-pointer"
                  onClick={() => handleClick(i, true)}
                />
                <button
                  type="button"
                  aria-label={`Rate ${i + 1} out of 5`}
                  className="absolute inset-y-0 right-0 w-1/2 cursor-pointer"
                  onClick={() => handleClick(i, false)}
                />
              </>
            )}
          </span>
        );
      })}
    </div>
  );
}
