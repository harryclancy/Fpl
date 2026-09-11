import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useLiveQuery } from 'dexie-react-hooks';
import { Navigation2, Plus, Trash2, X } from 'lucide-react';
import { db } from '../db/database';
import { PageHeader } from '../components/layout/PageHeader';
import { usePubData } from '../context/PubDataContext';
import { DraggableList } from '../components/ui/DraggableList';
import { PubImage } from '../components/ui/PubImage';
import { PubMultiSelectSheet } from '../components/pub/PubMultiSelectSheet';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { updateCrawlStops, renameCrawl, deleteCrawl } from '../db/actions';
import { directionsForCrawl, directionsBetween } from '../lib/googleMaps';
import { haversineKm, formatDistance } from '../lib/geo';
import { useToast } from '../components/ui/Toast';

export function CrawlDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const crawl = useLiveQuery(() => (id ? db.crawls.get(id) : undefined), [id]);
  const { pubsById } = usePubData();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState('');
  const toast = useToast();

  const stopPubs = useMemo(() => {
    if (!crawl) return [];
    return crawl.stops
      .sort((a, b) => a.order - b.order)
      .map((s) => pubsById.get(s.pubId))
      .filter((p): p is NonNullable<typeof p> => !!p);
  }, [crawl, pubsById]);

  if (!crawl) {
    return (
      <div>
        <PageHeader title="Pub Crawl" back />
        <p className="px-4 py-10 text-center text-sm text-ink-soft">This crawl couldn't be found.</p>
      </div>
    );
  }

  const directionsUrl = directionsForCrawl(stopPubs.map((p) => ({ lat: p.lat, lon: p.lon })));

  async function handleReorder(newOrder: typeof stopPubs) {
    if (!id) return;
    await updateCrawlStops(id, newOrder.map((p) => p.id));
  }

  async function removeStop(pubId: string) {
    if (!id) return;
    await updateCrawlStops(id, stopPubs.filter((p) => p.id !== pubId).map((p) => p.id));
    toast.show('Removed from crawl');
  }

  async function addStops(ids: string[]) {
    if (!id) return;
    const existing = stopPubs.map((p) => p.id);
    const merged = [...existing, ...ids.filter((i) => !existing.includes(i))];
    await updateCrawlStops(id, merged);
    setPickerOpen(false);
  }

  return (
    <div>
      <PageHeader
        title={crawl.name}
        subtitle={`${stopPubs.length} stops`}
        back
        action={
          <button onClick={() => { setNameDraft(crawl.name); setEditingName(true); }} className="text-xs font-semibold text-brand-700">
            Rename
          </button>
        }
      />

      <div className="space-y-5 px-4 pb-10 pt-4 sm:px-6">
        {stopPubs.length >= 2 && directionsUrl && (
          <a
            href={directionsUrl}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-center gap-2 rounded-card bg-brand-800 py-3.5 text-sm font-bold text-white shadow-card active:scale-95"
          >
            <Navigation2 size={17} /> Open Full Route in Google Maps
          </a>
        )}

        {stopPubs.length === 0 ? (
          <p className="rounded-card border border-dashed border-line bg-white/60 p-6 text-center text-sm text-ink-soft">
            No stops yet — add pubs to build your route.
          </p>
        ) : (
          <DraggableList
            items={stopPubs}
            keyFn={(p) => p.id}
            onReorder={handleReorder}
            renderItem={(pub, index) => (
              <div className="flex items-center gap-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-800 text-xs font-bold text-white">
                  {index + 1}
                </div>
                <PubImage src={pub.displayImage} name={pub.displayName} className="h-11 w-11 shrink-0 rounded-lg" iconSize={14} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-ink">{pub.displayName}</div>
                  <div className="truncate text-xs text-ink-soft">{pub.displayArea}</div>
                  {index < stopPubs.length - 1 && (
                    <div className="mt-0.5 flex items-center gap-1 text-[11px] text-brand-700">
                      <a
                        href={directionsBetween({ lat: pub.lat, lon: pub.lon }, { lat: stopPubs[index + 1].lat, lon: stopPubs[index + 1].lon })}
                        target="_blank"
                        rel="noreferrer"
                        className="underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {formatDistance(haversineKm({ lat: pub.lat, lon: pub.lon }, { lat: stopPubs[index + 1].lat, lon: stopPubs[index + 1].lon }))} to next
                      </a>
                    </div>
                  )}
                </div>
                <button onClick={() => removeStop(pub.id)} aria-label={`Remove ${pub.displayName}`} className="shrink-0 text-ink-soft/50 hover:text-red-600">
                  <X size={16} />
                </button>
              </div>
            )}
          />
        )}

        <button
          onClick={() => setPickerOpen(true)}
          className="flex w-full items-center justify-center gap-2 rounded-card border border-dashed border-line py-3.5 text-sm font-semibold text-brand-700"
        >
          <Plus size={16} /> Add pubs to this crawl
        </button>

        <button
          onClick={() => setConfirmDelete(true)}
          className="flex w-full items-center justify-center gap-2 py-2 text-sm font-semibold text-red-600"
        >
          <Trash2 size={15} /> Delete Crawl
        </button>
      </div>

      <PubMultiSelectSheet open={pickerOpen} onClose={() => setPickerOpen(false)} onConfirm={addStops} title="Add Pubs to Crawl" />

      {editingName && (
        <ConfirmDialog
          open={editingName}
          title="Rename crawl"
          description={
            <input
              autoFocus
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              className="mt-2 h-11 w-full rounded-xl border border-line bg-white px-3 text-sm"
            />
          }
          confirmLabel="Save"
          onCancel={() => setEditingName(false)}
          onConfirm={async () => {
            if (id && nameDraft.trim()) await renameCrawl(id, nameDraft.trim());
            setEditingName(false);
          }}
        />
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this pub crawl?"
        description="This can't be undone. Your visits and ratings for these pubs are unaffected."
        confirmLabel="Delete"
        destructive
        onCancel={() => setConfirmDelete(false)}
        onConfirm={async () => {
          if (id) await deleteCrawl(id);
          navigate('/crawls');
        }}
      />
    </div>
  );
}
