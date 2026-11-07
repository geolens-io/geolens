import { useQuery } from '@tanstack/react-query';
import { getStoryFrameHosts } from '@/api/stories';
import { queryKeys } from '@/lib/query-keys';
import type { StoryFrameHost } from '@/types/api';

/** An embed or video block's config: the address it frames and the frame's accessible name. */
export interface FrameConfig {
  url: string;
  title: string;
}

/** The server's caps on a frame block (`FrameConfig` in widgets/schemas.py). */
export const FRAME_URL_MAX_LENGTH = 2048;
export const FRAME_TITLE_MAX_LENGTH = 200;

export const FRAME_DEFAULT_CONFIG: FrameConfig = { url: '', title: '' };

const LABEL = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;
// eslint-disable-next-line no-control-regex -- control characters are the point
const UNSAFE_URL_CHARS = /[\s\\\u0000-\u001f\u007f]/;

/** A lower-cased DNS host name with two or more labels, or null; mirrors `normalize_frame_host`. */
export function normalizeFrameHost(value: string): string | null {
  const host = value.trim().toLowerCase();
  const labels = host.split('.');
  if (host.length > 253 || labels.length < 2 || !labels.every((label) => LABEL.test(label))) return null;
  // A last label browsers read as a number (decimal or 0x hex) makes the host an IPv4 address.
  return /^([0-9]+|0x[0-9a-f]*)$/.test(labels[labels.length - 1]) ? null : host;
}

/**
 * The host of an address a story block may frame, or null when the server
 * would refuse its shape: https only, no user name, no port but 443, and a
 * plain host name rather than an IP address.
 */
export function frameUrlHost(url: string): string | null {
  if ([...url].length > FRAME_URL_MAX_LENGTH || UNSAFE_URL_CHARS.test(url)) return null;
  const authority = /^https:\/\/([^/?#]*)/i.exec(url)?.[1].toLowerCase();
  if (authority === undefined || authority.includes('@')) return null;
  const host = authority.endsWith(':443') ? authority.slice(0, -4) : authority;
  return host.includes(':') ? null : normalizeFrameHost(host);
}

/** The approved entry for the host `url` frames, if there is one. */
export function approvedFrameHost(
  hosts: readonly StoryFrameHost[],
  url: string,
): StoryFrameHost | undefined {
  const host = frameUrlHost(url);
  return host === null ? undefined : hosts.find((entry) => entry.host === host);
}

/** The iframe sandbox: scripts and popups, and the frame's own origin only for a host an admin opted in. */
export function frameSandbox(entry: StoryFrameHost): string {
  return entry.allow_same_origin ? 'allow-scripts allow-popups allow-same-origin' : 'allow-scripts allow-popups';
}

const KEYS = new Set(['url', 'title']);

export function parseFrameConfig(config: unknown): FrameConfig | null {
  if (typeof config !== 'object' || config === null || Array.isArray(config)) return null;
  if (!Object.keys(config).every((key) => KEYS.has(key))) return null;
  const { url, title } = config as { url?: unknown; title?: unknown };
  if (typeof url !== 'string' || frameUrlHost(url) === null) return null;
  if (typeof title !== 'string' || title.trim() === '' || [...title].length > FRAME_TITLE_MAX_LENGTH) return null;
  return { url, title };
}

/**
 * The hosts an admin approved for story frames, as anyone may read them.
 * A mounted page asks again every half minute, so a host an admin adds or
 * removes reaches open editors and readers without a reload.
 */
export function useStoryFrameHosts() {
  return useQuery({
    queryKey: queryKeys.stories.frameHosts,
    queryFn: getStoryFrameHosts,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}
