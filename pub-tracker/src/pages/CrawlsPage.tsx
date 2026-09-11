import { useState } from 'react';
import { useLiveQuery } from 'dexie-react-hooks';
import { Link, useNavigate } from 'react-router-dom';
import { Plus, Route, Trash2 } from 'lucide-react';
import { db } from '../db/database';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState } from '../components/ui/EmptyState';
import { PubMultiSelectSheet } from '../components/pub/PubMultiSelectSheet';
import { BottomSheet } from '../components/ui/BottomSheet';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { createCrawl, deleteCrawl } from '../db/actions';
import { usePubData } from '../context/PubDataContext';

export function CrawlsPage() {
  const crawls = useLiveQuery(() => db.crawls.orderBy('updatedAt').reverse().toArray(), [], []);
  const { pubsById } = usePubData();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingIds, setPendingIds] = useState<string[] | null>(null);
  const [name, setName] = useState('');
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const navigate = useNavigate();

  async function handleCreate() {
    if (!pendingIds || !name.trim()) return;
    const id = await createCrawl(name.trim(), pendingIds);
    setPendingIds(null);
    setName('');
    navigate(`/crawls/${id}`);
  }

  return (
    <div>
      <PageHeader
        title="Pub Crawls"
        subtitle="Plan a route, then follow it in Google Maps"
        action={
          <button
            onClick={() => setPickerOpen(true)}
            className="flex items-center gap-1.5 rounded-full bg-brand-800 px-3.5 py-2 text-xs font-bold text-white active:scale-95"
          >
            <Plus size={14} /> New Crawl
          </button>
        }
      />
      <div className="px-4 pb-8 pt-4 sm:px-6">
        {!crawls || crawls.length === 0 ? (
          <EmptyState
            icon={Route}
            title="No pub crawls yet"
            description="Pick a handful of pubs, put them in order, and get one-tap directions between every stop."
            action={
              <button onClick={() => setPickerOpen(true)} className="rounded-full bg-brand-800 px-5 py-2.5 text-sm font-semibold text-white">
                Create a crawl
              </button>
            }
          />
        ) : (
          <div className="flex flex-col gap-3">
            {crawls.map((crawl) => (
              <div key={crawl.id} className="flex items-center gap-3 rounded-card bg-white p-4 shadow-card">
                <Link to={`/crawls/${crawl.id}`} className="min-w-0 flex-1">
                  <div className="font-display text-base font-bold text-ink">{crawl.name}</div>
                  <div className="mt-1 truncate text-xs text-ink-soft">
                    {crawl.stops
                      .slice(0, 4)
                      .map((s) => pubsById.get(s.pubId)?.displayName ?? '—')
                      .join(' → ')}
                    {crawl.stops.length > 4 ? '…' : ''}
                  </div>
                  <div className="mt-1 text-[11px] font-semibold text-brand-700">{crawl.stops.length} stops</div>
                </Link>
                <button onClick={() => setConfirmDelete(crawl.id)} aria-label={`Delete ${crawl.name}`} className="text-ink-soft/50 hover:text-red-600">
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <PubMultiSelectSheet
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onConfirm={(ids) => {
          setPickerOpen(false);
          setPendingIds(ids);
        }}
        title="Choose Pubs for Your Crawl"
      />

      <BottomSheet open={!!pendingIds} onClose={() => setPendingIds(null)} title="Name Your Crawl">
        <div className="space-y-4 pb-4">
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Camden Street Crawl"
            className="h-11 w-full rounded-xl border border-line bg-white px-3 text-sm focus:border-brand-600 focus:outline-none"
          />
          <p className="text-xs text-ink-soft">{pendingIds?.length ?? 0} pubs selected. You can reorder them after creating the crawl.</p>
          <button onClick={handleCreate} disabled={!name.trim()} className="w-full rounded-xl bg-brand-800 py-3.5 text-sm font-bold text-white disabled:opacity-40">
            Create Crawl
          </button>
        </div>
      </BottomSheet>

      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete this crawl?"
        description="This only deletes the saved route — it doesn't affect your visits, ratings or photos."
        confirmLabel="Delete crawl"
        destructive
        onCancel={() => setConfirmDelete(null)}
        onConfirm={async () => {
          if (confirmDelete) await deleteCrawl(confirmDelete);
          setConfirmDelete(null);
        }}
      />
    </div>
  );
}
