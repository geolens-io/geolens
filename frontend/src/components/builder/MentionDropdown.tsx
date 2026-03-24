import { Layers, Terminal } from 'lucide-react';

export interface MentionItem {
  id: string;
  label: string;
  description?: string;
}

interface MentionDropdownProps {
  id: string;
  items: MentionItem[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  type: '@' | '/';
}

export function MentionDropdown({ id, items, selectedIndex, onSelect, type }: MentionDropdownProps) {
  if (items.length === 0) return null;

  return (
    <div
      id={id}
      className="absolute bottom-full left-0 w-full mb-1 max-h-48 overflow-y-auto rounded-lg border bg-popover shadow-md text-sm z-50"
      role="listbox"
      aria-label={type === '@' ? 'Layers' : 'Commands'}
    >
      {items.map((item, index) => (
        <div
          key={item.id}
          id={`${id}-option-${index}`}
          role="option"
          aria-selected={index === selectedIndex}
          className={`flex items-center gap-2 px-3 py-1.5 cursor-pointer ${
            index === selectedIndex ? 'bg-accent' : 'hover:bg-accent/50'
          }`}
          onMouseDown={(e) => {
            e.preventDefault(); // prevent textarea blur
            onSelect(index);
          }}
        >
          {type === '@' ? (
            <Layers className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <Terminal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="font-medium truncate">{item.label}</span>
          {item.description && (
            <span className="text-xs text-muted-foreground ml-auto shrink-0">
              {item.description}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
