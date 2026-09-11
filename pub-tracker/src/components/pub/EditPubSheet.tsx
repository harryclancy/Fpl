import { useState, type ReactNode } from 'react';
import { BottomSheet } from '../ui/BottomSheet';
import { upsertPubEdit } from '../../db/actions';
import { useToast } from '../ui/Toast';
import type { PubWithComputed } from '../../types';
import { blobToDataUrl } from '../../lib/photos';

interface EditPubSheetProps {
  open: boolean;
  onClose: () => void;
  pub: PubWithComputed;
}

export function EditPubSheet({ open, onClose, pub }: EditPubSheetProps) {
  const [name, setName] = useState(pub.displayName);
  const [area, setArea] = useState(pub.displayArea);
  const [address, setAddress] = useState(pub.displayAddress ?? '');
  const [website, setWebsite] = useState(pub.edit?.website ?? pub.website ?? '');
  const [phone, setPhone] = useState(pub.edit?.phone ?? pub.phone ?? '');
  const [notes, setNotes] = useState(pub.edit?.notes ?? '');
  const [imagePreview, setImagePreview] = useState<string | null>(pub.displayImage);
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  async function handleImage(file: File) {
    const dataUrl = await blobToDataUrl(file);
    setImagePreview(dataUrl);
  }

  async function handleSave() {
    setSaving(true);
    await upsertPubEdit(pub.id, {
      name: name.trim() !== pub.name ? name.trim() : undefined,
      area: area.trim() !== pub.area ? area.trim() : undefined,
      address: address.trim() || undefined,
      website: website.trim() || undefined,
      phone: phone.trim() || undefined,
      notes: notes.trim() || undefined,
      imageOverride: imagePreview !== pub.image ? imagePreview ?? undefined : undefined,
    });
    setSaving(false);
    toast.show('Pub details updated');
    onClose();
  }

  return (
    <BottomSheet open={open} onClose={onClose} title="Edit Pub Details" maxHeight="90vh">
      <div className="space-y-4 pb-6">
        <p className="text-xs text-ink-soft">
          Our pub data comes from an open community map and may be missing or slightly out of date. Fix anything below —
          your changes are saved locally and only affect your app.
        </p>
        <Field label="Name">
          <input value={name} onChange={(e) => setName(e.target.value)} className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm" />
        </Field>
        <Field label="Area">
          <input value={area} onChange={(e) => setArea(e.target.value)} className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm" />
        </Field>
        <Field label="Address">
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="Add a street address"
            className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm"
          />
        </Field>
        <Field label="Website">
          <input
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
            placeholder="https://…"
            className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm"
          />
        </Field>
        <Field label="Phone">
          <input value={phone} onChange={(e) => setPhone(e.target.value)} className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm" />
        </Field>
        <Field label="Exterior photo">
          <div className="flex items-center gap-3">
            {imagePreview && <img src={imagePreview} alt="" className="h-16 w-16 rounded-xl object-cover" />}
            <label className="cursor-pointer rounded-full border border-line bg-white px-4 py-2 text-xs font-semibold text-ink">
              Choose photo
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && handleImage(e.target.files[0])}
              />
            </label>
          </div>
        </Field>
        <Field label="Notes">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder="Private notes about this pub"
            className="w-full resize-none rounded-xl border border-line bg-white p-3 text-sm"
          />
        </Field>
        <button onClick={handleSave} disabled={saving} className="w-full rounded-xl bg-brand-800 py-3.5 text-sm font-bold text-white disabled:opacity-60">
          {saving ? 'Saving…' : 'Save Changes'}
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
