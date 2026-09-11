import { useParams } from 'react-router-dom';
import { useMemo } from 'react';
import { usePubData } from '../context/PubDataContext';
import { PageHeader } from '../components/layout/PageHeader';
import { PubCard } from '../components/pub/PubCard';
import { EmptyState } from '../components/ui/EmptyState';
import { Beer } from 'lucide-react';

export function AreaPage() {
  const { area } = useParams<{ area: string }>();
  const decoded = decodeURIComponent(area ?? '');
  const { pubs } = usePubData();

  const areaPubs = useMemo(() => pubs.filter((p) => p.displayArea === decoded), [pubs, decoded]);
  const visitedCount = areaPubs.filter((p) => p.status.visited).length;

  return (
    <div>
      <PageHeader title={decoded} subtitle={`${visitedCount} / ${areaPubs.length} visited`} back />
      <div className="px-4 pb-8 pt-4 sm:px-6">
        {areaPubs.length === 0 ? (
          <EmptyState icon={Beer} title="No pubs found for this area" />
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {areaPubs.map((pub) => (
              <PubCard key={pub.id} pub={pub} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
