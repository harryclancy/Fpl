import { useRef, useState, type PointerEvent, type ReactNode } from 'react';
import { GripVertical } from 'lucide-react';

interface DraggableListProps<T> {
  items: T[];
  keyFn: (item: T) => string;
  onReorder: (items: T[]) => void;
  renderItem: (item: T, index: number) => ReactNode;
}

const ROW_HEIGHT_ESTIMATE = 76;

/** Touch-friendly drag-to-reorder list using Pointer Events (works for mouse,
 * touch and pen alike) — no external DnD library needed for a single vertical list. */
export function DraggableList<T>({ items, keyFn, onReorder, renderItem }: DraggableListProps<T>) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [offsetY, setOffsetY] = useState(0);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const startYRef = useRef(0);

  function handlePointerDown(e: PointerEvent, index: number) {
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    startYRef.current = e.clientY;
    setDragIndex(index);
    setOverIndex(index);
    setOffsetY(0);
  }

  function handlePointerMove(e: PointerEvent) {
    if (dragIndex === null) return;
    const delta = e.clientY - startYRef.current;
    setOffsetY(delta);
    const approxIndex = Math.round(dragIndex + delta / ROW_HEIGHT_ESTIMATE);
    const clamped = Math.max(0, Math.min(items.length - 1, approxIndex));
    setOverIndex(clamped);
  }

  function handlePointerUp() {
    if (dragIndex === null || overIndex === null) {
      setDragIndex(null);
      return;
    }
    if (overIndex !== dragIndex) {
      const next = [...items];
      const [moved] = next.splice(dragIndex, 1);
      next.splice(overIndex, 0, moved);
      onReorder(next);
    }
    setDragIndex(null);
    setOverIndex(null);
    setOffsetY(0);
  }

  return (
    <div ref={containerRef} className="flex flex-col gap-2">
      {items.map((item, index) => {
        const isDragging = index === dragIndex;
        let translateY = 0;
        if (dragIndex !== null && overIndex !== null && !isDragging) {
          if (dragIndex < overIndex && index > dragIndex && index <= overIndex) translateY = -ROW_HEIGHT_ESTIMATE;
          if (dragIndex > overIndex && index < dragIndex && index >= overIndex) translateY = ROW_HEIGHT_ESTIMATE;
        }
        return (
          <div
            key={keyFn(item)}
            style={{
              transform: isDragging ? `translateY(${offsetY}px)` : `translateY(${translateY}px)`,
              transition: isDragging ? 'none' : 'transform 0.2s ease',
              zIndex: isDragging ? 20 : 1,
              position: 'relative',
            }}
            className={isDragging ? 'shadow-pop' : ''}
          >
            <div className="flex items-center gap-2 rounded-card bg-white p-2 shadow-card">
              <button
                onPointerDown={(e) => handlePointerDown(e, index)}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                onPointerCancel={handlePointerUp}
                aria-label="Drag to reorder"
                className="flex h-9 w-9 shrink-0 touch-none items-center justify-center rounded-lg text-ink-soft active:bg-black/5"
              >
                <GripVertical size={17} />
              </button>
              <div className="min-w-0 flex-1">{renderItem(item, index)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
