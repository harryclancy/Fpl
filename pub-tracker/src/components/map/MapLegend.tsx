export function MapLegend() {
  const items = [
    { color: '#1c8a4b', label: 'Visited' },
    { color: '#d97706', label: 'Not visited' },
    { color: '#d1435b', label: 'Favourite' },
    { color: '#6d5bd0', label: 'Want to visit' },
  ];
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 z-[400] rounded-xl bg-white/95 px-3 py-2 shadow-card backdrop-blur">
      <div className="flex flex-col gap-1">
        {items.map((item) => (
          <div key={item.label} className="flex items-center gap-1.5 text-[11px] font-medium text-ink-soft">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: item.color }} />
            {item.label}
          </div>
        ))}
      </div>
    </div>
  );
}
