"""
Alerts Page - View and filter system alerts.
"""
import streamlit as st
import pandas as pd

from services.database import fetch_data


def render():
    """Render the Alerts page."""
    # Filters
    col1, col2 = st.columns(2)

    with col1:
        assets_df = fetch_data("SELECT id, name FROM asset ORDER BY name")
        asset_filter = st.selectbox(
            "Filter by Asset",
            options=["All"] + assets_df['name'].tolist() if not assets_df.empty else ["All"]
        )

    with col2:
        alert_types = ["All", "long_signal", "short_signal", "hiring_signal", "risk_detected"]
        alert_type_filter = st.selectbox("Filter by Alert Type", options=alert_types)

    # Build query
    alerts_query = """
        SELECT
            a.timestamp,
            c.name as asset_name,
            c.ticker,
            a.alert_type,
            a.severity,
            a.description,
            a.confidence_score
        FROM alerts a
        JOIN asset c ON a.asset_id = c.id
        WHERE 1=1
    """
    params = []

    if asset_filter != "All":
        alerts_query += " AND c.name = %s"
        params.append(asset_filter)

    if alert_type_filter != "All":
        alerts_query += " AND a.alert_type = %s"
        params.append(alert_type_filter)

    alerts_query += " ORDER BY a.timestamp DESC LIMIT 100"

    alerts_df = fetch_data(alerts_query, tuple(params) if params else None)

    if not alerts_df.empty:
        st.subheader(f"Recent Alerts ({len(alerts_df)})")

        for _, alert in alerts_df.iterrows():
            # Get severity (default to 'medium' for backward compatibility)
            severity = alert.get('severity', 'medium')

            # Color code by alert type and severity
            # Using dark background to match dashboard theme
            bg_color = "#1E1E1E"  # Dark background for all alerts

            if alert['alert_type'] == 'long_signal':
                # Long signal (bullish) - green/blue colors
                if severity == 'high':
                    icon = "High"
                    border_color = "#28a745"
                    severity_badge = "<span style='background-color: #28a745; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>STRONG LONG</span>"
                elif severity == 'medium':
                    icon = "Medium"
                    border_color = "#20c997"
                    severity_badge = "<span style='background-color: #20c997; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>MODERATE LONG</span>"
                else:  # low
                    icon = "Low"
                    border_color = "#17a2b8"
                    severity_badge = "<span style='background-color: #17a2b8; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>WEAK LONG</span>"
            elif alert['alert_type'] == 'short_signal':
                # Short signal (bearish) - red/orange colors
                if severity == 'high':
                    icon = "High"
                    border_color = "#dc3545"
                    severity_badge = "<span style='background-color: #dc3545; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>STRONG SHORT</span>"
                elif severity == 'medium':
                    icon = "Medium"
                    border_color = "#fd7e14"
                    severity_badge = "<span style='background-color: #fd7e14; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>MODERATE SHORT</span>"
                else:  # low
                    icon = "Low"
                    border_color = "#ffc107"
                    severity_badge = "<span style='background-color: #ffc107; color: #212529; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>WEAK SHORT</span>"
            # Special event alert types
            elif alert['alert_type'] == 'partnership':
                icon = "Partnership"
                border_color = "#17a2b8"
                severity_badge = f"<span style='background-color: #17a2b8; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'product_launch':
                icon = "Product Launch"
                border_color = "#28a745"
                severity_badge = f"<span style='background-color: #28a745; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'regulatory_risk':
                icon = "Regulatory Risk"
                border_color = "#dc3545"
                severity_badge = f"<span style='background-color: #dc3545; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'analyst_upgrade':
                icon = "Analyst Upgrade"
                border_color = "#28a745"
                severity_badge = f"<span style='background-color: #28a745; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'analyst_downgrade':
                icon = "Analyst Downgrade"
                border_color = "#dc3545"
                severity_badge = f"<span style='background-color: #dc3545; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'market_share':
                icon = "Market Share"
                border_color = "#20c997"
                severity_badge = f"<span style='background-color: #20c997; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'customer_loss':
                icon = "Customer Loss"
                border_color = "#fd7e14"
                severity_badge = f"<span style='background-color: #fd7e14; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'executive_change':
                icon = "Executive Change"
                border_color = "#6f42c1"
                severity_badge = f"<span style='background-color: #6f42c1; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'guidance':
                icon = "Guidance"
                border_color = "#ffc107"
                severity_badge = f"<span style='background-color: #ffc107; color: #212529; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            elif alert['alert_type'] == 'insider_trading':
                icon = "Insider Trading"
                border_color = "#007bff"
                severity_badge = f"<span style='background-color: #007bff; color: white; padding: 2px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;'>{severity.upper()}</span>"
            # Legacy alert types (for backward compatibility)
            elif alert['alert_type'] == 'hiring_signal':
                icon = "Hiring Signal"
                border_color = "#007bff"
                severity_badge = ""
            elif alert['alert_type'] == 'risk_detected':
                icon = "Risk Detected"
                border_color = "#dc3545"
                severity_badge = ""
            elif alert['alert_type'] == 'negative_sentiment':
                icon = "Negative Sentiment"
                border_color = "#dc3545"
                severity_badge = ""
            elif alert['alert_type'] == 'problem_detected':
                icon = "Problem Detected"
                border_color = "#fd7e14"
                severity_badge = ""
            else:
                icon = "Info"
                border_color = "#6c757d"
                severity_badge = ""

            with st.container():
                timestamp_str = alert['timestamp'].strftime('%Y-%m-%d %H:%M') if hasattr(alert['timestamp'], 'strftime') else alert['timestamp']
                st.markdown(f"""
                <div style="
                    padding: 15px;
                    border-left: 5px solid {border_color};
                    background-color: {bg_color};
                    margin-bottom: 15px;
                    border-radius: 5px;
                    color: #E0E0E0;
                ">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                        <div style="font-size: 16px; font-weight: bold; color: #FFFFFF;">
                            {icon} {alert['asset_name']} ({alert['ticker']}) {severity_badge}
                        </div>
                        <div style="font-size: 14px; font-weight: bold; text-align: right; color: #B0B0B0;">
                            Confidence: {alert['confidence_score']:.2f}<br>
                            {timestamp_str}
                        </div>
                    </div>
                    <div style="font-style: italic; color: #888888; margin-bottom: 8px;">
                        {alert['alert_type'].replace('_', ' ').title()}
                    </div>
                    <div style="color: #E0E0E0;">
                        {alert['description']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("No alerts found.")
