import { useNavigate } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';
import type { ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  back?: boolean;
  action?: ReactNode;
}

export function PageHeader({ title, subtitle, back = false, action }: PageHeaderProps) {
  const navigate = useNavigate();
  return (
    <header className="safe-top sticky top-0 z-20 border-b border-line bg-paper/90 px-4 backdrop-blur sm:px-6">
      <div className="flex items-center gap-2 py-4">
        {back && (
          <button
            onClick={() => navigate(-1)}
            aria-label="Go back"
            className="-ml-1.5 inline-flex h-9 w-9 items-center justify-center rounded-full text-ink transition active:scale-90 hover:bg-black/5"
          >
            <ChevronLeft size={22} />
          </button>
        )}
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-display text-xl font-bold text-ink sm:text-2xl">{title}</h1>
          {subtitle && <p className="mt-0.5 truncate text-sm text-ink-soft">{subtitle}</p>}
        </div>
        {action}
      </div>
    </header>
  );
}
