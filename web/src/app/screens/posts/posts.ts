import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { PAGE_SIZES } from '../paging';
import { PostsStore } from './posts.store';

/**
 * The posts screen `/posts` - *What did it find?*
 *
 * One row per post with its analysis, the two filters and the pager. The store owns the window,
 * the filters and the request; the component only reads its signals (#58).
 */
@Component({
  selector: 'app-posts',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './posts.html',
})
export class Posts {
  protected readonly store = inject(PostsStore);
  /** The page sizes of the pager's selector (#59). */
  protected readonly pageSizes = PAGE_SIZES;
}
