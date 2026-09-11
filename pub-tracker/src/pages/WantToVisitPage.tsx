import { useMemo } from 'react';
import { usePubData } from '../context/PubDataContext';
import { PageHeader } from '../components/layout/PageHeader';
import { PubCard } from '../components/pub/PubCard';
import { EmptyState } from '../components/ui/EmptyState';
import { Bookmark } from 'lucide-react';
import { Link } from 'react-router-dom';

export function WantToVisitPage() {
  const { pubs } = usePubData();
  const list = useMemo(() => pubs.filter((p) => p.status.wantToVisit), [pubs]);

  return (
    <div>
      <PageHeader title="Want to Visit" subtitle={`${list.length} pubs shortlisted`} />
      <div className="px-4 pb-8 pt-4 sm:px-6">
        {list.length === 0 ? (
          <EmptyState
            icon={Bookmark}
            title="Your shortlist is empty"
            description="Tap the bookmark icon on any pub to save it here for your next night out."
            action={
              <Link to="/pubs" className="rounded-full bg-brand-800 px-5 py-2.5 text-sm font-semibold text-white">
                Browse all pubs
              </Link>
            }
          />
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {list.map((pub) => (
              <PubCard key={pub.id} pub={pub} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
