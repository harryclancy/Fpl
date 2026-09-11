import { useState, type ReactNode } from 'react';
import { BottomSheet } from '../ui/BottomSheet';
import { addVisit } from '../../db/actions';
import type { PersonOrBoth } from '../../types';
import { useToast } from '../ui/Toast';

interface AddVisitSheetProps {
  open: boolean;
  onClose: () => void;
  pubId: string;
}

const WHO_OPTIONS: { value: PersonOrBoth; label: string }[] = [
  { value: 'both', label: 'Both' },
  { value: 'harry', label: 'Harry' },
  { value: 'ava', label: 'Ava' },
];

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

export function AddVisitSheet({ open, onClose, pubId }: AddVisitSheetProps) {
  const [date, setDate] = useState(todayStr());
  const [time, setTime] = useState('');
  const [who, setWho] = useState<PersonOrBoth>('both');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  async function handleSave() {
    setSaving(true);
    await addVisit({ pubId, date, time: time || null, who, notes: notes.trim() || null });
    setSaving(false);
    toast.show('Visit added');
    setDate(todayStr());
    setTime('');
    setWho('both');
    setNotes('');
    onClose();
  }

  return (
    <BottomSheet open={open} onClose={onClose} title="Add Visit">
      <div className="space-y-5 pb-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date">
            <input
              type="date"
              value={date}
              max={todayStr()}
              onChange={(e) => setDate(e.target.value)}
              className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm"
            />
          </Field>
          <Field label="Time (optional)">
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm"
            />
          </Field>
        </div>

        <Field label="Who was there">
          <div className="grid grid-cols-3 gap-2">
            {WHO_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setWho(opt.value)}
                className={`rounded-xl border py-2.5 text-sm font-semibold ${
                  who === opt.value ? 'border-brand-700 bg-brand-800 text-white' : 'border-line bg-white text-ink'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Notes (optional)">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Great atmosphere before the match…"
            className="w-full resize-none rounded-xl border border-line bg-white p-3 text-sm placeholder:text-ink-soft/60 focus:border-brand-600 focus:outline-none"
          />
        </Field>

        <button
          onClick={handleSave}
          disabled={saving}
          className="w-full rounded-xl bg-brand-800 py-3.5 text-sm font-bold text-white disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save Visit'}
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
