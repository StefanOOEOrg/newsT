import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { Page, PostRow } from './models';

/** The window and the filters of one `/api/posts` call. */
export interface PostsQuery {
  readonly page: number;
  readonly per_page: number;
  /** `social_posts.asset_id`, `null` for every asset. */
  readonly asset_id: number | null;
  /** `social_posts.source`, `null` for every source. */
  readonly source: string | null;
}

/** `/api/posts`: the posts joined with their analysis, newest first (#56). */
@Injectable({ providedIn: 'root' })
export class PostsService {
  private readonly http = inject(HttpClient);

  /** `GET /api/posts?page=&per_page=&asset_id=&source=` -> one page of posts. */
  list(query: PostsQuery): Observable<Page<PostRow>> {
    let params = new HttpParams().set('page', query.page).set('per_page', query.per_page);
    if (query.asset_id !== null) {
      params = params.set('asset_id', query.asset_id);
    }
    if (query.source !== null) {
      params = params.set('source', query.source);
    }
    return this.http.get<Page<PostRow>>('/api/posts', { params });
  }
}
