/**
 * Generic admin-configured announcement banner.
 *
 * Renders for all visitors (logged-in or anonymous) when the admin has
 * enabled it AND set a non-empty banner_text in Settings → General. Color is
 * one of the theme tokens (warning | info | success | destructive); unknown
 * values fall back to warning.
 *
 * Dismissible per session: dismissing stores the banner text in
 * sessionStorage, so it stays hidden until the tab session ends or the admin
 * changes the text.
 *
 * Reuses the same /auth/config query-cache entry that LandingFirstGuard
 * populates — no additional network request.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { getAuthConfig } from '@/api/auth';
import { queryKeys } from '@/lib/query-keys';

const COLOR_CLASSES: Record<string, string> = {
  warning: 'border-warning/30 bg-warning/10 text-warning',
  info: 'border-info/30 bg-info/10 text-info',
  success: 'border-success/30 bg-success/10 text-success',
  destructive: 'border-destructive/30 bg-destructive/10 text-destructive',
};

const DISMISS_KEY = 'gl-site-banner-dismissed';

// Linkifies https:// URLs in admin-entered banner text. The text stays
// React-escaped and only the matched URL becomes an anchor, so an admin cannot
// inject markup. Trailing sentence punctuation stays outside the link.
// Apostrophes are legitimate URL characters (/O'Reilly), so ' is not excluded
// from the body; it delimits only when it wraps the URL ('https://…'), via the
// paired-wrapper check below.
// One greedy group, with the trail peeled in plain code: a lazy body plus a
// punctuation group lets the engine retry every split point on adversarial
// runs (quadratic).
const URL_RE_SOURCE = String.raw`https:\/\/[^\s<>"\u201C\u201D\u2018\u2019\u00AB\u00BB\u2013\u2014]+`;
// [label](https://…) is tried first at each position. The label needs a
// visible character and cannot contain brackets and the target cannot contain parentheses, so a failed match gives
// up at the next bracket and the scan stays linear.
const LINK_RE_SOURCE = String.raw`\[(?=[^\[\]]*[^\s\[\]])([^\[\]]+)\]\((https:\/\/[^\s()<>"]+)\)`;
const LINK_OR_URL_RE = new RegExp(`${LINK_RE_SOURCE}|${URL_RE_SOURCE}`, 'gi');
const TRAIL_RE = /[.,;:!?)\]\u2026\u3002\u3001]+$/;

// The linkifier runs per visitor render on admin text with no schema length
// limit. Capping the work bounds the worst case to a constant: a longer banner
// (broken UX anyway) renders as plain text.
const LINKIFY_MAX_LENGTH = 2000;

function renderBannerText(text: string) {
  if (text.length > LINKIFY_MAX_LENGTH) return [text];
  const parts: Array<string | { url: string; trail: string; label?: string }> = [];
  let last = 0;
  for (const m of text.matchAll(LINK_OR_URL_RE)) {
    // A verbatim <…> span advances `last` past text matchAll has not seen; a
    // scheme inside it must not produce a second, overlapping link.
    if (m.index! < last) continue;
    if (m[1] !== undefined) {
      if (m.index! > last) parts.push(text.slice(last, m.index));
      parts.push({ url: m[2], trail: '', label: m[1] });
      last = m.index! + m[0].length;
      continue;
    }
    // Only at a token boundary: an https:// inside another token (nothttps://…
    // or a URL nested in another URL's path) is not a link of its own.
    if (m.index! > 0 && !/[\s<>"'()[\]\u201C\u201D\u2018\u2019\u00AB\u00BB\u2013\u2014]/.test(text[m.index! - 1])) {
      continue;
    }
    if (m.index! > last) parts.push(text.slice(last, m.index));
    const matched = m[0];
    const trailMatch = TRAIL_RE.exec(matched);
    let url = trailMatch ? matched.slice(0, trailMatch.index) : matched;
    let trail = trailMatch ? trailMatch[0] : '';
    // <https://…> is RFC 3986's URL delimiting: inside angle brackets the URL
    // is taken VERBATIM (trailing punctuation like /wiki/Yahoo! stays in the
    // href, no heuristics run). It is also the escape hatch for an admin who
    // needs an exact URL the heuristics would trim. The regex may stop early
    // inside <…> (excluded characters are allowed there), so the span runs to
    // the closing bracket itself.
    if (m.index! > 0 && text[m.index! - 1] === '<') {
      // Bounded to the current whitespace-free token: an unclosed '<' must not
      // scan the remaining text, or repeated ones make the render quadratic.
      const ws = text.slice(m.index!).search(/\s/);
      const tokenEnd = ws === -1 ? text.length : m.index! + ws;
      const closeInToken = text.slice(m.index!, tokenEnd).indexOf('>');
      if (closeInToken !== -1) {
        const close = m.index! + closeInToken;
        parts.push({ url: text.slice(m.index!, close), trail: '' });
        last = close;
        continue;
      }
    }
    // With an opening quote just before the match, a trailing apostrophe is the
    // closing wrapper; unpaired apostrophes stay in the URL.
    if (m.index! > 0 && text[m.index! - 1] === "'" && url.endsWith("'")) {
      url = url.slice(0, -1);
      trail = "'" + trail;
    }
    // A URL like /Function_(mathematics) keeps as many closing brackets as it
    // has unmatched opening ones; only the excess is punctuation or a wrapper.
    for (const [openCh, closeCh] of [
      ['(', ')'],
      ['[', ']'],
    ] as const) {
      let unmatched = 0;
      for (const ch of url) {
        if (ch === openCh) unmatched += 1;
        else if (ch === closeCh && unmatched > 0) unmatched -= 1;
      }
      while (unmatched > 0 && trail.includes(closeCh)) {
        const j = trail.indexOf(closeCh);
        url += trail.slice(0, j + 1);
        trail = trail.slice(j + 1);
        unmatched -= 1;
      }
    }
    parts.push({ url, trail });
    last = m.index! + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.map((p, i) =>
    typeof p === 'string' ? (
      p
    ) : (
      <span key={i}>
        <a
          href={p.url}
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-2 hover:opacity-80"
        >
          {p.label ?? p.url}
        </a>
        {p.trail}
      </span>
    ),
  );
}

function getDismissed(): string | null {
  try {
    return sessionStorage.getItem(DISMISS_KEY);
  } catch {
    return null;
  }
}

export function SiteBanner() {
  const { t } = useTranslation('common');
  const { data: config } = useQuery({
    queryKey: queryKeys.authConfig.config,
    queryFn: getAuthConfig,
    staleTime: 5 * 60 * 1000,
  });
  const [dismissed, setDismissed] = useState(getDismissed);

  const text = config?.banner_text?.trim();
  if (!config?.banner_enabled || !text || dismissed === text) return null;

  const colorClass = COLOR_CLASSES[config?.banner_color ?? ''] ?? COLOR_CLASSES.warning;

  function handleDismiss() {
    try {
      sessionStorage.setItem(DISMISS_KEY, text!);
    } catch {
      // Storage may be unavailable (privacy mode); dismiss for this mount only.
    }
    setDismissed(text!);
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className={`relative border-b px-8 py-1.5 text-center text-sm ${colorClass}`}
    >
      {renderBannerText(text)}
      <button
        type="button"
        onClick={handleDismiss}
        aria-label={t('close')}
        className="absolute end-2 top-1/2 -translate-y-1/2 rounded p-0.5 opacity-70 hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
