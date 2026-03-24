import type { MapLayerResponse } from '@/types/api';

/**
 * Enrich a chat message with @mention context blocks and /command intent hints.
 *
 * @mentions are resolved against the current map layers. Bracket syntax @[Name With Spaces]
 * and plain @Name are both supported. Unresolvable mentions are left as-is.
 *
 * Slash commands (/style, /filter, /label, /query, /add) at the start of the message
 * are stripped and replaced with an [Intent: X] prefix.
 */

const SLASH_COMMANDS = ['style', 'filter', 'label', 'query', 'add'] as const;

const MENTION_BRACKET_RE = /@\[([^\]]+)\]/g;
const MENTION_PLAIN_RE = /@(\w+)/g;

function findLayer(name: string, layers: MapLayerResponse[]): MapLayerResponse | undefined {
  const lower = name.toLowerCase();
  return layers.find(
    (l) => (l.display_name ?? l.dataset_name).toLowerCase() === lower,
  );
}

function buildContextBlock(layer: MapLayerResponse): string {
  const name = layer.display_name ?? layer.dataset_name;
  const cols = (layer.dataset_column_info ?? [])
    .slice(0, 5)
    .map((c) => `${c.name}(${c.type})`)
    .join(', ');
  const count = layer.dataset_feature_count
    ? `${layer.dataset_feature_count.toLocaleString()} features`
    : 'unknown count';
  const geom = layer.dataset_geometry_type ?? 'unknown';
  return `@${name} = layer_id:${layer.id}, ${geom}, ${count}, columns: ${cols}`;
}

export function enrichMessage(raw: string, layers: MapLayerResponse[]): string {
  let message = raw;
  let intentPrefix = '';

  // Detect leading slash command
  const slashMatch = message.match(/^\/(\w+)\s*/);
  if (slashMatch) {
    const cmd = slashMatch[1].toLowerCase();
    if (SLASH_COMMANDS.includes(cmd as (typeof SLASH_COMMANDS)[number])) {
      intentPrefix = `[Intent: ${cmd}] `;
      message = message.slice(slashMatch[0].length);
    }
  }

  // Collect resolved mention context blocks (deduplicated by layer id)
  const resolved = new Map<string, string>();

  // Bracket mentions first: @[Layer Name]
  for (const match of raw.matchAll(MENTION_BRACKET_RE)) {
    const layer = findLayer(match[1].trim(), layers);
    if (layer && !resolved.has(layer.id)) {
      resolved.set(layer.id, buildContextBlock(layer));
    }
  }

  // Plain mentions: @LayerName (single word)
  for (const match of raw.matchAll(MENTION_PLAIN_RE)) {
    const layer = findLayer(match[1], layers);
    if (layer && !resolved.has(layer.id)) {
      resolved.set(layer.id, buildContextBlock(layer));
    }
  }

  const enriched = intentPrefix + message;

  if (resolved.size === 0) return enriched;
  return `${enriched}\n\n[Context: ${[...resolved.values()].join(' | ')}]`;
}
