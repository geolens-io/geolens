interface MetadataFieldProps {
  icon?: React.ComponentType<{ className?: string }>;
  label: string;
  children: React.ReactNode;
}

/**
 * Reusable icon + label + content pattern for displaying metadata fields.
 */
export function MetadataField({ icon: Icon, label, children }: MetadataFieldProps) {
  return (
    <div className="space-y-2">
      <dt className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
        {Icon && <Icon className="h-4 w-4" />}
        {label}
      </dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}
