import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { BottomNav } from './BottomNav';

export function AppShell() {
  return (
    <div className="min-h-dvh bg-paper">
      <Sidebar />
      <div className="lg:pl-64">
        <main className="mx-auto min-h-dvh max-w-6xl pb-24 lg:pb-10">
          <Outlet />
        </main>
      </div>
      <BottomNav />
    </div>
  );
}
