/** Hidden tag the mechanic adds at the end of an answer (see backend services/prompts.py). */
export interface AnswerMedia {
  parts: string[];
  video: string | null;
  /** The user asked to see the parts: show a button to the car's parts catalog. */
  catalog: boolean;
}

const MEDIA_TAG = /<!--\s*mikaniki-media\s*(\{[\s\S]*?\})\s*-->/;

/** Split an assistant reply into its visible text and its media tag (if any, and valid). */
export function splitMedia(content: string): { text: string; media: AnswerMedia | null } {
  const match = content.match(MEDIA_TAG);
  if (!match) return { text: content, media: null };
  const text = content.replace(MEDIA_TAG, '').trimEnd();
  try {
    const raw = JSON.parse(match[1]) as { parts?: unknown; video?: unknown; catalog?: unknown };
    const parts = Array.isArray(raw.parts)
      ? raw.parts.filter((p): p is string => typeof p === 'string' && !!p.trim()).slice(0, 3)
      : [];
    const video = typeof raw.video === 'string' && raw.video.trim() ? raw.video.trim() : null;
    const catalog = raw.catalog === true;
    return { text, media: parts.length || video || catalog ? { parts, video, catalog } : null };
  } catch {
    return { text, media: null };
  }
}

/**
 * Minimal, safe Markdown → HTML for assistant replies:
 * escapes HTML first, then supports **bold**, headings, numbered/bullet lists and paragraphs.
 */
export function renderMarkdown(src: string): string {
  const escape = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const inline = (s: string) =>
    escape(s)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*(?!\s)(.+?)\*(?!\*)/g, '$1<em>$2</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');

  const out: string[] = [];
  let list: 'ul' | 'ol' | null = null;
  const closeList = () => {
    if (list) out.push(`</${list}>`);
    list = null;
  };

  let code: string[] | null = null;  // inside a ``` block (e.g. a small text sketch of the engine bay)
  for (const raw of src.split('\n')) {
    const line = raw.trimEnd();
    if (/^\s*```/.test(line)) {
      if (code) {
        out.push(`<pre>${escape(code.join('\n'))}</pre>`);
        code = null;
      } else {
        closeList();
        code = [];
      }
      continue;
    }
    if (code) {
      code.push(raw);
      continue;
    }
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const ul = line.match(/^\s*[-*•]\s+(.*)$/);
    const h = line.match(/^#{1,4}\s+(.*)$/);

    if (ol || ul) {
      const kind = ol ? 'ol' : 'ul';
      if (list !== kind) {
        closeList();
        out.push(`<${kind}>`);
        list = kind;
      }
      out.push(`<li>${inline((ol ?? ul)![1])}</li>`);
    } else if (h) {
      closeList();
      out.push(`<p class="md-h">${inline(h[1])}</p>`);
    } else if (!line.trim()) {
      closeList();
    } else {
      closeList();
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  if (code) out.push(`<pre>${escape(code.join('\n'))}</pre>`);  // unclosed block
  return out.join('');
}
