/** The page a story's embed loads. */
export function storyEmbedSrc(origin: string, storyId: string): string {
  return `${origin}/stories/${encodeURIComponent(storyId)}/embed`;
}

function escapeHtmlAttribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * The iframe snippet for a public story. The sandbox is the map embed's (see
 * generateEmbedCode), plus popups that leave the sandbox, so a button block
 * set to open its link in a new tab still opens a working page.
 */
export function storyEmbedCode({ origin, storyId, title }: { origin: string; storyId: string; title: string }): string {
  return (
    `<iframe src="${storyEmbedSrc(origin, storyId)}" title="${escapeHtmlAttribute(title)}" ` +
    'width="100%" height="640" ' +
    'sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox" ' +
    'style="border:none;"></iframe>'
  );
}
