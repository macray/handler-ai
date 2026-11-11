// The browser tab says what waits for you (decided with the bell): its title `(n) Handler`, and
// a dot drawn on the favicon, so it shows from another tab. Never a sound nor a notification.

const ICON = "/favicon.svg";
const DOT = '<circle cx="52" cy="12" r="11" fill="#d97706" stroke="#fff" stroke-width="3"/>';

/** The favicon's SVG with the dot added (before its closing tag). */
export function withDot(svg: string): string {
  return svg.replace(/<\/svg>\s*$/, `${DOT}</svg>`);
}

export function tabTitle(count: number): string {
  return count ? `(${count}) Handler` : "Handler";
}

let plain: string | null = null;

/** Title and favicon for `count` things waiting. */
export async function showCount(count: number): Promise<void> {
  document.title = tabTitle(count);
  const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) return;
  if (!count) {
    link.href = ICON;
    return;
  }
  try {
    plain ??= await (await fetch(ICON)).text();
  } catch {
    return; // the title still says it
  }
  link.href = `data:image/svg+xml,${encodeURIComponent(withDot(plain))}`;
}
