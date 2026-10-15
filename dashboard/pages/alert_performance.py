"""
Alert Performance Page - Backtest and analyze trading alert performance.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from services.database import fetch_data


def render():
    """Render the Alert Performance page."""
    st.title("📊 Alert Performance & Backtesting")
    st.markdown("Track the performance of trading alerts by analyzing actual price movements")

    # Get available alert types
    alert_types_df = fetch_data("SELECT DISTINCT alert_type FROM alert_performance ORDER BY alert_type")
    alert_types = alert_types_df['alert_type'].tolist() if not alert_types_df.empty else []

    # Filters
    col1, col2, col3 = st.columns(3)

    with col1:
        selected_alert_type = st.selectbox(
            "Alert Type Filter",
            options=["All"] + alert_types,
            index=0
        )

    with col2:
        time_period = st.selectbox(
            "Time Period",
            options=["Last 7 Days", "Last 30 Days", "Last 90 Days", "All Time"],
            index=1
        )

    with col3:
        min_confidence = st.slider(
            "Min Confidence",
            min_value=0.0,
            max_value=1.0,
            value=0.0,
            step=0.05
        )

    # Map time period to days
    period_days = {
        "Last 7 Days": 7,
        "Last 30 Days": 30,
        "Last 90 Days": 90,
        "All Time": 99999
    }[time_period]

    # Build query filters
    time_filter = f"AND ap.alert_date >= NOW() - INTERVAL '{period_days} days'" if period_days < 99999 else ""
    type_filter = f"AND ap.alert_type = '{selected_alert_type}'" if selected_alert_type != "All" else ""

    # === SUMMARY METRICS ===
    st.header("Performance Summary")

    summary_df = fetch_data(f"""
        SELECT
            COUNT(*) as total_alerts,
            COUNT(CASE WHEN correct_7d = TRUE THEN 1 END)::FLOAT / NULLIF(COUNT(CASE WHEN correct_7d IS NOT NULL THEN 1 END), 0) * 100 as win_rate_7d,
            AVG(return_7d) * 100 as avg_return_7d,
            AVG(return_3d) * 100 as avg_return_3d,
            AVG(return_1d) * 100 as avg_return_1d
        FROM alert_performance ap
        WHERE ap.confidence_score >= {min_confidence}
        {time_filter}
        {type_filter}
    """)

    if not summary_df.empty:
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.metric("Total Alerts", f"{int(summary_df['total_alerts'].iloc[0]):,}")

        with col2:
            win_rate = summary_df['win_rate_7d'].iloc[0] if pd.notna(summary_df['win_rate_7d'].iloc[0]) else 0
            st.metric("7-Day Win Rate", f"{win_rate:.1f}%")

        with col3:
            avg_7d = summary_df['avg_return_7d'].iloc[0] if pd.notna(summary_df['avg_return_7d'].iloc[0]) else 0
            st.metric("Avg 7-Day Return", f"{avg_7d:+.2f}%", delta=f"{avg_7d:.2f}%")

        with col4:
            avg_3d = summary_df['avg_return_3d'].iloc[0] if pd.notna(summary_df['avg_return_3d'].iloc[0]) else 0
            st.metric("Avg 3-Day Return", f"{avg_3d:+.2f}%")

        with col5:
            avg_1d = summary_df['avg_return_1d'].iloc[0] if pd.notna(summary_df['avg_return_1d'].iloc[0]) else 0
            st.metric("Avg 1-Day Return", f"{avg_1d:+.2f}%")

    st.divider()

    # === PERFORMANCE BY ALERT TYPE ===
    st.header("Performance by Alert Type")

    df_by_type = fetch_data(f"""
        SELECT
            ap.alert_type,
            COUNT(*) as total_alerts,
            COUNT(CASE WHEN correct_7d = TRUE THEN 1 END)::FLOAT / NULLIF(COUNT(CASE WHEN correct_7d IS NOT NULL THEN 1 END), 0) * 100 as win_rate_7d,
            AVG(return_7d) * 100 as avg_return_7d,
            AVG(return_3d) * 100 as avg_return_3d,
            AVG(return_1d) * 100 as avg_return_1d,
            AVG(confidence_score) * 100 as avg_confidence
        FROM alert_performance ap
        WHERE ap.confidence_score >= {min_confidence}
        {time_filter}
        {type_filter}
        GROUP BY ap.alert_type
        ORDER BY win_rate_7d DESC NULLS LAST
    """)

    if not df_by_type.empty:
        # Format the dataframe
        df_by_type['total_alerts'] = df_by_type['total_alerts'].astype(int)
        df_by_type = df_by_type.rename(columns={
            'alert_type': 'Alert Type',
            'total_alerts': 'Total',
            'win_rate_7d': 'Win Rate 7d (%)',
            'avg_return_7d': 'Avg Return 7d (%)',
            'avg_return_3d': 'Avg Return 3d (%)',
            'avg_return_1d': 'Avg Return 1d (%)',
            'avg_confidence': 'Avg Confidence (%)'
        })

        for col in ['Win Rate 7d (%)', 'Avg Return 7d (%)', 'Avg Return 3d (%)', 'Avg Return 1d (%)', 'Avg Confidence (%)']:
            df_by_type[col] = df_by_type[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "N/A")

        st.dataframe(df_by_type, use_container_width=True, hide_index=True)

        # Charts
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Win Rate by Alert Type")
            df_chart = df_by_type.copy()
            df_chart['Win Rate 7d (%)'] = pd.to_numeric(df_chart['Win Rate 7d (%)'], errors='coerce')
            df_chart = df_chart.dropna(subset=['Win Rate 7d (%)'])

            if not df_chart.empty:
                fig = px.bar(
                    df_chart,
                    x='Alert Type',
                    y='Win Rate 7d (%)',
                    color='Win Rate 7d (%)',
                    color_continuous_scale=['red', 'yellow', 'green'],
                    range_color=[0, 100]
                )
                fig.update_layout(height=400, showlegend=False)
                fig.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="50% Baseline")
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Avg 7-Day Return by Type")
            df_chart = df_by_type.copy()
            df_chart['Avg Return 7d (%)'] = pd.to_numeric(df_chart['Avg Return 7d (%)'], errors='coerce')
            df_chart = df_chart.dropna(subset=['Avg Return 7d (%)'])

            if not df_chart.empty:
                fig = px.bar(
                    df_chart,
                    x='Alert Type',
                    y='Avg Return 7d (%)',
                    color='Avg Return 7d (%)',
                    color_continuous_scale='RdYlGn'
                )
                fig.update_layout(height=400, showlegend=False)
                fig.add_hline(y=0, line_dash="dash", line_color="gray")
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No performance data available for the selected filters")

    st.divider()

    # === PERFORMANCE BY ASSET ===
    st.header("Performance by Asset")

    df_by_asset = fetch_data(f"""
        SELECT
            c.name,
            c.ticker,
            COUNT(*) as total_alerts,
            COUNT(CASE WHEN ap.correct_7d = TRUE THEN 1 END)::FLOAT / NULLIF(COUNT(CASE WHEN ap.correct_7d IS NOT NULL THEN 1 END), 0) * 100 as win_rate_7d,
            AVG(ap.return_7d) * 100 as avg_return_7d
        FROM alert_performance ap
        JOIN asset c ON ap.asset_id = c.id
        WHERE ap.confidence_score >= {min_confidence}
        {time_filter}
        {type_filter}
        GROUP BY c.name, c.ticker
        ORDER BY win_rate_7d DESC NULLS LAST
    """)

    if not df_by_asset.empty:
        df_by_asset['total_alerts'] = df_by_asset['total_alerts'].astype(int)
        df_by_asset = df_by_asset.rename(columns={
            'name': 'Asset',
            'ticker': 'Ticker',
            'total_alerts': 'Total',
            'win_rate_7d': 'Win Rate 7d (%)',
            'avg_return_7d': 'Avg Return 7d (%)'
        })
        df_by_asset['Win Rate 7d (%)'] = df_by_asset['Win Rate 7d (%)'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "N/A")
        df_by_asset['Avg Return 7d (%)'] = df_by_asset['Avg Return 7d (%)'].apply(lambda x: f"{x:+.2f}" if pd.notna(x) else "N/A")

        st.dataframe(df_by_asset, use_container_width=True, hide_index=True)
    else:
        st.info("No performance data available by asset")

    st.divider()

    # === CUMULATIVE RETURNS ===
    st.header("Cumulative Returns Over Time")
    st.markdown("Simulated portfolio performance if all alerts were traded with equal position sizes")

    returns_df = fetch_data(f"""
        SELECT
            ap.alert_date,
            ap.return_7d
        FROM alert_performance ap
        WHERE ap.return_7d IS NOT NULL
          AND ap.confidence_score >= {min_confidence}
        {time_filter}
        {type_filter}
        ORDER BY ap.alert_date
    """)

    if not returns_df.empty:
        returns_df['cumulative_return'] = (1 + returns_df['return_7d']).cumprod() - 1
        returns_df['cumulative_return_pct'] = returns_df['cumulative_return'] * 100

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=returns_df['alert_date'],
            y=returns_df['cumulative_return_pct'],
            mode='lines',
            name='Cumulative Return',
            line=dict(color='blue', width=2),
            fill='tozeroy',
            fillcolor='rgba(0, 100, 255, 0.1)'
        ))

        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(
            height=400,
            xaxis_title="Date",
            yaxis_title="Cumulative Return (%)",
            hovermode='x unified'
        )

        st.plotly_chart(fig, use_container_width=True)

        final_return = returns_df['cumulative_return_pct'].iloc[-1]
        st.success(f"📈 Final cumulative return: **{final_return:+.2f}%** ({len(returns_df)} alerts)")
    else:
        st.info("Not enough data to show cumulative returns")

    st.divider()

    # === CONFIDENCE OPTIMIZATION ===
    st.header("Confidence Score Optimization")
    st.markdown("Find the optimal confidence threshold for your trading strategy")

    confidence_df = fetch_data(f"""
        SELECT
            ROUND(ap.confidence_score * 20) / 20 as confidence_bucket,
            COUNT(*) as total,
            COUNT(CASE WHEN ap.correct_7d = TRUE THEN 1 END)::FLOAT / NULLIF(COUNT(CASE WHEN ap.correct_7d IS NOT NULL THEN 1 END), 0) * 100 as win_rate
        FROM alert_performance ap
        WHERE ap.correct_7d IS NOT NULL
        {time_filter}
        {type_filter}
        GROUP BY confidence_bucket
        HAVING COUNT(*) >= 3
        ORDER BY confidence_bucket
    """)

    if not confidence_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=confidence_df['confidence_bucket'],
            y=confidence_df['win_rate'],
            mode='lines+markers',
            name='Win Rate',
            marker=dict(size=confidence_df['total'] * 2, sizemode='diameter'),
            line=dict(color='green', width=2)
        ))

        fig.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="50% Baseline")
        fig.update_layout(
            height=400,
            xaxis_title="Confidence Score",
            yaxis_title="7-Day Win Rate (%)",
            hovermode='x unified'
        )

        st.plotly_chart(fig, use_container_width=True)
        st.caption("Marker size represents number of alerts in that confidence bucket (min 3 alerts per bucket)")
    else:
        st.info("Not enough data to analyze confidence vs win rate")

    st.divider()
    st.caption("💡 Tip: Adjust filters above to analyze specific alert types or time periods")
