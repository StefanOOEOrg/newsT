-- Migration: Add special event detection to analysis prompt
-- Date: 2025-11-19

UPDATE notification_settings
SET analysis_prompt = 'Analyze this social media post about {asset_name} ({ticker}) from a trading perspective.

{text_to_analyze}

Provide your analysis in JSON format with these fields:
- sentiment: one of "positive", "negative", or "neutral"
- sentiment_score: a number between -1.0 (very bearish/short signal) and 1.0 (very bullish/long signal)
- category: one of "Hiring", "Growth", "Problems", "Product", "Earnings", "Other"
- key_topics: array of 2-5 key topics or themes (as strings)
- summary: brief summary in 1-2 sentences (max 100 words)
- special_events: array of detected special events (if any), each event should be one of:
  * "partnership_announced"
  * "product_launch"
  * "regulatory_risk"
  * "analyst_upgrade"
  * "analyst_downgrade"
  * "market_share_gain"
  * "customer_loss"
  * "executive_change"
  * "guidance_raise"
  * "guidance_cut"
  * "insider_buying"
  * "insider_selling"
  Leave empty array [] if no special events detected.

Focus on identifying trading signals:
- BULLISH (long signals): hiring, partnerships, product launches, earnings beats, growth indicators, positive guidance, analyst upgrades, insider buying, market share gains
- BEARISH (short signals): problems, layoffs, negative sentiment, downgrades, missed earnings, legal issues, regulatory risks, guidance cuts, insider selling, customer losses

Return ONLY valid JSON, no other text.'
WHERE id = 1;
