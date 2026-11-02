# Alert notifications

`newstrading notify` turns the alerts of the analysis pass into messages. The code lives in
`src/newstrading/notify/`; everything it needs is read from PostgreSQL, not from the environment.
This guide describes that configuration and the delivery rules the code implements.

## What a notification pass does

1. Read the single settings row (`notification_settings`, `id = 1`). Without it the pass logs one
   warning and handles nothing.
2. Select the alerts with `notified = FALSE`, newest first, at most 100 per run.
3. For every alert read its preference row, check `enabled`, check `min_confidence`, check the
   quiet-hours window, then send over the channels the preference lists.
4. Write one `notification_log` row per attempted channel and commit the pass once at the end.

An alert is marked notified (`notified = TRUE`, `notified_at = NOW()`) after at least one successful
send. Without a matching active preference, or with a preference whose `min_confidence` the alert
does not reach, it is consumed without a send. A broken channel never raises out of the pass: the
remaining channels of the same alert still run.

## The four senders

| Channel | Sender | Sends | Recipient written to the log |
|---|---|---|---|
| `email` | `EmailSender` | multipart HTML mail per alert | `notification_email` |
| `sms` | `SmsSender` | one text message over the provider HTTP API | `notification_phone` |
| `push` | `PushSender` | one push notification, elevated priority at confidence 0.9 or higher | `pushover_user` |
| `webhook` | `WebhookSender` | `POST` with the alert as JSON | the URL |

The email sender needs `notification_email`, `smtp_user` and `smtp_password`. `smtp_host` falls back
to `smtp.gmail.com`, `smtp_port` to `587`, and `smtp_from` to `smtp_user`. The subject of the message
is `Alert: <asset> (<ticker>) - <alert type>`.

The SMS sender needs `twilio_account_sid`, `twilio_auth_token`, `twilio_from_number` and
`notification_phone`; the body carries the asset, the alert type, the confidence and the first 100
characters of the description.

The push sender needs `pushover_token` and `pushover_user`.

The webhook sender needs `webhook_url` and accepts `200`, `201` and `204`. Its JSON body has the
keys `alert_id`, `asset_name`, `ticker`, `alert_type`, `description`, `confidence_score` and
`timestamp` (ISO 8601).

## Configuration: the `notification_settings` row

The senders read exactly these columns of the single row `notification_settings.id = 1`:

| Column | Used by | Meaning |
|---|---|---|
| `notification_email` | email | recipient address |
| `smtp_host` | email | host, default `smtp.gmail.com` |
| `smtp_port` | email | port, default `587` |
| `smtp_user` | email | login and default sender |
| `smtp_password` | email | password or app password |
| `smtp_from` | email | sender address, falls back to `smtp_user` |
| `notification_phone` | sms | recipient number |
| `twilio_account_sid` | sms | account SID |
| `twilio_auth_token` | sms | auth token |
| `twilio_from_number` | sms | sender number |
| `pushover_token` | push | application token |
| `pushover_user` | push | user key, also the logged recipient |
| `webhook_url` | webhook | endpoint the alert JSON is posted to |

A channel runs only when every column it needs holds a non-empty value. One empty or `NULL`
credential disables the whole channel: the pass logs the attempt with status `skipped` and the
sender's reason, and does not call the provider. The other channels of the same alert still run.

The row is read at the start of every pass, so a changed credential applies to the next run without
a restart. The columns are set in the database — `sql/schema.sql` creates the table — and there is
no environment-variable setup for the senders.

## Preferences: `alert_notification_preferences`

One row per asset and alert type decides whether and how an alert is delivered:

| Column | Meaning |
|---|---|
| `asset_id` | the asset the row applies to |
| `alert_type` | the alert type, or `NULL` for the wildcard row of the asset |
| `min_confidence` | threshold, default `0.80` |
| `notification_channels` | array of channel names, default `ARRAY['email']` |
| `quiet_hours_start` | start of the quiet window, default `22:00` |
| `quiet_hours_end` | end of the quiet window, default `07:00` |
| `enabled` | whether the preference is active, default `TRUE` |

The pass looks the alert up by `(asset_id, alert_type)` and falls back to the `alert_type IS NULL`
row of the same asset. The outcome of a row:

- **No row found, or `enabled = FALSE`** — the alert is marked notified without a send.
- **`confidence_score` below `min_confidence`** — the alert is marked notified without a send.
- **Inside the quiet window** — nothing is sent, logged or marked. The alert is deferred and the
  next pass picks it up again; deferred alerts do not count as handled.
- **Otherwise** — the pass sends over `notification_channels`, in array order. A name that matches
  no sender is logged as a warning and skipped.

Quiet hours include both ends. A window whose start is later than its end crosses midnight, so the
default `22:00`–`07:00` blocks from 22:00 through 07:00, both times included. The window is
evaluated against local time.

## Audit: `notification_log`

Every attempted channel writes one row with `alert_id`, `channel`, `recipient`, `status`,
`sent_at` and `error_message`. The status is one of:

| Status | When | Recipient |
|---|---|---|
| `sent` | the sender returned without an error | the recipient the sender used |
| `failed` | the sender raised, e.g. the provider rejected the message | `unknown` |
| `skipped` | a required column is empty, so the sender was not called | `unknown` |

`error_message` holds the provider text of a failure or the reason of a skip, cut to 500
characters. A failing channel is not retried inside the pass: the alert stays unnotified and the
next pass tries again, while the channels that did deliver are logged as `sent`.

## Known limitation

An alert that reaches no deliverable channel — an empty `notification_channels` array, or every
listed channel skipped or failed — is never marked notified. It is selected again by every pass and,
because the pass always takes the newest 100, such alerts can keep older ones out of the batch
(#34). Until that is fixed, give every active preference at least one configured channel, or
disable the preference so its alerts are consumed.

## Operating it

```bash
uv run newstrading notify          # one pass over the waiting alerts
```

The pass logs what it did to the console; the durable record is the `notification_log` table:

```sql
SELECT alert_id, channel, recipient, status, sent_at, error_message
FROM notification_log
ORDER BY sent_at DESC
LIMIT 20;

SELECT id, asset_id, alert_type, confidence_score, notified, notified_at
FROM alerts
WHERE notified = FALSE
ORDER BY timestamp DESC;
```

An alert that stays in the second result across several passes either has no deliverable channel or
waits for the end of its quiet window.
