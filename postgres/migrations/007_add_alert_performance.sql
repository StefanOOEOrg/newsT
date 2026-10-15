-- Migration 007: Add Alert Performance Tracking
-- Description: Track stock price movements after alerts for backtesting and validation

CREATE TABLE IF NOT EXISTS alert_performance (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id) ON DELETE CASCADE,
    asset_id INTEGER REFERENCES asset(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL,
    alert_date TIMESTAMP NOT NULL,
    confidence_score DECIMAL(5,2),

    -- Price data at alert time
    price_at_alert DECIMAL(10,2),

    -- Price data at future intervals
    price_1d_later DECIMAL(10,2),
    price_3d_later DECIMAL(10,2),
    price_7d_later DECIMAL(10,2),
    price_14d_later DECIMAL(10,2),
    price_30d_later DECIMAL(10,2),

    -- Return calculations
    return_1d DECIMAL(10,4),
    return_3d DECIMAL(10,4),
    return_7d DECIMAL(10,4),
    return_14d DECIMAL(10,4),
    return_30d DECIMAL(10,4),

    -- Directional analysis
    predicted_direction VARCHAR(10), -- 'bullish', 'bearish', 'neutral'
    actual_direction_1d VARCHAR(10),
    actual_direction_3d VARCHAR(10),
    actual_direction_7d VARCHAR(10),

    -- Accuracy tracking
    correct_1d BOOLEAN,
    correct_3d BOOLEAN,
    correct_7d BOOLEAN,

    -- Tracking metadata
    last_updated TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_alert_performance_alert_id ON alert_performance(alert_id);
CREATE INDEX idx_alert_performance_asset_id ON alert_performance(asset_id);
CREATE INDEX idx_alert_performance_alert_type ON alert_performance(alert_type);
CREATE INDEX idx_alert_performance_alert_date ON alert_performance(alert_date);
CREATE INDEX idx_alert_performance_confidence ON alert_performance(confidence_score);

-- Comments
COMMENT ON TABLE alert_performance IS 'Tracks stock price movements after alerts for backtesting and validation';
COMMENT ON COLUMN alert_performance.predicted_direction IS 'Direction predicted by alert: bullish (long), bearish (short), neutral';
COMMENT ON COLUMN alert_performance.return_1d IS 'Price return 1 day after alert as decimal (e.g., 0.05 = 5%)';
COMMENT ON COLUMN alert_performance.correct_1d IS 'True if predicted direction matches actual price movement';
