import { useCallback } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';
import { applyLayerVisibilityToMap } from '@/components/builder/hooks/use-layer-map-sync';
import { removePerLayerCompanions } from '@/components/builder/hooks/builder-layer-mutations';
import { type GroupedLayer, clearPersistedFolderGroup } from '@/components/builder/folder-groups';

// STATE-02: folder-group handlers, relocated verbatim out of the useBuilderLayers
// god-hook. PURE RELOCATION — handler bodies are unchanged; the shared layers
// state (layersRef + setters) is threaded in as params. These operate on the
// in-memory localLayers array. Group layers are encoded as layers with
// layer_type: 'group:folder' or 'group:basemap'. Child layers reference their
// parent via parent_group_id (frontend-only field, not persisted to API).
interface UseFolderGroupLayersParams {
  layersRef: React.RefObject<MapLayerResponse[]>;
  setLocalLayers: React.Dispatch<React.SetStateAction<MapLayerResponse[]>>;
  setGroupMeta: React.Dispatch<React.SetStateAction<Record<string, { expanded: boolean }>>>;
  setHasUnsavedChanges: React.Dispatch<React.SetStateAction<boolean>>;
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
}

export function useFolderGroupLayers({
  layersRef,
  setLocalLayers,
  setGroupMeta,
  setHasUnsavedChanges,
  mapInstanceRef,
}: UseFolderGroupLayersParams) {
  const handleCreateGroupWithLayer = useCallback((layerId: string) => {
    // Generate id OUTSIDE the updater so both setters share the same value.
    // Phase 1051 WR-01: crypto.randomUUID is collision-safe across bulk +
    // single create paths firing in the same millisecond. The prior
    // `group-${Date.now()}` form collided under rapid bulk operations.
    const groupId = `group-${crypto.randomUUID()}`;

    setLocalLayers((prev) => {
      const idx = prev.findIndex((l) => l.id === layerId);
      if (idx < 0) return prev;

      // Generate a unique group name
      const existingGroupCount = prev.filter((l) =>
        (l as GroupedLayer).layer_type === 'group:folder',
      ).length;
      const groupName = `Group ${existingGroupCount + 1}`;

      const groupRow: GroupedLayer = {
        ...(prev[idx] as GroupedLayer),
        id: groupId,
        display_name: groupName,
        layer_type: 'group:folder',
        sort_order: prev[idx].sort_order,
        parent_group_id: null,
      };

      const childLayer: GroupedLayer = {
        ...(prev[idx] as GroupedLayer),
        parent_group_id: groupId,
      };

      const next = [...prev];
      next.splice(idx, 1, groupRow as unknown as MapLayerResponse, childLayer as unknown as MapLayerResponse);
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    // groupId is now in scope — auto-expand so the child layer is visible immediately.
    setGroupMeta((prev) => ({ ...prev, [groupId]: { expanded: true } }));
    setHasUnsavedChanges(true);
  }, [setLocalLayers, setGroupMeta, setHasUnsavedChanges]);

  const handleRenameGroup = useCallback((groupId: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return; // silent revert per UI-SPEC
    setLocalLayers((prev) =>
      prev.map((l) =>
        l.id === groupId ? { ...l, display_name: trimmed } : l,
      ),
    );
    setHasUnsavedChanges(true);
  }, [setLocalLayers, setHasUnsavedChanges]);

  const handleUngroup = useCallback((groupId: string) => {
    setLocalLayers((prev) => {
      // Remove the group container, keep children (clear their parent_group_id
      // AND any persisted style_config.builder.folderGroupId — otherwise a
      // child duplicated before Save carries the stale group pointer and gets
      // silently re-grouped on the next server resync; see fix #392, audit CR-01).
      const next = prev
        .filter((l) => l.id !== groupId)
        .map((l) => {
          const gl = l as GroupedLayer;
          if (gl.parent_group_id === groupId) {
            return {
              ...gl,
              parent_group_id: null,
              style_config: clearPersistedFolderGroup(gl.style_config),
            } as MapLayerResponse;
          }
          return l;
        });
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setHasUnsavedChanges(true);
  }, [setLocalLayers, setHasUnsavedChanges]);

  // P1-09: toggle the visibility of a folder group AND every child layer in ONE
  // atomic setLocalLayers write, routing each child's live-map side effect
  // through the shared companion visibility helper so a folder eye hides/shows
  // every child sublayer + its outline/label/extrusion/arrow/cluster/color-relief
  // companions. The synthetic group row is not a real map layer, so the old
  // `set_visibility` on the group id updated nothing but the row.
  const handleToggleGroupVisibility = useCallback((groupId: string) => {
    const current = layersRef.current;
    const group = current.find((l) => l.id === groupId);
    if (!group) return;
    const children = current.filter(
      (l) => (l as GroupedLayer).parent_group_id === groupId && l.id !== groupId,
    );
    // Flip relative to the group row's current visibility so the eye affordance
    // toggles predictably; the row + every child follow in one pass.
    const nextVisible = !(group.visible !== false);
    const affectedIds = new Set<string>([groupId, ...children.map((c) => c.id)]);

    setLocalLayers((prev) =>
      prev.map((l) => (affectedIds.has(l.id) ? { ...l, visible: nextVisible } : l)),
    );
    setHasUnsavedChanges(true);

    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      for (const child of children) {
        applyLayerVisibilityToMap(map, child, nextVisible);
      }
    }
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, mapInstanceRef]);

  const handleDeleteGroup = useCallback((groupId: string) => {
    // B-007: collect the group's child layer ids BEFORE the state mutation and
    // imperatively tear down their MapLibre companions (fill/outline/label/
    // extrusion/arrow/cluster glyphs), mirroring handleRemove. Without this the
    // children's paint layers linger as ghost visuals on the map until the next
    // full syncFromState. Deduped sources are left for the reference-count-aware
    // prune. (Group delete stays draft-until-Save for server persistence.)
    const childIds = layersRef.current
      .filter((l) => (l as GroupedLayer).parent_group_id === groupId && l.id !== groupId)
      .map((l) => l.id);
    if (childIds.length > 0) {
      removePerLayerCompanions(mapInstanceRef.current, childIds);
    }
    setLocalLayers((prev) => {
      const next = prev.filter((l) => {
        if (l.id === groupId) return false;
        const gl = l as GroupedLayer;
        if (gl.parent_group_id === groupId) return false;
        return true;
      });
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setHasUnsavedChanges(true);
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, mapInstanceRef]);

  const handleAddLayerToExistingGroup = useCallback((layerId: string, groupId: string) => {
    setLocalLayers((prev) => {
      const targetIdx = prev.findIndex((l) => l.id === layerId);
      if (targetIdx < 0) return prev;
      const updatedLayer: GroupedLayer = { ...(prev[targetIdx] as GroupedLayer), parent_group_id: groupId };
      const next = [...prev];
      next[targetIdx] = updatedLayer as MapLayerResponse;
      return next;
    });
    setGroupMeta((prev) => {
      if (prev[groupId]?.expanded) return prev;
      return { ...prev, [groupId]: { expanded: true } };
    });
    setHasUnsavedChanges(true);
  }, [setLocalLayers, setGroupMeta, setHasUnsavedChanges]);

  const handleMoveLayerOutOfGroup = useCallback((layerId: string) => {
    setLocalLayers((prev) => {
      const idx = prev.findIndex((l) => l.id === layerId);
      if (idx < 0) return prev;
      const gl = prev[idx] as GroupedLayer;
      const parentGroupId = gl.parent_group_id;
      if (!parentGroupId) return prev; // already not in a group

      // Find the position of the group container to place the layer just after it
      const groupIdx = prev.findIndex((l) => l.id === parentGroupId);
      // fix(#392): clear the persisted folderGroupId alongside the
      // frontend-only parent_group_id — see handleUngroup comment above. (audit CR-01)
      const updatedLayer: GroupedLayer = {
        ...gl,
        parent_group_id: null,
        style_config: clearPersistedFolderGroup(gl.style_config),
      };

      const next = prev.filter((l) => l.id !== layerId) as MapLayerResponse[];
      const insertAt = groupIdx >= 0 ? groupIdx + 1 : next.length;
      next.splice(insertAt, 0, updatedLayer as MapLayerResponse);
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setHasUnsavedChanges(true);
  }, [setLocalLayers, setHasUnsavedChanges]);

  return {
    handleCreateGroupWithLayer,
    handleRenameGroup,
    handleUngroup,
    handleToggleGroupVisibility,
    handleDeleteGroup,
    handleAddLayerToExistingGroup,
    handleMoveLayerOutOfGroup,
  };
}
