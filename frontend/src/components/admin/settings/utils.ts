import type { SettingItem } from '@/api/settings';

export function findSetting(settings: SettingItem[], key: string) {
  return settings.find((s) => s.key === key);
}
