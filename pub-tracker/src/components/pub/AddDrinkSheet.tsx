import { useRef, useState, type ReactNode } from 'react';
import { Camera, ImagePlus, X } from 'lucide-react';
import { BottomSheet } from '../ui/BottomSheet';
import { RatingStars } from '../ui/RatingStars';
import { addDrink } from '../../db/actions';
import { useToast } from '../ui/Toast';

interface AddDrinkSheetProps {
  open: boolean;
  onClose: () => void;
  visitId: string;
}

interface PendingPhoto {
  file: File;
  url: string;
}

export function AddDrinkSheet({ open, onClose, visitId }: AddDrinkSheetProps) {
  const [name, setName] = useState('');
  const [rating, setRating] = useState<number | null>(null);
  const [comment, setComment] = useState('');
  const [photos, setPhotos] = useState<PendingPhoto[]>([]);
  const [saving, setSaving] = useState(false);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const libraryInputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  function addFiles(files: FileList | null) {
    if (!files) return;
    const next = Array.from(files).map((file) => ({ file, url: URL.createObjectURL(file) }));
    setPhotos((p) => [...p, ...next]);
  }

  function removePhoto(index: number) {
    setPhotos((p) => {
      URL.revokeObjectURL(p[index].url);
      return p.filter((_, i) => i !== index);
    });
  }

  function reset() {
    photos.forEach((p) => URL.revokeObjectURL(p.url));
    setName('');
    setRating(null);
    setComment('');
    setPhotos([]);
  }

  async function handleSave() {
    if (!name.trim()) return;
    setSaving(true);
    await addDrink({
      visitId,
      name: name.trim(),
      rating,
      comment: comment.trim() || null,
      photos: photos.map((p) => p.file),
    });
    setSaving(false);
    toast.show('Drink added');
    reset();
    onClose();
  }

  return (
    <BottomSheet
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Add Pint / Drink"
    >
      <div className="space-y-5 pb-4">
        <Field label="Drink name">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Guinness, Rockshore, a hot whiskey…"
            className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm focus:border-brand-600 focus:outline-none"
            autoFocus
          />
        </Field>

        <Field label="Rating (optional)">
          <RatingStars value={rating} interactive size={26} onChange={(v) => setRating(v === 0 ? null : v)} />
        </Field>

        <Field label="Comment (optional)">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            placeholder="Perfectly poured…"
            className="w-full resize-none rounded-xl border border-line bg-white p-3 text-sm focus:border-brand-600 focus:outline-none"
          />
        </Field>

        <Field label="Photos">
          <div className="flex flex-wrap gap-2">
            {photos.map((p, i) => (
              <div key={p.url} className="relative h-20 w-20 overflow-hidden rounded-xl">
                <img src={p.url} alt="" className="h-full w-full object-cover" />
                <button
                  onClick={() => removePhoto(i)}
                  aria-label="Remove photo"
                  className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-black/60 text-white"
                >
                  <X size={11} />
                </button>
              </div>
            ))}
            <button
              onClick={() => cameraInputRef.current?.click()}
              className="flex h-20 w-20 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-line text-ink-soft"
            >
              <Camera size={18} />
              <span className="text-[10px] font-medium">Camera</span>
            </button>
            <button
              onClick={() => libraryInputRef.current?.click()}
              className="flex h-20 w-20 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-line text-ink-soft"
            >
              <ImagePlus size={18} />
              <span className="text-[10px] font-medium">Library</span>
            </button>
          </div>
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = '';
            }}
          />
          <input
            ref={libraryInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = '';
            }}
          />
        </Field>

        <button
          onClick={handleSave}
          disabled={saving || !name.trim()}
          className="w-full rounded-xl bg-brand-800 py-3.5 text-sm font-bold text-white disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save Drink'}
        </button>
      </div>
    </BottomSheet>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-soft">{label}</div>
      {children}
    </div>
  );
}
