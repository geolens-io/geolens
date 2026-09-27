import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Map, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useMaps, useCreateMap } from '@/hooks/use-maps';
import { usePermissions } from '@/hooks/use-permissions';
import { useAuthStore } from '@/stores/auth-store';
import { canMutateResource } from '@/lib/ownership';

interface AddToMapButtonProps {
  datasetId: string;
  datasetTitle?: string;
}

export function AddToMapButton({ datasetId, datasetTitle }: AddToMapButtonProps) {
  const { t } = useTranslation('dataset');
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.roles.includes('admin') ?? false;
  const { data, isLoading } = useMaps({ limit: 20, sort_by: 'updated_at', sort_dir: 'desc', owned_only: !isAdmin });
  const createMap = useCreateMap();
  const { can } = usePermissions();

  const maps = data?.maps.filter((map) => canMutateResource(map, user?.id, isAdmin)) ?? [];

  function handleSelect(mapId: string) {
    setOpen(false);
    navigate(`/maps/${mapId}?add_dataset=${datasetId}`);
  }

  async function handleNewMap() {
    setOpen(false);
    try {
      const name = datasetTitle
        ? t('addToMap.newMapName', { title: datasetTitle })
        : t('addToMap.newMapFallback');
      const newMap = await createMap.mutateAsync({ name });
      navigate(`/maps/${newMap.id}?add_dataset=${datasetId}`);
    } catch {
      // useCreateMap reports the failure.
    }
  }

  if (!can('edit_metadata')) return null;

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button size="sm">
          <Map className="me-1 size-3.5" />
          {t('addToMap.button')}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {isLoading ? (
          <DropdownMenuItem disabled>{t('addToMap.loading')}</DropdownMenuItem>
        ) : maps.length === 0 ? (
          <DropdownMenuItem disabled>{t('addToMap.noMaps')}</DropdownMenuItem>
        ) : (
          maps.map((m) => (
            <DropdownMenuItem key={m.id} onClick={() => handleSelect(m.id)}>
              <span className="truncate">{m.name}</span>
            </DropdownMenuItem>
          ))
        )}
        {maps.length > 0 && <DropdownMenuSeparator />}
        <DropdownMenuItem onClick={handleNewMap} disabled={createMap.isPending}>
          {createMap.isPending ? (
            <><Loader2 className="me-1 size-3.5 animate-spin" /> {t('addToMap.creating')}</>
          ) : (
            t('addToMap.newMap')
          )}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
