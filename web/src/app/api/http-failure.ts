import { HttpErrorResponse } from '@angular/common/http';

/**
 * A failed dashboard call, as the screens report it (#58).
 *
 * The status is what the screen prints ("HTTP 503"), so a store never shows a bare "something
 * went wrong"; `status` is 0 for a failure that never reached the server.
 */
export interface Failure {
  readonly status: number;
  readonly message: string;
}

/** Map whatever `HttpClient` raised onto the one failure shape the stores hold. */
export function toFailure(error: unknown): Failure {
  if (error instanceof HttpErrorResponse) {
    return { status: error.status, message: error.statusText || `HTTP ${error.status}` };
  }
  if (error instanceof Error) {
    return { status: 0, message: error.message };
  }
  return { status: 0, message: String(error) };
}
