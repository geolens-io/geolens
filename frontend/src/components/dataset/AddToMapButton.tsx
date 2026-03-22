import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Map } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useMaps } from '@/hooks/use-maps';

interface AddToMapButtonProps {
  datasetId: string;
}

export function AddToMapButton({ datasetId }: AddToMapButtonProps) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useMaps({ limit: 20, sort_by: 'updated_at', sort_dir: 'desc' });

  const maps = data?.maps ?? [];

  function handleSelect(mapId: string) {
    setOpen(false);
    navigate(`/maps/${mapId}?add_dataset=${datasetId}`);
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Map className="mr-1 size-3.5" />
          Add to Map
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {isLoading ? (
          <DropdownMenuItem disabled>Loading maps...</DropdownMenuItem>
        ) : maps.length === 0 ? (
          <DropdownMenuItem disabled>No maps available</DropdownMenuItem>
        ) : (
          maps.map((m) => (
            <DropdownMenuItem key={m.id} onClick={() => handleSelect(m.id)}>
              <span className="truncate">{m.name}</span>
            </DropdownMenuItem>
          ))
        )}
        {maps.length > 0 && <DropdownMenuSeparator />}
        <DropdownMenuItem onClick={() => { setOpen(false); navigate(`/maps?add_dataset=${datasetId}`); }}>
          + New map
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
