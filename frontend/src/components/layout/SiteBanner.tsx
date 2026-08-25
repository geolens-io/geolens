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

// feat(#1662): make https:// URLs in admin-entered banner text
// clickable. The text itself stays React-escaped; only the matched URL
// becomes an anchor, so an admin cannot inject markup through the banner.
// Trailing sentence punctuation stays outside the link.
// Apostrophes are legitimate URL characters (/O'Reilly), so ' is NOT an
// excluded body character; a single quote only acts as a delimiter when it
// wraps the URL ('https://…'), handled by the paired-wrapper check below.
// fix(#1662 review): a single greedy group with no trailing-group/lookahead
// split — the earlier lazy-body + punctuation-group pair let the engine retry
// every split point on adversarial runs (quadratic). The trail is peeled in
// plain code below instead, which is linear by construction.
const URL_RE = /https:\/\/[^\s<>"\u201C\u201D\u2018\u2019\u00AB\u00BB\u2013\u2014]+/gi;
const TRAIL_RE = /[.,;:!?)\]\u2026\u3002\u3001]+$/;

function renderBannerText(text: string) {
  const parts: Array<string | { url: string; trail: string }> = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    // fix(#1662 review): a verbatim <…> span advances `last` past characters
    // matchAll has not seen; a scheme inside the consumed span must not
    // produce a second, overlapping link.
    if (m.index! < last) continue;
    // fix(#1662 review): only linkify at a token boundary — an https:// embedded
    // inside another token (nothttps://…, or a URL nested in another URL's
    // path) is not a link of its own.
    if (m.index! > 0 && !/[\s<>"'()[\]\u201C\u201D\u2018\u2019\u00AB\u00BB\u2013\u2014]/.test(text[m.index! - 1])) {
      continue;
    }
    if (m.index! > last) parts.push(text.slice(last, m.index));
    const matched = m[0];
    const trailMatch = TRAIL_RE.exec(matched);
    let url = trailMatch ? matched.slice(0, trailMatch.index) : matched;
    let trail = trailMatch ? trailMatch[0] : '';
    // fix(#1662 review): <https://…> is RFC 3986's own URL delimiting. Inside
    // angle brackets the URL is taken VERBATIM — trailing punctuation like
    // /wiki/Yahoo! stays in the href, and no wrapper/balance heuristics run.
    // This is also the documented escape hatch: an admin who needs an exact
    // URL that the heuristics would trim can always write <URL>.
    // The regex may stop early inside <…> (excluded characters like dashes are
    // allowed there), so the verbatim span runs to the closing bracket itself.
    if (m.index! > 0 && text[m.index! - 1] === '<') {
      // fix(#1662 review): bound the '>' search to the current whitespace-free
      // token — an unclosed '<' must not scan the whole remaining text, or
      // repeated unclosed spans would make the render quadratic.
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
    // fix(#1662 review): 'https://…' wrapped in single quotes — the opening
    // quote sits just before the match, so a trailing apostrophe is the
    // closing wrapper, not part of the URL. Unpaired apostrophes stay in.
    if (m.index! > 0 && text[m.index! - 1] === "'" && url.endsWith("'")) {
      url = url.slice(0, -1);
      trail = "'" + trail;
    }
    // fix(#1662 review): a URL that legitimately ends in ')' or ']' — e.g. a
    // Wikipedia path like /Function_(mathematics) — should keep as many
    // closing brackets as it has unmatched opening ones of the same kind;
    // only the excess is sentence punctuation or a wrapping delimiter.
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
          {p.url}
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
      // storage unavailable (privacy mode) — dismiss for this mount only
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
