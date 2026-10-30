import { useEffect, useRef, type RefObject } from 'react';

/**
 * Reordering moves a row's DOM node, which drops focus. Call the returned
 * function before a move; once `items` changes, focus goes back to the same
 * `[data-move]` arrow in the row whose `idAttribute` matches, or to the other
 * arrow once the row reaches an end.
 */
export function useMoveFocus(container: RefObject<HTMLElement | null>, idAttribute: string, items: unknown) {
  const movedRef = useRef<{ id: string; by: -1 | 1 } | null>(null);
  useEffect(() => {
    const moved = movedRef.current;
    if (!moved) return;
    movedRef.current = null;
    const row = container.current?.querySelector(`[${idAttribute}="${moved.id}"]`);
    const arrows = [...(row?.querySelectorAll<HTMLButtonElement>('[data-move]') ?? [])].filter((b) => !b.disabled);
    (arrows.find((b) => b.dataset.move === String(moved.by)) ?? arrows[0])?.focus();
  }, [container, idAttribute, items]);
  return (id: string, by: -1 | 1) => {
    movedRef.current = { id, by };
  };
}
