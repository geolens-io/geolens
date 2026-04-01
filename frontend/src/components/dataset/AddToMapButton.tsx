import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Map, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useMaps, useCreateMap } from '@/hooks/use-maps';

interface AddToMapButtonProps {
  datasetId: string;
  datasetTitle?: string;
}

export function AddToMapButton({ datasetId, datasetTitle }: AddToMapButtonProps) {
  const { t } = useTranslation('dataset');
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useMaps({ limit: 20, sort_by: 'updated_at', sort_dir: 'desc' });
  const createMap = useCreateMap();

  const maps = data?.maps ?? [];

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
      toast.error(t('addToMap.createFailed'));
    }
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
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
