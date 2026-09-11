import { useRef, useState } from 'react';
import { Download, Upload, Info, ShieldCheck } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { exportBackup, downloadBackup, parseBackupFile, importBackup, summarizeBackup, type BackupFile } from '../lib/backup';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { useToast } from '../components/ui/Toast';
import { usePubData } from '../context/PubDataContext';

export function SettingsPage() {
  const [exporting, setExporting] = useState(false);
  const [pendingImport, setPendingImport] = useState<BackupFile | null>(null);
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const { pubs } = usePubData();

  async function handleExport() {
    setExporting(true);
    try {
      const blob = await exportBackup();
      downloadBackup(blob);
      toast.show('Backup downloaded');
    } finally {
      setExporting(false);
    }
  }

  async function handleFileSelected(file: File) {
    try {
      const backup = await parseBackupFile(file);
      setPendingImport(backup);
    } catch (err) {
      toast.show(err instanceof Error ? err.message : 'Could not read that file');
    }
  }

  async function confirmImport() {
    if (!pendingImport) return;
    setImporting(true);
    try {
      await importBackup(pendingImport);
      toast.show('Backup restored');
    } finally {
      setImporting(false);
      setPendingImport(null);
    }
  }

  const summary = pendingImport ? summarizeBackup(pendingImport) : null;

  return (
    <div>
      <PageHeader title="Settings" subtitle="Backup, restore &amp; about" />
      <div className="space-y-6 px-4 pb-10 pt-4 sm:px-6">
        <section className="rounded-card bg-white p-4 shadow-card">
          <h2 className="font-display text-sm font-bold text-ink">Backup &amp; Restore</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-soft">
            There's no account or login — everything lives on this device. Export a backup regularly (especially before
            switching phones) so your visits, ratings and pint photos are never lost.
          </p>
          <div className="mt-4 flex flex-col gap-2.5 sm:flex-row">
            <button
              onClick={handleExport}
              disabled={exporting}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-brand-800 py-3 text-sm font-bold text-white disabled:opacity-60"
            >
              <Download size={16} /> {exporting ? 'Preparing…' : 'Export Backup'}
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-line bg-white py-3 text-sm font-bold text-ink"
            >
              <Upload size={16} /> Import Backup
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFileSelected(file);
                e.target.value = '';
              }}
            />
          </div>
        </section>

        <section className="rounded-card bg-white p-4 shadow-card">
          <div className="flex items-center gap-2">
            <Info size={15} className="text-brand-700" />
            <h2 className="font-display text-sm font-bold text-ink">About this data</h2>
          </div>
          <ul className="mt-2.5 space-y-1.5 text-xs leading-relaxed text-ink-soft">
            <li>• {pubs.length} pubs across Dublin city &amp; county, sourced from an open OpenStreetMap-derived community map.</li>
            <li>• Locations are real; addresses, phone numbers and photos are often missing — use "Edit Pub Details" on any pub to fill them in.</li>
            <li>• Areas and postal districts are estimated from coordinates and may need correcting for pubs near a boundary.</li>
            <li>• We never claim a pub is open or closed without confirming it — check Google Maps if you're heading out.</li>
          </ul>
        </section>

        <section className="rounded-card bg-white p-4 shadow-card">
          <div className="flex items-center gap-2">
            <ShieldCheck size={15} className="text-brand-700" />
            <h2 className="font-display text-sm font-bold text-ink">Privacy</h2>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-soft">
            No sign-up, no server, no tracking. Your reviews and photos stay in this browser's storage unless you export
            them yourself.
          </p>
        </section>
      </div>

      <ConfirmDialog
        open={!!pendingImport}
        title="Replace your data with this backup?"
        description={
          summary && (
            <span>
              This file contains {summary.visitedPubs} visited pubs, {summary.visits} visits, {summary.drinks} drinks,{' '}
              {summary.photos} photos and {summary.crawls} crawls. Importing will <strong>replace</strong> everything
              currently on this device. This can't be undone — export your current data first if you're unsure.
            </span>
          )
        }
        confirmLabel={importing ? 'Restoring…' : 'Replace & Import'}
        destructive
        onCancel={() => setPendingImport(null)}
        onConfirm={confirmImport}
      />
    </div>
  );
}
