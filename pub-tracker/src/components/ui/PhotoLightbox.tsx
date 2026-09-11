import { AnimatePresence, motion } from 'framer-motion';
import { ChevronLeft, ChevronRight, Trash2, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { blobUrl } from '../../lib/photos';
import type { DrinkPhoto } from '../../types';

interface PhotoLightboxProps {
  photos: DrinkPhoto[];
  startIndex: number;
  onClose: () => void;
  onDelete?: (photo: DrinkPhoto) => void;
}

export function PhotoLightbox({ photos, startIndex, onClose, onDelete }: PhotoLightboxProps) {
  const [index, setIndex] = useState(startIndex);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft') setIndex((i) => Math.max(0, i - 1));
      if (e.key === 'ArrowRight') setIndex((i) => Math.min(photos.length - 1, i + 1));
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [photos.length, onClose]);

  if (!photos.length) return null;
  const photo = photos[Math.min(index, photos.length - 1)];

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[1300] flex flex-col bg-black/95"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        role="dialog"
        aria-modal="true"
        aria-label="Photo viewer"
      >
        <div className="flex items-center justify-between p-4 safe-top">
          <span className="text-sm text-white/70">
            {index + 1} / {photos.length}
          </span>
          <div className="flex items-center gap-2">
            {onDelete && (
              <button
                onClick={() => onDelete(photo)}
                aria-label="Delete photo"
                className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-white active:scale-90"
              >
                <Trash2 size={18} />
              </button>
            )}
            <button
              onClick={onClose}
              aria-label="Close"
              className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-white active:scale-90"
            >
              <X size={20} />
            </button>
          </div>
        </div>
        <div className="relative flex flex-1 items-center justify-center overflow-hidden px-2">
          {index > 0 && (
            <button
              onClick={() => setIndex((i) => i - 1)}
              aria-label="Previous photo"
              className="absolute left-2 z-10 inline-flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white active:scale-90"
            >
              <ChevronLeft />
            </button>
          )}
          <motion.img
            key={photo.id}
            src={blobUrl(photo.blob)}
            alt="Pint photo"
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            className="max-h-full max-w-full rounded-lg object-contain"
          />
          {index < photos.length - 1 && (
            <button
              onClick={() => setIndex((i) => i + 1)}
              aria-label="Next photo"
              className="absolute right-2 z-10 inline-flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white active:scale-90"
            >
              <ChevronRight />
            </button>
          )}
        </div>
        <div className="h-6 safe-bottom" />
      </motion.div>
    </AnimatePresence>
  );
}
