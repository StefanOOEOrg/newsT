/**
 * Paging of the three list screens `/posts`, `/alerts` and `/logs` (#59).
 *
 * All three page the same way: a window of `page` x `per_page`, a jump that can land beyond the
 * last page, and one sentence that says so when it did. The sizes and that sentence live here
 * once, so the three stores and pagers cannot drift apart.
 */

/** The page sizes the pager offers, smallest first. */
export const PAGE_SIZES = [25, 50, 100, 200] as const;

/** Where a requested page ends up, and whether it had to be pulled back from beyond the list. */
export interface PageClamp {
  readonly page: number;
  /** True when the request was above the last page - the pager says so then. */
  readonly beyondLast: boolean;
}

/** Pull a requested page into `1..pages`; `pages` is at least 1, as the stores compute it. */
export function clampPage(page: number, pages: number): PageClamp {
  const last = Math.max(1, Math.trunc(pages));
  const wanted = Math.trunc(page);
  if (wanted > last) {
    return { page: last, beyondLast: true };
  }
  return { page: Math.max(1, wanted), beyondLast: false };
}

/** The sentence the pager shows after a jump beyond the last page; `null` for a normal move. */
export function pageNoticeFor(clamp: PageClamp): string | null {
  if (!clamp.beyondLast) {
    return null;
  }
  return `That page does not exist — showing page ${clamp.page}, the last one.`;
}
