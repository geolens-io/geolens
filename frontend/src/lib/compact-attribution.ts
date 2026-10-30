// MapLibre's own width for switching to the compact attribution.
const NARROW_MAP_PX = 640;

const ATTRIB = 'maplibregl-ctrl-attrib';
const COMPACT = 'maplibregl-compact';
const SHOWN = 'maplibregl-compact-show';

/**
 * Folds MapLibre's compact attribution inside `root` whenever it opens by
 * itself on a map at most 640 px wide. MapLibre expands it when the control is
 * added or first gets credits, and folds it only on the first drag, so on a
 * phone it covers a small map; it also folds it when a wider map narrows past
 * that width. The "i" button still expands it. Returns a function that stops
 * watching.
 */
export function keepCompactAttributionFolded(root: HTMLElement): () => void {
  const foldIfNarrow = (el: Element) => {
    if (root.clientWidth > NARROW_MAP_PX || !el.classList.contains(SHOWN)) return;
    el.classList.remove(SHOWN);
    el.removeAttribute('open');
  };

  root.querySelectorAll(`.${ATTRIB}`).forEach(foldIfNarrow);
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'childList') {
        record.addedNodes.forEach((node) => {
          if (node instanceof Element && node.classList.contains(ATTRIB)) foldIfNarrow(node);
        });
        continue;
      }
      // A control that was already compact changed because the reader
      // pressed its button; only the switch into compact opens it unasked.
      const target = record.target as Element;
      if (!target.classList.contains(ATTRIB)) continue;
      if (!record.oldValue?.split(/\s+/).includes(COMPACT)) foldIfNarrow(target);
    }
  });
  observer.observe(root, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['class'],
    attributeOldValue: true,
  });
  // MapLibre leaves an open attribution open when its map narrows, so fold it on the way down.
  let narrow = root.clientWidth <= NARROW_MAP_PX;
  const resize =
    typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(() => {
          const nowNarrow = root.clientWidth <= NARROW_MAP_PX;
          if (nowNarrow && !narrow) root.querySelectorAll(`.${ATTRIB}`).forEach(foldIfNarrow);
          narrow = nowNarrow;
        });
  resize?.observe(root);
  return () => {
    observer.disconnect();
    resize?.disconnect();
  };
}
