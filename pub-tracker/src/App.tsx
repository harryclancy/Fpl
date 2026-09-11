import { lazy, Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { PubDataProvider } from './context/PubDataContext';
import { ToastProvider } from './components/ui/Toast';
import { AppShell } from './components/layout/AppShell';
import { HomePage } from './pages/HomePage';
import { AllPubsPage } from './pages/AllPubsPage';
import { VisitedPage } from './pages/VisitedPage';
import { WantToVisitPage } from './pages/WantToVisitPage';
import { FavouritesPage } from './pages/FavouritesPage';
import { StatsPage } from './pages/StatsPage';
import { CrawlsPage } from './pages/CrawlsPage';
import { SettingsPage } from './pages/SettingsPage';
import { AreaPage } from './pages/AreaPage';

// Map-heavy pages pull in Leaflet + marker clustering — lazy-loaded so the
// initial bundle (and first paint on a phone) stays lean.
const MapPage = lazy(() => import('./pages/MapPage').then((m) => ({ default: m.MapPage })));
const PubDetailPage = lazy(() => import('./pages/PubDetailPage').then((m) => ({ default: m.PubDetailPage })));
const CrawlDetailPage = lazy(() => import('./pages/CrawlDetailPage').then((m) => ({ default: m.CrawlDetailPage })));

function PageFallback() {
  return (
    <div className="flex h-[60vh] items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-brand-200 border-t-brand-700" />
    </div>
  );
}

export default function App() {
  return (
    <PubDataProvider>
      <ToastProvider>
        <BrowserRouter>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route element={<AppShell />}>
                <Route path="/" element={<HomePage />} />
                <Route path="/map" element={<MapPage />} />
                <Route path="/pubs" element={<AllPubsPage />} />
                <Route path="/areas/:area" element={<AreaPage />} />
                <Route path="/visited" element={<VisitedPage />} />
                <Route path="/want-to-visit" element={<WantToVisitPage />} />
                <Route path="/favourites" element={<FavouritesPage />} />
                <Route path="/stats" element={<StatsPage />} />
                <Route path="/crawls" element={<CrawlsPage />} />
                <Route path="/crawls/:id" element={<CrawlDetailPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/pub/:id" element={<PubDetailPage />} />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
      </ToastProvider>
    </PubDataProvider>
  );
}
