import { useMemo, useState } from 'react';
import { usePubData } from '../context/PubDataContext';
import { PageHeader } from '../components/layout/PageHeader';
import { PubCard } from '../components/pub/PubCard';
import { SearchBar } from '../components/pub/SearchBar';
import { EmptyState } from '../components/ui/EmptyState';
import { ProgressBar } from '../components/ui/ProgressBar';
import { ListChecks } from 'lucide-react';

export function VisitedPage() {
  const { pubs } = usePubData();
  const [search, setSearch] = useState('');

  const visited = useMemo(() => {
    const q = search.trim().toLowerCase();
    return pubs
      .filter((p) => p.status.visited)
      .filter((p) => !q || p.displayName.toLowerCase().includes(q) || p.displayArea.toLowerCase().includes(q))
      .sort((a, b) => (b.status.firstVisitDate ?? '').localeCompare(a.status.firstVisitDate ?? ''));
  }, [pubs, search]);

  const total = pubs.length;
  const pct = total ? (pubs.filter((p) => p.status.visited).length / total) * 100 : 0;

  return (
    <div>
      <PageHeader title="Visited" subtitle={`${pubs.filter((p) => p.status.visited).length} / ${total} Dublin pubs`} />
      <div className="space-y-4 px-4 pb-8 pt-4 sm:px-6">
        <div className="rounded-card bg-white p-4 shadow-card">
          <ProgressBar value={pct} />
          <div className="mt-2 text-xs font-medium text-ink-soft">{pct.toFixed(1)}% of Dublin complete</div>
        </div>
        <SearchBar value={search} onChange={setSearch} placeholder="Search visited pubs…" />
        {visited.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title="No visited pubs yet"
            description="Mark a pub as visited from its detail page and it'll show up here in green."
          />
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {visited.map((pub) => (
              <PubCard key={pub.id} pub={pub} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
