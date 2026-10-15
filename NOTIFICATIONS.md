# Alert Notification System

Get instantly notified when high-confidence trading alerts are generated.

## Features

- **Multiple Channels**: Email, SMS (Twilio), Push (Pushover), Webhook
- **Configurable Thresholds**: Set minimum confidence levels per alert type
- **Quiet Hours**: No notifications during sleep hours (default: 22:00-07:00)
- **Per-Alert Customization**: Different settings for Hiring, Negative Sentiment, and Problem alerts
- **Real-time Delivery**: Notifications sent within 1-5 minutes of alert generation

## Quick Setup

### 1. Configure Email Notifications (Recommended)

The easiest way to get started is with email notifications using Gmail:

1. Go to **Dashboard → Settings → Notification Settings**

2. Enter your email configuration:
   - **Email Address**: Your email where you want to receive alerts
   - **SMTP Username**: Your Gmail address (e.g., your.email@gmail.com)
   - **SMTP Password**: Your Gmail App Password (see below)

3. Configure alert preferences:
   - **Hiring Signal**: Min confidence 0.85, Email enabled
   - **Negative Sentiment**: Min confidence 0.85, Email enabled
   - **Problem Detected**: Min confidence 0.80, Email enabled

4. Set quiet hours (default 22:00-07:00)

5. Click "Save Notification Settings"

6. Restart the notifier service:
   ```bash
   docker-compose restart notifier
   ```

### Gmail App Password Setup

Gmail requires an "App Password" for SMTP access:

1. Go to your Google Account: https://myaccount.google.com/
2. Navigate to "Security"
3. Enable "2-Step Verification" (if not already enabled)
4. Under "2-Step Verification", find "App passwords"
5. Generate a new app password for "Mail"
6. Copy the 16-character password (without spaces)
7. Use this as your SMTP_PASSWORD

## Supported Notification Channels

### 1. Email (SMTP)

**Configuration:**
```env
# .env file
NOTIFICATION_EMAIL=your.email@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your.email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your.email@gmail.com  # Optional, defaults to SMTP_USER
```

**Supported Providers:**
- Gmail (smtp.gmail.com:587)
- Outlook (smtp-mail.outlook.com:587)
- Yahoo (smtp.mail.yahoo.com:587)
- Custom SMTP server

**Example Email:**
```
Subject: 🔔 Alert: Genpact (G) - Hiring Signal

Company: Genpact (G)
Alert Type: Hiring Signal
Confidence: 0.92
Time: 2025-11-17 14:30:15

Description:
Multiple job postings detected across LinkedIn and Glassdoor for AI/ML
positions. Indicates strong hiring momentum and potential expansion...

View Dashboard: http://localhost:8501
```

### 2. SMS (Twilio)

**Setup:**

1. Create Twilio account: https://www.twilio.com/try-twilio
2. Get your Account SID and Auth Token from dashboard
3. Purchase a phone number
4. Configure in .env:

```env
NOTIFICATION_PHONE=+1234567890
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+1987654321
```

5. Install Twilio library (already in requirements):
```bash
pip install twilio
```

**Example SMS:**
```
🔔 Alert: Genpact (G)
Hiring Signal
Confidence: 0.92
Multiple job postings detected across LinkedIn...
```

### 3. Push Notifications (Pushover)

**Setup:**

1. Create Pushover account: https://pushover.net/
2. Install Pushover app on your phone (iOS/Android)
3. Get your User Key from dashboard
4. Create an application to get API Token
5. Configure in .env:

```env
PUSHOVER_TOKEN=your_app_token
PUSHOVER_USER=your_user_key
```

**Features:**
- High-priority alerts (confidence >= 0.9)
- Click-through to dashboard
- Rich notifications with company info

### 4. Webhook

Send alerts to any HTTP endpoint (e.g., Slack, Discord, custom API):

**Configuration:**
```env
WEBHOOK_URL=https://your-endpoint.com/alerts
```

**Payload:**
```json
{
  "alert_id": 123,
  "company_name": "Genpact",
  "ticker": "G",
  "alert_type": "hiring_signal",
  "description": "Multiple job postings detected...",
  "confidence_score": 0.92,
  "timestamp": "2025-11-17T14:30:15"
}
```

**Slack Example:**

Create a Slack incoming webhook, then use a wrapper service like Zapier or create a simple proxy:

```python
# webhook_proxy.py - Forward to Slack
from flask import Flask, request
import requests

app = Flask(__name__)
SLACK_WEBHOOK = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

@app.route('/alerts', methods=['POST'])
def forward_to_slack():
    data = request.json
    slack_msg = {
        "text": f"🔔 *{data['company_name']} ({data['ticker']})* Alert",
        "attachments": [{
            "color": "good" if data['confidence_score'] >= 0.85 else "warning",
            "fields": [
                {"title": "Type", "value": data['alert_type'], "short": True},
                {"title": "Confidence", "value": f"{data['confidence_score']:.2f}", "short": True},
                {"title": "Description", "value": data['description']}
            ]
        }]
    }
    requests.post(SLACK_WEBHOOK, json=slack_msg)
    return "OK", 200
```

## Alert Type Settings

### Hiring Signal 💼
- **Default Confidence**: 0.85
- **Use Case**: Early indicator of company expansion
- **Example**: "3+ job postings in 24h indicates strong hiring momentum"

### Negative Sentiment ⚠️
- **Default Confidence**: 0.85
- **Use Case**: Risk detection, potential bearish signal
- **Example**: "Widespread negative reviews, potential reputation damage"

### Problem Detected 🔴
- **Default Confidence**: 0.80
- **Use Case**: Critical issues, major red flags
- **Example**: "SEC investigation announced, legal troubles reported"

## Configuration via Dashboard

Navigate to **Settings → Notification Settings** to configure:

### Global Settings
- **Email Address**: Where to receive email alerts
- **Phone Number**: For SMS alerts (format: +1234567890)
- **SMTP Credentials**: For sending emails
- **Check Interval**: How often to check for new alerts (default: 5 minutes)

### Per-Alert Settings
For each alert type (Hiring, Negative Sentiment, Problem):
- **Enable/Disable**: Turn notifications on/off
- **Min Confidence**: Threshold (0.0-1.0)
- **Channels**: Select email, sms, push, webhook

### Quiet Hours
- **Start Time**: When to stop sending notifications (default: 22:00)
- **End Time**: When to resume notifications (default: 07:00)

**Note**: Quiet hours span midnight (e.g., 22:00-07:00 means no notifications from 10 PM to 7 AM)

## Environment Variables Reference

```env
# Email Configuration
NOTIFICATION_EMAIL=your.email@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your.email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your.email@gmail.com

# SMS Configuration (Optional)
NOTIFICATION_PHONE=+1234567890
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+1987654321

# Push Configuration (Optional)
PUSHOVER_TOKEN=your_app_token
PUSHOVER_USER=your_user_key

# Webhook Configuration (Optional)
WEBHOOK_URL=https://your-endpoint.com/alerts

# Service Configuration
NOTIFICATION_CHECK_INTERVAL=5  # Minutes between checks
LOG_LEVEL=INFO
```

## Testing Notifications

### 1. Test Email Manually

```bash
docker-compose exec notifier python3 -c "
import os
import smtplib
from email.mime.text import MIMEText

msg = MIMEText('Test alert from News Trading System')
msg['Subject'] = 'Test Alert'
msg['From'] = os.getenv('SMTP_USER')
msg['To'] = os.getenv('NOTIFICATION_EMAIL')

with smtplib.SMTP(os.getenv('SMTP_HOST'), int(os.getenv('SMTP_PORT'))) as server:
    server.starttls()
    server.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD'))
    server.send_message(msg)

print('Test email sent!')
"
```

### 2. Trigger a Test Alert

Create a high-confidence alert manually in the database:

```bash
docker-compose exec -T postgres psql -U trading -d newstrading <<EOF
INSERT INTO alerts (company_id, alert_type, description, confidence_score)
VALUES (
    (SELECT id FROM companies LIMIT 1),
    'hiring_signal',
    'Test alert - please ignore',
    0.95
);
EOF
```

Wait 1-5 minutes for the notifier service to pick it up and send notification.

### 3. Check Notification Logs

```bash
# View notifier service logs
docker-compose logs -f notifier

# Check database notification log
docker-compose exec -T postgres psql -U trading -d newstrading -c "
SELECT * FROM notification_log ORDER BY sent_at DESC LIMIT 10;
"
```

## Troubleshooting

### No notifications received

1. **Check notifier service status:**
   ```bash
   docker-compose ps notifier
   docker-compose logs notifier --tail=50
   ```

2. **Verify database preferences:**
   ```bash
   docker-compose exec -T postgres psql -U trading -d newstrading -c "
   SELECT * FROM alert_notification_preferences;
   "
   ```

3. **Check for unnotified alerts:**
   ```bash
   docker-compose exec -T postgres psql -U trading -d newstrading -c "
   SELECT id, company_id, alert_type, confidence_score, notified
   FROM alerts
   WHERE notified = FALSE
   ORDER BY timestamp DESC;
   "
   ```

4. **Test SMTP connection:**
   ```bash
   docker-compose exec notifier python3 -c "
   import os, smtplib
   with smtplib.SMTP(os.getenv('SMTP_HOST'), int(os.getenv('SMTP_PORT'))) as s:
       s.starttls()
       s.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD'))
       print('SMTP connection successful!')
   "
   ```

### Gmail "Less secure app" error

Gmail requires App Passwords (see setup section above). Regular passwords won't work with 2FA enabled.

### Notifications during quiet hours

Check system time zone alignment:
```bash
docker-compose exec notifier python3 -c "
from datetime import datetime
print(f'Container time: {datetime.now()}')
"
```

If timezone is wrong, set in docker-compose.yml:
```yaml
notifier:
  environment:
    - TZ=Europe/Vienna  # Your timezone
```

### High notification volume

Increase minimum confidence thresholds in Settings to reduce noise:
- Hiring: 0.85 → 0.90
- Negative Sentiment: 0.85 → 0.90
- Problem: 0.80 → 0.85

Or increase check interval from 5 minutes to 15-30 minutes.

## Architecture

```
┌─────────────┐
│  Analyzer   │ Creates alerts in database
└──────┬──────┘
       │
       v
┌─────────────┐
│  Database   │ Stores alerts (notified=false)
└──────┬──────┘
       │
       v
┌─────────────┐
│  Notifier   │ Checks every 5 min, sends notifications
└──────┬──────┘
       │
       ├──→ Email (SMTP)
       ├──→ SMS (Twilio)
       ├──→ Push (Pushover)
       └──→ Webhook
```

## Performance

- **Latency**: 1-5 minutes from alert creation to notification (based on check interval)
- **Reliability**: Notifications logged to database for audit trail
- **Retry**: Failed notifications logged but not retried (check logs manually)
- **Rate Limits**:
  - Email: Depends on SMTP provider (Gmail: ~500/day)
  - SMS: Depends on Twilio plan
  - Push: Pushover has generous limits (10,000/month free tier)

## Security

- **Credentials**: Store sensitive data in .env file, never commit to git
- **SMTP**: Use app-specific passwords, not your main account password
- **Twilio**: Rotate auth tokens regularly
- **Webhooks**: Use HTTPS endpoints, validate requests if possible

## Future Enhancements

See [IDEAS.md](IDEAS.md) Section 3.2 for planned features:
- Daily digest emails
- Per-company notification preferences
- Alert clustering (send 1 notification for 3+ similar alerts)
- Notification scheduling (specific days/times)
- Mobile app integration

## Support

For issues or questions:
1. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Review notifier logs: `docker-compose logs notifier`
3. Open GitHub issue with logs and configuration (redact credentials!)
