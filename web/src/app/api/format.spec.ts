import { HttpErrorResponse } from '@angular/common/http';

import { bytes, dash, fixed, share, signedPercent, stamp, yesNo } from './format';
import { toFailure } from './http-failure';

/**
 * The display helpers of #58. Every value the templates show goes through one of these, so `null`
 * can never become `0` (`dash`), and one timestamp format is used everywhere.
 */
describe('format', () => {
  it('renders an em dash for a missing value, but keeps a real zero', () => {
    expect(dash(null)).toBe('—');
    expect(dash(undefined)).toBe('—');
    expect(dash('')).toBe('—');
    expect(dash(0)).toBe('0');
    expect(dash('rss')).toBe('rss');
  });

  it('renders the same timestamp format everywhere, and an em dash for null', () => {
    expect(stamp('2026-11-03T06:15:42')).toBe('2026-11-03 06:15');
    expect(stamp('2026-11-03T06:15:42.123456')).toBe('2026-11-03 06:15');
    expect(stamp(null)).toBe('—');
  });

  it('renders a byte count with one unit and one decimal', () => {
    expect(bytes(512)).toBe('512 B');
    expect(bytes(4194304)).toBe('4.0 MB');
    expect(bytes(null)).toBe('—');
  });

  it('renders a fixed-point number, a signed return and a hit rate', () => {
    expect(fixed(0.8723, 2)).toBe('0.87');
    expect(fixed(null, 2)).toBe('—');
    expect(signedPercent(0.0412)).toBe('+4.1 %');
    expect(signedPercent(-0.013)).toBe('-1.3 %');
    expect(signedPercent(0)).toBe('0.0 %');
    expect(signedPercent(null)).toBe('—');
    expect(share(1)).toBe('100.0 %');
    expect(share(null)).toBe('—');
  });

  it('renders a nullable boolean as yes, no or an em dash', () => {
    expect(yesNo(true)).toBe('yes');
    expect(yesNo(false)).toBe('no');
    expect(yesNo(null)).toBe('—');
  });
});

describe('toFailure', () => {
  it('keeps the status of an HTTP failure', () => {
    const error = new HttpErrorResponse({ status: 503, statusText: 'Service Unavailable' });
    expect(toFailure(error)).toEqual({ status: 503, message: 'Service Unavailable' });
  });

  it('reports a non-HTTP error as status 0 with its message', () => {
    expect(toFailure(new Error('boom'))).toEqual({ status: 0, message: 'boom' });
  });
});
