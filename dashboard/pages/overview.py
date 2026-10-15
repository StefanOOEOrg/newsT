"""
Overview Page - Dashboard main overview with system health and asset metrics.
"""
import streamlit as st
import pandas as pd
from datetime import datetime
import sys
from pathlib import Path
import os

from services.database import fetch_data

# Import collector factory to get collector instances
try:
    collector_path = Path(__file__).parent.parent.parent / 'collector'
    if collector_path.exists():
        sys.path.insert(0, str(collector_path))
    from collector_factory import get_factory
    COLLECTORS_AVAILABLE = True
except ImportError:
    COLLECTORS_AVAILABLE = False


def render():
    """Render the Overview page."""
    # Custom CSS for Overview page - reduce font sizes to 2 levels
    st.markdown("""
        <style>
        /* Overview page: limit to 2 font sizes */
        [data-testid="stAppViewContainer"] h3 {
            font-size: 1.2rem !important;  /* Smaller subheaders */
            margin-top: 0.5rem !important;
            margin-bottom: 0.5rem !important;
        }
        /* Align all metric values to same font size */
        [data-testid="stMetricValue"] {
            font-size: 1.5rem !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.875rem !important;
        }
        /* Regular text stays default size */
        </style>
    """, unsafe_allow_html=True)

    # ========================================================================
    # SYSTEM HEALTH STATUS
    # ========================================================================

    # Fetch system health metrics
    health_query = """
        SELECT
            (
                SELECT MAX(timestamp)
                FROM system_logs
                WHERE service = 'analyzer'
            ) as last_analyzer_run,
            (
                SELECT COUNT(*)
                FROM system_logs
                WHERE service = 'analyzer'
                  AND level = 'ERROR'
                  AND timestamp >= NOW() - INTERVAL '1 hour'
            ) as analyzer_errors_1h,
            (
                SELECT MAX(analyzed_at)
                FROM ai_analysis
            ) as last_post_analyzed,
            (
                SELECT COUNT(*)
                FROM system_logs
                WHERE level = 'WARNING'
                  AND timestamp >= NOW() - INTERVAL '24 hours'
            ) as total_warnings_24h,
            (
                SELECT COUNT(*)
                FROM system_logs
                WHERE level = 'ERROR'
                  AND timestamp >= NOW() - INTERVAL '24 hours'
            ) as total_errors_24h
    """

    health_df = fetch_data(health_query)

    if not health_df.empty:
        health = health_df.iloc[0]

        # Single row with all metrics
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            # Analyzer status
            last_analyzer = health['last_analyzer_run']
            analyzer_errors = int(health['analyzer_errors_1h']) if pd.notna(health['analyzer_errors_1h']) else 0

            if pd.notna(last_analyzer):
                time_diff = datetime.now() - last_analyzer.replace(tzinfo=None)
                minutes_ago = int(time_diff.total_seconds() / 60)

                if minutes_ago < 60:
                    analyzer_status = f"Active ({minutes_ago}m ago)"
                elif minutes_ago < 180:
                    analyzer_status = f"Delayed ({minutes_ago}m ago)"
                else:
                    analyzer_status = f"Stale ({minutes_ago}m ago)"
            else:
                analyzer_status = "No data"

            st.metric("Analyzer", analyzer_status)
            if analyzer_errors > 0:
                # Check for API credit errors
                api_credit_error_query = """
                    SELECT COUNT(*)
                    FROM system_logs
                    WHERE service = 'analyzer'
                      AND level = 'ERROR'
                      AND timestamp >= NOW() - INTERVAL '1 hour'
                      AND (message LIKE '%insufficient_quota%'
                           OR message LIKE '%rate_limit%'
                           OR message LIKE '%quota%'
                           OR message LIKE '%credit%')
                """
                api_error_df = fetch_data(api_credit_error_query)
                api_errors = int(api_error_df.iloc[0, 0]) if not api_error_df.empty else 0

                if api_errors > 0:
                    st.error(f"Claude API Credits Low/Exhausted!")
                    st.error(f"Check API credits at console.anthropic.com")
                else:
                    st.error(f"{analyzer_errors} errors in last hour")

        with col2:
            # Last analysis
            last_analysis = health['last_post_analyzed']
            if pd.notna(last_analysis):
                time_diff = datetime.now() - last_analysis.replace(tzinfo=None)
                minutes_ago = int(time_diff.total_seconds() / 60)
                st.metric("Last Analysis", f"{minutes_ago}m ago")
            else:
                st.metric("Last Analysis", "No data")

        with col3:
            # Warnings (24h)
            total_warnings = int(health['total_warnings_24h']) if pd.notna(health['total_warnings_24h']) else 0
            st.metric("Warnings (24h)", total_warnings, delta=None if total_warnings == 0 else f"{total_warnings} issues")

        with col4:
            # Errors (24h)
            total_errors = int(health['total_errors_24h']) if pd.notna(health['total_errors_24h']) else 0
            st.metric("Errors (24h)", total_errors, delta=None if total_errors == 0 else f"{total_errors} issues", delta_color="inverse")

    st.markdown("---")

    # ========================================================================
    # COLLECTOR STATISTICS
    # ========================================================================

    # Fetch collector statistics directly from database
    stats_query = """
        SELECT
            collector_name,
            last_run_started_at,
            last_run_completed_at,
            last_run_duration_seconds,
            total_posts_collected,
            total_posts_saved,
            last_run_posts_collected,
            last_run_posts_saved,
            total_errors,
            last_error_message,
            last_error_at
        FROM collector_statistics
        ORDER BY collector_name
    """

    stats_df = fetch_data(stats_query)

    if not stats_df.empty:
        # Convert DataFrame to list of dicts for error details
        collector_stats = stats_df.to_dict('records')

        # Format datetime columns
        datetime_cols = ['last_run_started_at', 'last_run_completed_at', 'last_error_at']
        for col in datetime_cols:
            if col in stats_df.columns:
                stats_df[col] = stats_df[col].apply(
                    lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(x) else 'Never'
                )

        # Format duration
        if 'last_run_duration_seconds' in stats_df.columns:
            stats_df['last_run_duration'] = stats_df['last_run_duration_seconds'].apply(
                lambda x: f"{x:.1f}s" if pd.notna(x) else 'N/A'
            )

        # Select and rename columns for display
        display_cols = {
            'collector_name': 'Collector',
            'last_run_completed_at': 'Last Run',
            'last_run_duration': 'Duration',
            'last_run_posts_collected': 'Posts Found',
            'last_run_posts_saved': 'New Posts',
            'total_posts_collected': 'Total Collected',
            'total_posts_saved': 'Total Saved',
            'total_errors': 'Errors'
        }

        # Select only existing columns
        available_cols = {k: v for k, v in display_cols.items() if k in stats_df.columns}
        display_df = stats_df[list(available_cols.keys())].rename(columns=available_cols)

        # Display as table with styling
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Collector": st.column_config.TextColumn("Collector", width="medium"),
                "Last Run": st.column_config.TextColumn("Last Run", width="medium"),
                "Duration": st.column_config.TextColumn("Duration", width="small"),
                "Posts Found": st.column_config.NumberColumn("Posts Found", width="small"),
                "New Posts": st.column_config.NumberColumn("New Posts", width="small"),
                "Total Collected": st.column_config.NumberColumn("Total Collected", width="medium"),
                "Total Saved": st.column_config.NumberColumn("Total Saved", width="medium"),
                "Errors": st.column_config.NumberColumn("Errors", width="small", help="Total errors since initialization")
            }
        )

        # Show error details in expander if any collector has errors
        collectors_with_errors = [s for s in collector_stats if s.get('total_errors', 0) > 0]
        if collectors_with_errors:
            with st.expander(f"⚠️ Error Details ({len(collectors_with_errors)} collectors with errors)"):
                for stats in collectors_with_errors:
                    st.markdown(f"**{stats['collector_name']}**: {stats.get('total_errors', 0)} errors")
                    if stats.get('last_error_message'):
                        st.text(f"Last error: {stats['last_error_message']}")
                    if stats.get('last_error_at'):
                        error_time = stats['last_error_at']
                        if isinstance(error_time, datetime):
                            st.text(f"At: {error_time.strftime('%Y-%m-%d %H:%M:%S')}")
                        st.markdown("---")
    else:
        st.info("No collector statistics available yet. Collectors will populate statistics after their first run.")

    st.markdown("---")

    # ========================================================================
    # ASSET METRICS
    # ========================================================================

    # Fetch asset metrics with recent alerts
    query = """
        SELECT
            c.id,
            c.name,
            c.ticker,
            dm.mention_count,
            dm.sentiment_avg,
            dm.hiring_mentions,
            dm.problem_mentions,
            dm.growth_mentions,
            (
                SELECT MAX(fetched_at)
                FROM social_posts
                WHERE asset_id = c.id
            ) as last_collection,
            (
                SELECT COUNT(*)
                FROM social_posts
                WHERE asset_id = c.id
            ) as total_posts,
            (
                SELECT COUNT(*)
                FROM alerts
                WHERE asset_id = c.id
                  AND DATE(timestamp) = CURRENT_DATE
                  AND alert_type = 'long_signal'
            ) as today_long_signals,
            (
                SELECT COUNT(*)
                FROM alerts
                WHERE asset_id = c.id
                  AND DATE(timestamp) = CURRENT_DATE
                  AND alert_type = 'short_signal'
            ) as today_short_signals,
            (
                SELECT COUNT(*)
                FROM alerts
                WHERE asset_id = c.id
                  AND timestamp >= NOW() - INTERVAL '24 hours'
            ) as alerts_24h
        FROM asset c
        LEFT JOIN LATERAL (
            SELECT *
            FROM daily_metrics
            WHERE asset_id = c.id
              AND date >= CURRENT_DATE - INTERVAL '7 days'
            ORDER BY date DESC
        ) dm ON true
        ORDER BY c.name
    """

    df = fetch_data(query)

    if not df.empty:
        # Aggregate metrics by company
        asset_metrics = df.groupby(['id', 'name', 'ticker']).agg({
            'mention_count': 'sum',
            'sentiment_avg': 'mean',
            'hiring_mentions': 'sum',
            'problem_mentions': 'sum',
            'growth_mentions': 'sum',
            'last_collection': 'first',
            'total_posts': 'first',
            'today_long_signals': 'first',
            'today_short_signals': 'first',
            'alerts_24h': 'first'
        }).reset_index()

        # Detailed table view

        # Prepare display dataframe
        display_df = asset_metrics.copy()

        # Calculate Daily Signal Strength (long signals - short signals)
        display_df['daily_signal_strength'] = (
            display_df['today_long_signals'].fillna(0).astype(int) -
            display_df['today_short_signals'].fillna(0).astype(int)
        )

        # Sort by absolute value of Daily Signal Strength descending (highest magnitude first)
        display_df['abs_signal_strength'] = display_df['daily_signal_strength'].abs()
        display_df = display_df.sort_values('abs_signal_strength', ascending=False)

        # Format columns
        display_df['DSS'] = display_df['daily_signal_strength'].astype(int)
        display_df['Asset'] = display_df['name'] + " (" + display_df['ticker'] + ")"
        display_df['Sentiment'] = display_df['sentiment_avg'].apply(
            lambda x: f"{x:.2f}" if pd.notna(x) else "N/A"
        )
        display_df['Mentions'] = display_df['mention_count'].fillna(0).astype(int)
        display_df['Long'] = display_df['today_long_signals'].fillna(0).astype(int)
        display_df['Short'] = display_df['today_short_signals'].fillna(0).astype(int)
        display_df['Alerts (24h)'] = display_df['alerts_24h'].fillna(0).astype(int)

        # Create a mapping of signal strength for each row index
        signal_strength_map = display_df['daily_signal_strength'].to_dict()

        # Create final display dataframe with only visible columns (no internal column)
        final_df = display_df[['DSS', 'Asset', 'Mentions', 'Sentiment', 'Long', 'Short', 'Alerts (24h)']].copy()

        # Apply row-wise text color styling using the mapping
        def style_rows(row):
            """Style rows based on signal strength from mapping"""
            # Get signal strength from the mapping using row index
            signal_strength = signal_strength_map.get(row.name, 0)

            if signal_strength > 0:
                color = 'color: #00AA00; font-weight: bold'  # Green text for positive
            elif signal_strength < 0:
                color = 'color: #DD0000; font-weight: bold'  # Red text for negative
            else:
                color = ''  # No color for neutral

            # Return style for all columns
            return [color] * len(row)

        # Display table with clickable asset names

        # Display header row
        col1, col2, col3, col4, col5, col6, col7 = st.columns([1, 3, 1, 1, 1, 1, 1])
        with col1:
            st.markdown("**DSS**")
        with col2:
            st.markdown("**Asset**")
        with col3:
            st.markdown("**Mentions**")
        with col4:
            st.markdown("**Sentiment**")
        with col5:
            st.markdown("**Long**")
        with col6:
            st.markdown("**Short**")
        with col7:
            st.markdown("**Alerts (24h)**")

        st.markdown("---")

        # Create a container for the table with clickable rows
        for idx, row in final_df.iterrows():
            col1, col2, col3, col4, col5, col6, col7 = st.columns([1, 3, 1, 1, 1, 1, 1])

            # Get signal strength for coloring
            signal_strength = signal_strength_map.get(idx, 0)
            if signal_strength > 0:
                color = '#00AA00'  # Green for positive
            elif signal_strength < 0:
                color = '#DD0000'  # Red for negative
            else:
                color = '#FFFFFF'  # White for neutral

            with col1:
                st.markdown(f"<span style='color: {color}; font-weight: bold;'>{row['DSS']}</span>", unsafe_allow_html=True)
            with col2:
                # Extract asset name without ticker for button and session state
                asset_full = row['Asset']
                asset_name = asset_full.split(' (')[0]
                if st.button(asset_full, key=f"asset_{idx}", use_container_width=True):
                    # Set selected asset and switch to Asset Detail page
                    st.session_state.selected_asset = asset_name
                    st.session_state.page = "Asset Detail"
                    st.rerun()
            with col3:
                st.markdown(f"<span style='color: {color};'>{row['Mentions']}</span>", unsafe_allow_html=True)
            with col4:
                st.markdown(f"<span style='color: {color};'>{row['Sentiment']}</span>", unsafe_allow_html=True)
            with col5:
                st.markdown(f"<span style='color: {color};'>{row['Long']}</span>", unsafe_allow_html=True)
            with col6:
                st.markdown(f"<span style='color: {color};'>{row['Short']}</span>", unsafe_allow_html=True)
            with col7:
                st.markdown(f"<span style='color: {color};'>{row['Alerts (24h)']}</span>", unsafe_allow_html=True)
    else:
        st.info("No data available yet. The collector service is gathering data.")
