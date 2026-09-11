import { Link } from 'react-router-dom';
import type { PubWithComputed } from '../../types';
import { PubCard } from './PubCard';

interface PubScrollRowProps {
  title: string;
  pubs: PubWithComputed[];
  seeAllHref?: string;
  emptyText?: string;
}

export function PubScrollRow({ title, pubs, seeAllHref, emptyText }: PubScrollRowProps) {
  return (
    <section>
      <div className="mb-2.5 flex items-center justify-between px-4 sm:px-6">
        <h2 className="font-display text-base font-bold text-ink">{title}</h2>
        {seeAllHref && pubs.length > 0 && (
          <Link to={seeAllHref} className="text-xs font-semibold text-brand-700">
            See all
          </Link>
        )}
      </div>
      {pubs.length === 0 ? (
        <p className="px-4 text-sm text-ink-soft sm:px-6">{emptyText}</p>
      ) : (
        <div className="no-scrollbar flex gap-3 overflow-x-auto px-4 pb-1 sm:px-6">
          {pubs.map((pub) => (
            <div key={pub.id} className="w-40 shrink-0">
              <PubCard pub={pub} compact />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
