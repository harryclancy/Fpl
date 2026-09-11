import { useMemo, useState } from 'react';
import { usePubData } from '../context/PubDataContext';
import { PageHeader } from '../components/layout/PageHeader';
import { PubCard } from '../components/pub/PubCard';
import { EmptyState } from '../components/ui/EmptyState';
import { Heart } from 'lucide-react';
import { Link } from 'react-router-dom';

type Who = 'both' | 'harry' | 'ava';

export function FavouritesPage() {
  const { pubs } = usePubData();
  const [who, setWho] = useState<Who>('both');

  const list = useMemo(() => {
    return pubs.filter((p) => {
      if (who === 'harry') return p.status.favouriteHarry;
      if (who === 'ava') return p.status.favouriteAva;
      return p.status.favouriteHarry || p.status.favouriteAva;
    });
  }, [pubs, who]);

  return (
    <div>
      <PageHeader title="Favourites" subtitle={`${list.length} favourite pubs`} />
      <div className="space-y-4 px-4 pb-8 pt-4 sm:px-6">
        <div className="grid grid-cols-3 gap-1 rounded-xl bg-black/5 p-1">
          {(['both', 'harry', 'ava'] as Who[]).map((w) => (
            <button
              key={w}
              onClick={() => setWho(w)}
              className={`rounded-lg py-2 text-xs font-semibold capitalize transition ${who === w ? 'bg-white text-ink shadow-card' : 'text-ink-soft'}`}
            >
              {w === 'both' ? 'Either' : w}
            </button>
          ))}
        </div>

        {list.length === 0 ? (
          <EmptyState
            icon={Heart}
            title="No favourites yet"
            description="Tap the heart icon on any pub to add it here."
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
