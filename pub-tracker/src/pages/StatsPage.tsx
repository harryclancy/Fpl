import { useMemo, type ReactNode } from 'react';
import { useLiveQuery } from 'dexie-react-hooks';
import { usePubData } from '../context/PubDataContext';
import { PageHeader } from '../components/layout/PageHeader';
import { ProgressBar } from '../components/ui/ProgressBar';
import { db } from '../db/database';
import { formatRating } from '../lib/rating';
import { Link } from 'react-router-dom';
import { Trophy, Frown, Repeat, MapPinned, CalendarDays, CalendarRange, Camera } from 'lucide-react';

export function StatsPage() {
  const { pubs } = usePubData();
  const visits = useLiveQuery(() => db.visits.toArray(), [], []);
  const drinks = useLiveQuery(() => db.drinks.toArray(), [], []);
  const photos = useLiveQuery(() => db.photos.toArray(), [], []);

  const stats = useMemo(() => {
    const total = pubs.length;
    const visitedPubs = pubs.filter((p) => p.status.visited);
    const visitedCount = visitedPubs.length;
    const pct = total ? (visitedCount / total) * 100 : 0;

    const harryRatings = pubs.filter((p) => p.harryReview?.rating != null).map((p) => p.harryReview!.rating!);
    const avaRatings = pubs.filter((p) => p.avaReview?.rating != null).map((p) => p.avaReview!.rating!);
    const avg = (arr: number[]) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);

    const harryFav = [...pubs].filter((p) => p.harryReview?.rating != null).sort((a, b) => b.harryReview!.rating! - a.harryReview!.rating!)[0];
    const avaFav = [...pubs].filter((p) => p.avaReview?.rating != null).sort((a, b) => b.avaReview!.rating! - a.avaReview!.rating!)[0];

    const rated = pubs.filter((p) => p.combinedRating != null);
    const highest = [...rated].sort((a, b) => b.combinedRating! - a.combinedRating!)[0] ?? null;
    const lowest = [...rated].sort((a, b) => a.combinedRating! - b.combinedRating!)[0] ?? null;

    const mostVisited = [...pubs].sort((a, b) => b.visitCount - a.visitCount)[0];

    const areaVisitCounts = new Map<string, number>();
    for (const p of visitedPubs) areaVisitCounts.set(p.displayArea, (areaVisitCounts.get(p.displayArea) ?? 0) + 1);
    const topAreaEntry = [...areaVisitCounts.entries()].sort((a, b) => b[1] - a[1])[0];
    const areasVisited = new Set(visitedPubs.map((p) => p.displayArea)).size;

    const now = new Date();
    const thisMonthKey = now.toISOString().slice(0, 7);
    const thisYearKey = now.toISOString().slice(0, 4);
    const visitedThisMonth = visitedPubs.filter((p) => p.status.firstVisitDate?.startsWith(thisMonthKey)).length;
    const visitedThisYear = visitedPubs.filter((p) => p.status.firstVisitDate?.startsWith(thisYearKey)).length;

    return {
      total,
      visitedCount,
      pct,
      harryAvg: avg(harryRatings),
      avaAvg: avg(avaRatings),
      harryReviewCount: harryRatings.length,
      avaReviewCount: avaRatings.length,
      harryFav,
      avaFav,
      highest,
      lowest,
      mostVisited: mostVisited && mostVisited.visitCount > 0 ? mostVisited : null,
      topArea: topAreaEntry ? { name: topAreaEntry[0], count: topAreaEntry[1] } : null,
      areasVisited,
      visitedThisMonth,
      visitedThisYear,
    };
  }, [pubs]);

  return (
    <div>
      <PageHeader title="Stats" subtitle="The Dublin Pub Challenge" />
      <div className="space-y-6 px-4 pb-10 pt-4 sm:px-6">
        <section className="rounded-card bg-brand-800 p-5 text-white shadow-pop">
          <div className="font-display text-3xl font-bold">
            {stats.visitedCount} <span className="text-brand-100/70">/ {stats.total}</span>
          </div>
          <div className="mt-0.5 text-sm text-brand-100/90">Dublin pubs visited</div>
          <div className="mt-4">
            <ProgressBar value={stats.pct} color="#e4f6ea" />
          </div>
          <div className="mt-2 text-sm font-semibold">{stats.pct.toFixed(1)}% complete</div>
        </section>

        <section>
          <SectionTitle>Overall</SectionTitle>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Pubs remaining" value={stats.total - stats.visitedCount} />
            <StatTile label="Total visits" value={visits?.length ?? 0} />
            <StatTile label="Drinks logged" value={drinks?.length ?? 0} />
            <StatTile label="Photos taken" value={photos?.length ?? 0} icon={Camera} />
          </div>
        </section>

        <section>
          <SectionTitle>Harry</SectionTitle>
          <div className="grid grid-cols-2 gap-3">
            <StatTile label="Average rating" value={formatRating(stats.harryAvg)} />
            <StatTile label="Reviews written" value={stats.harryReviewCount} />
          </div>
          {stats.harryFav && (
            <FavPubRow label="Harry's favourite" pub={stats.harryFav.displayName} rating={stats.harryFav.harryReview?.rating ?? null} id={stats.harryFav.id} />
          )}
        </section>

        <section>
          <SectionTitle>Ava</SectionTitle>
          <div className="grid grid-cols-2 gap-3">
            <StatTile label="Average rating" value={formatRating(stats.avaAvg)} />
            <StatTile label="Reviews written" value={stats.avaReviewCount} />
          </div>
          {stats.avaFav && (
            <FavPubRow label="Ava's favourite" pub={stats.avaFav.displayName} rating={stats.avaFav.avaReview?.rating ?? null} id={stats.avaFav.id} />
          )}
        </section>

        <section>
          <SectionTitle>Together</SectionTitle>
          <div className="flex flex-col gap-2">
            {stats.highest && (
              <InfoRow icon={Trophy} label="Highest rated" value={`${stats.highest.displayName} · ★ ${formatRating(stats.highest.combinedRating)}`} id={stats.highest.id} />
            )}
            {stats.lowest && stats.lowest.id !== stats.highest?.id && (
              <InfoRow icon={Frown} label="Lowest rated" value={`${stats.lowest.displayName} · ★ ${formatRating(stats.lowest.combinedRating)}`} id={stats.lowest.id} />
            )}
            {stats.mostVisited && (
              <InfoRow icon={Repeat} label="Most visited" value={`${stats.mostVisited.displayName} · ${stats.mostVisited.visitCount} visits`} id={stats.mostVisited.id} />
            )}
            {stats.topArea && <InfoRow icon={MapPinned} label="Most visited area" value={`${stats.topArea.name} · ${stats.topArea.count} pubs`} />}
            <InfoRow icon={MapPinned} label="Areas explored" value={`${stats.areasVisited} areas`} />
            <InfoRow icon={CalendarDays} label="Visited this month" value={`${stats.visitedThisMonth} pubs`} />
            <InfoRow icon={CalendarRange} label="Visited this year" value={`${stats.visitedThisYear} pubs`} />
          </div>
        </section>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="mb-2.5 font-display text-base font-bold text-ink">{children}</h2>;
}

function StatTile({ label, value, icon: Icon }: { label: string; value: string | number; icon?: import('lucide-react').LucideIcon }) {
  return (
    <div className="rounded-card bg-white p-4 shadow-card">
      <div className="flex items-center gap-1.5 text-ink-soft">
        {Icon && <Icon size={13} />}
        <div className="text-[11px] font-semibold uppercase tracking-wide">{label}</div>
      </div>
      <div className="mt-1 font-display text-2xl font-bold text-ink">{value}</div>
    </div>
  );
}

function FavPubRow({ label, pub, rating, id }: { label: string; pub: string; rating: number | null; id: string }) {
  return (
    <Link to={`/pub/${id}`} className="mt-2 flex items-center justify-between rounded-card bg-white p-3.5 shadow-card">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">{label}</div>
        <div className="font-display text-sm font-semibold text-ink">{pub}</div>
      </div>
      <div className="font-bold text-brand-800">★ {formatRating(rating)}</div>
    </Link>
  );
}

function InfoRow({ icon: Icon, label, value, id }: { icon: import('lucide-react').LucideIcon; label: string; value: string; id?: string }) {
  const content = (
    <div className="flex items-center gap-3 rounded-card bg-white p-3.5 shadow-card">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-800">
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">{label}</div>
        <div className="truncate text-sm font-semibold text-ink">{value}</div>
      </div>
    </div>
  );
  return id ? <Link to={`/pub/${id}`}>{content}</Link> : content;
}
