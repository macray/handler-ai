// Agent output is untrusted. Three layers keep it inert:
//   1. this renderer: raw HTML in markdown is shown as text, links/images only with safe URLs
//      (pure string work, independent of any DOM);
//   2. DOMPurify on the resulting HTML;
//   3. the daemon's Content-Security-Policy (no foreign scripts, connections, frames).
import DOMPurify from "dompurify";
import { Marked, type Tokens } from "marked";

const SAFE_URL = /^(https?:\/\/|mailto:|#|\/(?!\/)|\.{1,2}\/)/i;

export function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// A path relative to the current document, without a scheme ("notes.md", "sub/x.md#a").
const RELATIVE_PATH = /^(?![a-z][a-z0-9+.-]*:)[^/\\\s][^\s]*$/i;

function renderer(relativeLinks: boolean): Marked {
  return new Marked({
    gfm: true,
    breaks: false,
    renderer: {
      html(token: Tokens.HTML | Tokens.Tag): string {
        return escapeHtml(token.text);
      },
      link(token: Tokens.Link): string | false {
        const url = token.href.trim();
        if (!SAFE_URL.test(url) && !(relativeLinks && RELATIVE_PATH.test(url))) return escapeHtml(token.text);
        return false; // default rendering
      },
      image(token: Tokens.Image): string {
        return escapeHtml(`[image: ${token.text || token.href}]`); // no remote loads
      },
    },
  });
}

// Images the agent's tools return (e.g. browser screenshots, ACP image content blocks): inline data
// only, raster formats only (no SVG), never a URL to load.
export const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

/** A `data:` URL for an image content block, or null when it is not one we show. */
export function imageSrc(block: { type: string; mimeType?: string | null; data?: string | null }): string | null {
  if (block.type !== "image" || !block.mimeType || !block.data) return null;
  const mime = block.mimeType.toLowerCase();
  if (!IMAGE_TYPES.has(mime) || !BASE64.test(block.data)) return null;
  return `data:${mime};base64,${block.data}`;
}

const agentMarkdown = renderer(false);
const documentMarkdown = renderer(true);

/** `relativeLinks`: also keep links like "notes.md" (documents whose links the page resolves
 *  itself, e.g. knowledge notes); agent output keeps the stricter rule. */
export function markdown(text: string, options: { relativeLinks?: boolean } = {}): string {
  const html = (options.relativeLinks ? documentMarkdown : agentMarkdown).parse(text, { async: false });
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["style", "form", "input", "button", "iframe"],
    FORBID_ATTR: ["style"],
  });
}
