import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Label } from '@/components/ui/label';
import type { SettingItem } from '@/api/settings';

interface TabProps {
  settings: SettingItem[];
  envOnly: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onReset: (key: string) => void;
  isSaving: boolean;
  onDirtyChange?: (dirty: boolean) => void;
}

const CAPABILITY_KEYS = [
  'upload',
  'create_layers',
  'export',
  'edit_metadata',
  'manage_collections',
  'use_ai_chat',
  'manage_users',
  'manage_settings',
] as const;

const ROLES = ['viewer', 'editor', 'admin'] as const;

type RolePermissions = Record<string, Record<string, boolean>>;

/** Admin column: these capabilities are always checked and disabled */
const ADMIN_LOCKED = new Set(['manage_users', 'manage_settings']);

export function SettingsPermissionsTab({ settings, envOnly, onSave, onReset, isSaving, onDirtyChange }: TabProps) {
  const { t } = useTranslation('admin');
  const [matrix, setMatrix] = useState<RolePermissions>({});

  const setting = settings.find((s) => s.key === 'role_permissions');

  const syncFromSettings = useCallback(() => {
    if (setting?.value) {
      setMatrix(setting.value as RolePermissions);
    }
  }, [setting]);

  useEffect(() => {
    syncFromSettings();
  }, [syncFromSettings]);

  const handleToggle = useCallback((role: string, capability: string, checked: boolean) => {
    setMatrix((prev) => ({
      ...prev,
      [role]: {
        ...prev[role],
        [capability]: checked,
      },
    }));
  }, []);

  const isDirty = useMemo(
    () => JSON.stringify(matrix) !== JSON.stringify(setting?.value ?? {}),
    [matrix, setting?.value],
  );

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  function handleSave() {
    onSave({ role_permissions: matrix });
  }

  function isLocked(role: string, capability: string): boolean {
    return role === 'admin' && ADMIN_LOCKED.has(capability);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('settings.permissions.title')}</CardTitle>
        <CardDescription>
          {t('settings.permissions.description')}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('settings.permissions.capabilityHeader')}</TableHead>
                {ROLES.map((role) => (
                  <TableHead key={role} className="text-center">
                    {t(`roles.${role}`)}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {CAPABILITY_KEYS.map((key) => {
                const label = t(`settings.permissions.capabilities.${key}`);
                return (
                  <TableRow key={key}>
                    <TableCell>
                      <Label className="font-normal">{label}</Label>
                    </TableCell>
                    {ROLES.map((role) => {
                      const locked = isLocked(role, key);
                      const checked = locked ? true : (matrix[role]?.[key] ?? false);
                      return (
                        <TableCell key={role} className="text-center">
                          <Checkbox
                            checked={checked}
                            onCheckedChange={(v) => handleToggle(role, key, v === true)}
                            disabled={locked || envOnly}
                            aria-label={t('settings.permissions.capabilityForRole', { capability: label, role: t(`roles.${role}`) })}
                          />
                        </TableCell>
                      );
                    })}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>

        <div className="flex items-center gap-3 pt-4">
          <Button onClick={handleSave} disabled={!isDirty || envOnly || isSaving}>
            {isSaving ? <Loader2 className="me-2 h-4 w-4 animate-spin" /> : null}
            {t('common:save')}
          </Button>
          <Button variant="outline" onClick={() => onReset('role_permissions')} disabled={envOnly || isSaving}>
            {t('settings.actions.resetDefaults')}
          </Button>
          <Button variant="outline" onClick={syncFromSettings} disabled={!isDirty || isSaving}>
            {t('settings.actions.discard')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
