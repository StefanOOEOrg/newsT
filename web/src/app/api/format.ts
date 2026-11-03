/**
 * One formatter per value the screens print (#58).
 *
 * The rule of this file: a `null` from the API is the em dash, never `0`. Every table cell and
 * every card goes through these helpers, which is why the templates contain no arithmetic, no
 * `?? 0` and no `toFixed`.
 */

/** The em dash a missing value renders as. */
export const DASH = '—';

/** `null`, `undefined` and the empty string are missing; a real `0` is `0`. */
export function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return DASH;
  }
  return String(value);
}

/** `2026-11-03T06:15:42.123456` -> `2026-11-03 06:15`; one timestamp format everywhere. */
export function stamp(value: string | null | undefined): string {
  if (!value) {
    return DASH;
  }
  return value.slice(0, 16).replace('T', ' ');
}

const BYTE_UNITS = ['kB', 'MB', 'GB', 'TB'] as const;

/** `4194304` -> `4.0 MB`; below one kB the plain byte count. */
export function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return DASH;
  }
  if (value < 1024) {
    return `${value} B`;
  }
  let amount = value / 1024;
  let unit = 0;
  while (amount >= 1024 && unit < BYTE_UNITS.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(1)} ${BYTE_UNITS[unit]}`;
}

/** A fixed-point number (`0.8723` -> `0.87`) or the em dash. */
export function fixed(value: number | null | undefined, digits: number): string {
  if (value === null || value === undefined) {
    return DASH;
  }
  return value.toFixed(digits);
}

/** A decimal return (`0.0412` = 4.12 %) with its sign: `+4.1 %`. */
export function signedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return DASH;
  }
  const percent = value * 100;
  return `${percent > 0 ? '+' : ''}${percent.toFixed(1)} %`;
}

/** A decimal share (`0.5` = 50 %) without a sign: `50.0 %`. */
export function share(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return DASH;
  }
  return `${(value * 100).toFixed(1)} %`;
}

/** A nullable boolean as `yes`/`no`, or the em dash when nothing decided it yet. */
export function yesNo(value: boolean | null | undefined): string {
  if (value === null || value === undefined) {
    return DASH;
  }
  return value ? 'yes' : 'no';
}

/** The colour class of a log level; anything unknown stays muted, never an error. */
export function levelTone(level: string): 'err' | 'warn' | 'ok' | 'muted' {
  switch (level.toUpperCase()) {
    case 'ERROR':
    case 'CRITICAL':
    case 'FATAL':
      return 'err';
    case 'WARNING':
    case 'WARN':
      return 'warn';
    case 'INFO':
      return 'ok';
    default:
      return 'muted';
  }
}

/** The JSONB `metadata` column as one line, or the em dash when it is NULL. */
export function metadataText(metadata: unknown): string {
  if (metadata === null || metadata === undefined) {
    return DASH;
  }
  if (typeof metadata === 'string') {
    return metadata === '' ? DASH : metadata;
  }
  return JSON.stringify(metadata);
}
