"""
Settings Page - Configure assets, notifications, and system settings.
"""
import os
import sys
import traceback
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd

from services.database import get_db_connection, fetch_data

# Environment variables
DATABASE_URL = os.getenv('DATABASE_URL')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')


def render():
    """Render the Settings page."""
    # System status
    st.subheader("System Status")

    # Check database stats
    stats_query = """
        SELECT
            (SELECT COUNT(*) FROM asset) as asset_count,
            (SELECT COUNT(*) FROM social_posts) as post_count,
            (SELECT COUNT(*) FROM ai_analysis) as analyzed_count,
            (SELECT COUNT(*) FROM alerts) as alert_count
    """
    stats_df = fetch_data(stats_query)

    if not stats_df.empty:
        stats = stats_df.iloc[0]
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Assets", stats['asset_count'])
        with col2:
            st.metric("Posts Collected", stats['post_count'])
        with col3:
            st.metric("Posts Analyzed", stats['analyzed_count'])
        with col4:
            st.metric("Alerts Generated", stats['alert_count'])

    # API Usage Stats
    st.markdown("---")
    st.subheader("API Usage & Rate Limits")

    # Fetch API usage statistics
    api_usage_query = """
        SELECT
            rlc.collector_name,
            COALESCE(aus.calls_today, 0) as calls_today,
            COALESCE(aus.calls_last_hour, 0) as calls_last_hour,
            COALESCE(aus.calls_last_minute, 0) as calls_last_minute,
            COALESCE(aus.errors_today, 0) as errors_today,
            aus.last_call_time,
            rlc.max_calls_per_day,
            rlc.max_calls_per_hour,
            rlc.max_calls_per_minute,
            rlc.min_interval_seconds,
            rlc.enabled,
            rlc.notes
        FROM rate_limit_config rlc
        LEFT JOIN api_usage_stats aus ON rlc.collector_name = aus.collector_name
        ORDER BY rlc.collector_name
    """
    api_usage_df = fetch_data(api_usage_query)

    if not api_usage_df.empty:
        st.markdown("""
        Track API usage across all collectors to prevent exceeding free tier quotas.
        The system automatically enforces rate limits to avoid service disruptions.
        """)

        for _, collector in api_usage_df.iterrows():
            collector_name = collector['collector_name']
            calls_today = int(collector['calls_today'])
            calls_hour = int(collector['calls_last_hour'])
            calls_minute = int(collector['calls_last_minute'])
            errors_today = int(collector['errors_today'])
            last_call = collector['last_call_time']
            enabled = collector['enabled']

            # Determine display name
            display_name = collector_name.replace('Collector', '')

            # Status badge
            if not enabled:
                status = "🔴 Disabled"
            elif errors_today > 5:
                status = "⚠️ Errors"
            else:
                status = "🟢 Active"

            with st.expander(f"{display_name} - {status}"):
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    st.metric("Calls Today", calls_today)
                with col2:
                    st.metric("Last Hour", calls_hour)
                with col3:
                    st.metric("Last Minute", calls_minute)
                with col4:
                    st.metric("Errors Today", errors_today)

                st.markdown("---")
                st.markdown("**Rate Limits:**")

                limit_col1, limit_col2 = st.columns(2)

                with limit_col1:
                    # Daily limit
                    max_day = collector['max_calls_per_day']
                    if max_day:
                        pct_day = (calls_today / max_day) * 100 if max_day > 0 else 0
                        st.markdown(f"**Daily:** {calls_today} / {max_day} ({pct_day:.0f}%)")
                        st.progress(min(pct_day / 100, 1.0))
                    else:
                        st.markdown("**Daily:** No limit")

                    # Hourly limit
                    max_hour = collector['max_calls_per_hour']
                    if max_hour:
                        pct_hour = (calls_hour / max_hour) * 100 if max_hour > 0 else 0
                        st.markdown(f"**Hourly:** {calls_hour} / {max_hour} ({pct_hour:.0f}%)")
                        st.progress(min(pct_hour / 100, 1.0))
                    else:
                        st.markdown("**Hourly:** No limit")

                with limit_col2:
                    # Per-minute limit
                    max_minute = collector['max_calls_per_minute']
                    if max_minute:
                        pct_minute = (calls_minute / max_minute) * 100 if max_minute > 0 else 0
                        st.markdown(f"**Per Minute:** {calls_minute} / {max_minute} ({pct_minute:.0f}%)")
                        st.progress(min(pct_minute / 100, 1.0))
                    else:
                        st.markdown("**Per Minute:** No limit")

                    # Minimum interval
                    min_interval = collector['min_interval_seconds']
                    if min_interval:
                        st.markdown(f"**Min Interval:** {min_interval} seconds")
                    else:
                        st.markdown("**Min Interval:** None")

                # Last call timestamp
                if last_call:
                    st.caption(f"Last API call: {last_call}")

                # Notes
                if collector['notes']:
                    st.info(collector['notes'])

        st.markdown("---")
        st.markdown("**💡 Tips:**")
        st.markdown("""
        - Rate limits automatically prevent exceeding free tier quotas
        - Collectors are skipped when limits are hit, preventing service disruptions
        - See [RATE_LIMITING.md](https://github.com/yourusername/newsT/blob/main/docs/RATE_LIMITING.md) for optimization strategies
        - Adjust limits via SQL: `UPDATE rate_limit_config SET max_calls_per_day = X WHERE collector_name = 'YourCollector'`
        """)

    else:
        st.info("No API usage data available. Rate limiting tables may not be initialized.")

    # Display existing companies
    st.markdown("---")
    st.subheader("Existing Assets")

    assets_df = fetch_data("""
        SELECT id, name, ticker, search_keywords, created_at,
               initialization_status, initialization_days,
               initialization_started_at, initialization_completed_at
        FROM asset
        ORDER BY name
    """)

    if not assets_df.empty:
        for _, asset in assets_df.iterrows():
            # Status badge
            status = asset.get('initialization_status', 'completed')
            if status == 'pending':
                status_badge = "Pending"
                status_color = "orange"
            elif status == 'in_progress':
                status_badge = "In Progress"
                status_color = "blue"
            elif status == 'completed':
                status_badge = "Completed"
                status_color = "green"
            elif status == 'failed':
                status_badge = "Failed"
                status_color = "red"
            else:
                status_badge = "Unknown"
                status_color = "gray"

            with st.expander(f"{asset['name']} ({asset['ticker']}) - {status_badge}"):
                st.write(f"**Keywords:** {', '.join(asset['search_keywords'])}")
                st.caption(f"Added: {asset['created_at']}")

                # Edit Keywords
                st.markdown("---")
                st.markdown("**Edit Keywords**")

                with st.form(f"edit_keywords_form_{asset['id']}"):
                    current_keywords = '\n'.join(asset['search_keywords'])
                    new_keywords = st.text_area(
                        "Search Keywords (one per line)",
                        value=current_keywords,
                        height=100,
                        key=f"keywords_{asset['id']}",
                        help="Edit the keywords used to search for this asset in social media"
                    )

                    if st.form_submit_button("Update Keywords", type="primary"):
                        if not new_keywords.strip():
                            st.error("Keywords cannot be empty.")
                        else:
                            # Parse keywords
                            keyword_list = [k.strip() for k in new_keywords.split('\n') if k.strip()]

                            # Update in database
                            conn = get_db_connection()
                            try:
                                with conn.cursor() as cur:
                                    cur.execute("""
                                        UPDATE asset
                                        SET search_keywords = %s
                                        WHERE id = %s
                                    """, (keyword_list, int(asset['id'])))
                                    conn.commit()
                                    st.success(f"Keywords updated for '{asset['name']}'!")
                            except Exception as e:
                                conn.rollback()
                                st.error(f"Error updating keywords: {e}")
                            finally:
                                conn.close()

                # Initialization info
                if status != 'completed':
                    st.markdown(f"**Initialization Status:** {status_badge}")
                    if asset.get('initialization_days'):
                        st.write(f"Historical days: {asset['initialization_days']}")
                    if asset.get('initialization_started_at'):
                        st.write(f"Started: {asset['initialization_started_at']}")

                    # Retry button for failed initializations
                    if status == 'failed':
                        if st.button(f"Retry Initialization", key=f"retry_{asset['id']}"):
                            conn = get_db_connection()
                            try:
                                with conn.cursor() as cur:
                                    cur.execute("""
                                        UPDATE asset
                                        SET initialization_status = 'pending',
                                            initialization_started_at = NULL
                                        WHERE id = %s
                                    """, (int(asset['id']),))
                                    conn.commit()
                                    st.success("Asset marked for retry. Click 'Start Historical Data Collection' button above.")
                            except Exception as e:
                                conn.rollback()
                                st.error(f"Error: {e}")
                            finally:
                                conn.close()

                if asset.get('initialization_completed_at'):
                    st.caption(f"Initialization completed: {asset['initialization_completed_at']}")

                # Historical Data Collection for existing assets
                st.markdown("---")
                st.markdown("**Collect Historical Data**")

                col1, col2 = st.columns([2, 1])
                with col1:
                    hist_days = st.slider(
                        "Days to collect",
                        min_value=7,
                        max_value=60,
                        value=30,
                        key=f"hist_days_{asset['id']}",
                        help="Collectors will use their maximum supported range if requested days exceed their limits"
                    )
                with col2:
                    st.write("")  # Spacer
                    st.write("")  # Spacer
                    if st.button("Collect", key=f"collect_hist_{asset['id']}", type="primary"):
                        with st.spinner(f"Collecting {hist_days} days of historical data for {asset['name']}..."):
                            try:
                                # Import collector modules
                                from collector_factory import get_factory
                                import logging

                                # Get factory and collectors
                                factory = get_factory()
                                factory.auto_discover()

                                available_names = factory.list_available()

                                collectors_to_use = []
                                collector_errors = []

                                if 'newsapi' in available_names:
                                    collector = factory.create('newsapi', DATABASE_URL)
                                    if collector:
                                        collectors_to_use.append(collector)
                                    else:
                                        collector_errors.append("NewsAPI: Failed to initialize (check NEWSAPI_KEY in .env)")

                                if not collectors_to_use:
                                    st.error("No collectors available for historical data collection")
                                    if collector_errors:
                                        st.warning("**Configuration issues:**")
                                        for error in collector_errors:
                                            st.write(f"- {error}")
                                    st.info("To enable NewsAPI collector:\n"
                                          "1. Get a free API key from https://newsapi.org/register\n"
                                          "2. Add `NEWSAPI_KEY=your_key_here` to the `.env` file\n"
                                          "3. Restart the dashboard container: `docker-compose restart dashboard`")
                                else:
                                    # Mark asset as pending before starting
                                    conn = get_db_connection()
                                    try:
                                        with conn.cursor() as cur:
                                            cur.execute("""
                                                UPDATE asset
                                                SET initialization_status = 'in_progress',
                                                    initialization_days = %s,
                                                    initialization_started_at = NOW()
                                                WHERE id = %s
                                            """, (hist_days, int(asset['id'])))
                                            conn.commit()
                                    finally:
                                        conn.close()

                                    # Collect data
                                    total_saved = 0
                                    for collector in collectors_to_use:
                                        try:
                                            result = collector.initialize_asset(int(asset['id']), hist_days)
                                            total_saved += result['total_saved']
                                        except Exception as e:
                                            st.error(f"Error during collection: {e}")
                                            # Mark as failed
                                            conn = get_db_connection()
                                            try:
                                                with conn.cursor() as cur:
                                                    cur.execute("""
                                                        UPDATE asset
                                                        SET initialization_status = 'failed'
                                                        WHERE id = %s
                                                    """, (int(asset['id']),))
                                                    conn.commit()
                                            finally:
                                                conn.close()
                                            raise

                                    # Mark as completed
                                    conn = get_db_connection()
                                    try:
                                        with conn.cursor() as cur:
                                            cur.execute("""
                                                UPDATE asset
                                                SET initialization_status = 'completed',
                                                    initialization_completed_at = NOW()
                                                WHERE id = %s
                                            """, (int(asset['id']),))
                                            conn.commit()
                                    finally:
                                        conn.close()

                                    st.success(f"Collected {total_saved} new posts for {asset['name']}!")
                                    st.info("Refresh the page to see updated data")

                            except Exception as e:
                                st.error(f"Collection failed: {e}")
                                with st.expander("View Error Details"):
                                    st.code(traceback.format_exc())

                # Delete asset button
                st.markdown("---")
                col1, col2 = st.columns([3, 1])
                with col2:
                    if st.button("Delete", key=f"delete_{asset['id']}", type="secondary"):
                        # Confirmation using session state
                        st.session_state[f"confirm_delete_{asset['id']}"] = True

                # Show confirmation dialog
                if st.session_state.get(f"confirm_delete_{asset['id']}", False):
                    st.warning(f"Are you sure you want to delete **{asset['name']}**? This will also delete all related posts, analysis, metrics, and alerts.")
                    col1, col2, col3 = st.columns([1, 1, 2])

                    with col1:
                        if st.button("Yes, Delete", key=f"confirm_yes_{asset['id']}", type="primary"):
                            conn = get_db_connection()
                            try:
                                with conn.cursor() as cur:
                                    # Delete in correct order (dependencies first)
                                    # 1. Notification preferences
                                    cur.execute("DELETE FROM alert_notification_preferences WHERE asset_id = %s", (int(asset['id']),))

                                    # 2. AI analysis (references social_posts)
                                    cur.execute("DELETE FROM ai_analysis WHERE post_id IN (SELECT id FROM social_posts WHERE asset_id = %s)", (int(asset['id']),))

                                    # 3. Social posts
                                    cur.execute("DELETE FROM social_posts WHERE asset_id = %s", (int(asset['id']),))

                                    # 4. Daily metrics
                                    cur.execute("DELETE FROM daily_metrics WHERE asset_id = %s", (int(asset['id']),))

                                    # 5. Alerts (and their notification logs via CASCADE)
                                    cur.execute("DELETE FROM notification_log WHERE alert_id IN (SELECT id FROM alerts WHERE asset_id = %s)", (int(asset['id']),))
                                    cur.execute("DELETE FROM alerts WHERE asset_id = %s", (int(asset['id']),))

                                    # 6. Finally delete the asset
                                    cur.execute("DELETE FROM asset WHERE id = %s", (int(asset['id']),))

                                    conn.commit()
                                    st.success(f"Asset '{asset['name']}' deleted successfully!")
                                    st.info("Refresh the page to see updated list")
                                    # Clear confirmation state
                                    del st.session_state[f"confirm_delete_{asset['id']}"]
                            except Exception as e:
                                conn.rollback()
                                st.error(f"Error deleting asset: {e}")
                            finally:
                                conn.close()

                    with col2:
                        if st.button("Cancel", key=f"confirm_no_{asset['id']}"):
                            # Clear confirmation state
                            del st.session_state[f"confirm_delete_{asset['id']}"]
                            st.rerun()
    else:
        st.info("No assets configured yet.")

    st.markdown("---")
    st.subheader("Keyword Performance")
    st.markdown("""
    Track which keywords are finding posts and identify underperforming ones.
    Remove keywords that haven't found posts recently to keep your searches efficient.
    """)

    # Show keyword performance for existing assets
    if not assets_df.empty:
        with st.expander("View Keyword Performance", expanded=False):
            # Select asset for performance view
            asset_options = {row['name']: row['id'] for _, row in assets_df.iterrows()}
            selected_perf_asset_name = st.selectbox(
                "Select asset to view keyword performance",
                options=list(asset_options.keys()),
                key="keyword_perf_asset"
            )
            selected_perf_asset_id = asset_options[selected_perf_asset_name]

            # Import KeywordTracker
            shared_path = Path(__file__).parent / 'shared'
            if not shared_path.exists():
                shared_path = Path(__file__).parent.parent / 'shared'
            sys.path.insert(0, str(shared_path))

            from keyword_tracker import KeywordTracker
            keyword_tracker = KeywordTracker(database_url=DATABASE_URL)

            # Initialize tracking for this asset if not already done
            keyword_tracker.initialize_keyword_tracking(selected_perf_asset_id)

            # Get performance stats
            performance = keyword_tracker.get_keyword_performance(selected_perf_asset_id)
            summary = keyword_tracker.get_keyword_stats_summary(selected_perf_asset_id)

            if summary and summary['total_keywords'] > 0:
                # Show summary stats
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Keywords", summary['total_keywords'])
                with col2:
                    st.metric("Total Posts Found", summary['total_posts_found'] or 0)
                with col3:
                    st.metric("Avg Posts/Keyword", f"{summary['avg_posts_per_keyword']:.1f}" if summary['avg_posts_per_keyword'] else "0.0")
                with col4:
                    st.metric("Never Matched", summary['never_matched'] or 0)

                st.markdown("---")

                # Show performance table
                if performance:
                    perf_df = pd.DataFrame(performance)
                    perf_df['last_found_at'] = pd.to_datetime(perf_df['last_found_at'])
                    perf_df['days_since_last_hit'] = perf_df['days_since_last_hit'].fillna(perf_df['days_tracked'])

                    # Format for display
                    display_df = perf_df[['keyword', 'posts_found', 'days_since_last_hit', 'last_found_at']].copy()
                    display_df['last_found_at'] = display_df['last_found_at'].apply(
                        lambda x: x.strftime('%Y-%m-%d %H:%M') if pd.notna(x) else 'Never'
                    )
                    display_df['days_since_last_hit'] = display_df['days_since_last_hit'].apply(
                        lambda x: f"{int(x)} days" if pd.notna(x) else 'N/A'
                    )
                    display_df.columns = ['Keyword', 'Posts Found', 'Days Since Last Hit', 'Last Found']

                    st.dataframe(display_df, use_container_width=True, hide_index=True)

                    # Identify underperforming keywords
                    st.markdown("---")
                    st.markdown("#### Underperforming Keywords")

                    min_days_inactive = st.slider(
                        "Days inactive to consider underperforming",
                        min_value=7,
                        max_value=90,
                        value=30,
                        help="Keywords that haven't found posts in this many days"
                    )

                    underperforming = keyword_tracker.get_underperforming_keywords(
                        selected_perf_asset_id,
                        min_days_inactive=min_days_inactive,
                        min_posts_threshold=5
                    )

                    if underperforming:
                        st.warning(f"Found {len(underperforming)} underperforming keywords")

                        underperf_df = pd.DataFrame(underperforming)
                        underperf_df['days_since_last_hit'] = underperf_df['days_since_last_hit'].apply(
                            lambda x: f"{int(x)} days" if pd.notna(x) else 'Never'
                        )
                        display_underperf = underperf_df[['keyword', 'posts_found', 'days_since_last_hit']].copy()
                        display_underperf.columns = ['Keyword', 'Posts Found', 'Days Since Last Hit']

                        st.dataframe(display_underperf, use_container_width=True, hide_index=True)

                        # Auto-remove button
                        st.markdown("---")
                        if st.button(f"Remove All {len(underperforming)} Underperforming Keywords", type="primary"):
                            keywords_to_remove = [kw['keyword'] for kw in underperforming]
                            removed_count = keyword_tracker.remove_keywords_from_asset(
                                selected_perf_asset_id,
                                keywords_to_remove
                            )
                            if removed_count > 0:
                                st.success(f"Removed {removed_count} underperforming keywords from {selected_perf_asset_name}")
                                st.info("Refresh the page to see updated keywords")
                            else:
                                st.error("Failed to remove keywords")
                    else:
                        st.success("All keywords are performing well!")

                else:
                    st.info("No keyword performance data yet. Keywords will be tracked as posts are collected.")
            else:
                st.info("No keywords configured for this asset yet.")
    else:
        st.info("Add an asset first to view keyword performance.")

    st.markdown("---")
    st.subheader("Smart Keyword Suggestions")
    st.markdown("""
    Use AI to automatically discover new keywords based on collected posts.
    Claude will analyze your posts and suggest relevant terms you might be missing.
    """)

    # Show keyword suggestions for existing assets
    if not assets_df.empty:
        with st.expander("Get AI-Powered Keyword Suggestions", expanded=False):
            # Select asset for suggestions
            asset_options = {row['name']: row['id'] for _, row in assets_df.iterrows()}
            selected_asset_name = st.selectbox(
                "Select asset to get keyword suggestions",
                options=list(asset_options.keys()),
                key="keyword_suggest_asset"
            )

            max_suggestions = st.slider(
                "Number of keywords to suggest",
                min_value=5,
                max_value=20,
                value=10,
                help="Maximum number of keyword suggestions"
            )

            if st.button("Generate Keyword Suggestions", type="primary"):
                selected_asset_id = asset_options[selected_asset_name]

                with st.spinner(f"Analyzing posts for {selected_asset_name}..."):
                    try:
                        # Import and use KeywordSuggester
                        shared_path = Path(__file__).parent / 'shared'
                        if not shared_path.exists():
                            shared_path = Path(__file__).parent.parent / 'shared'
                        sys.path.insert(0, str(shared_path))

                        from keyword_suggester import KeywordSuggester

                        suggester = KeywordSuggester(
                            database_url=DATABASE_URL,
                            anthropic_api_key=ANTHROPIC_API_KEY
                        )

                        suggested_keywords = suggester.suggest_keywords(
                            selected_asset_id,
                            max_keywords=max_suggestions
                        )

                        if suggested_keywords:
                            st.success(f"Found {len(suggested_keywords)} keyword suggestions!")

                            # Display suggestions with add buttons
                            st.markdown("**Suggested Keywords:**")

                            # Store suggestions in session state for adding
                            if 'keyword_suggestions' not in st.session_state:
                                st.session_state.keyword_suggestions = {}
                            st.session_state.keyword_suggestions[selected_asset_id] = suggested_keywords

                            # Display in columns
                            cols_per_row = 3
                            for i in range(0, len(suggested_keywords), cols_per_row):
                                cols = st.columns(cols_per_row)
                                for j, keyword in enumerate(suggested_keywords[i:i+cols_per_row]):
                                    with cols[j]:
                                        # Create unique key for each button
                                        button_key = f"add_kw_{selected_asset_id}_{keyword.replace(' ', '_')}"
                                        if st.button(f"Add {keyword}", key=button_key, use_container_width=True):
                                            # Add keyword to asset
                                            conn = get_db_connection()
                                            try:
                                                with conn.cursor() as cur:
                                                    # Get current keywords
                                                    cur.execute("SELECT search_keywords FROM asset WHERE id = %s", (selected_asset_id,))
                                                    current_keywords = cur.fetchone()[0]

                                                    # Add new keyword if not already present
                                                    if keyword.lower() not in [kw.lower() for kw in current_keywords]:
                                                        current_keywords.append(keyword.lower())
                                                        cur.execute(
                                                            "UPDATE asset SET search_keywords = %s WHERE id = %s",
                                                            (current_keywords, selected_asset_id)
                                                        )
                                                        conn.commit()
                                                        st.success(f"Added '{keyword}' to {selected_asset_name}")
                                                        st.rerun()
                                                    else:
                                                        st.info(f"'{keyword}' already exists")
                                            except Exception as e:
                                                conn.rollback()
                                                st.error(f"Error adding keyword: {e}")
                                            finally:
                                                conn.close()

                            # Add all button
                            if st.button("Add All Suggestions", type="secondary"):
                                conn = get_db_connection()
                                try:
                                    with conn.cursor() as cur:
                                        # Get current keywords
                                        cur.execute("SELECT search_keywords FROM asset WHERE id = %s", (selected_asset_id,))
                                        current_keywords = cur.fetchone()[0]
                                        current_keywords_lower = [kw.lower() for kw in current_keywords]

                                        # Add all new keywords
                                        new_count = 0
                                        for keyword in suggested_keywords:
                                            if keyword.lower() not in current_keywords_lower:
                                                current_keywords.append(keyword.lower())
                                                new_count += 1

                                        if new_count > 0:
                                            cur.execute(
                                                "UPDATE asset SET search_keywords = %s WHERE id = %s",
                                                (current_keywords, selected_asset_id)
                                            )
                                            conn.commit()
                                            st.success(f"Added {new_count} new keywords to {selected_asset_name}")
                                            st.rerun()
                                        else:
                                            st.info("All suggested keywords already exist")
                                except Exception as e:
                                    conn.rollback()
                                    st.error(f"Error adding keywords: {e}")
                                finally:
                                    conn.close()

                        else:
                            st.warning("No new keyword suggestions found. The asset might need more posts, or all relevant keywords may already be configured.")

                    except Exception as e:
                        st.error(f"Error generating suggestions: {e}")
                        with st.expander("View Error Details"):
                            st.code(traceback.format_exc())
    else:
        st.info("Add an asset first to get keyword suggestions.")

    st.markdown("---")
    st.markdown("#### Add New Asset")
    with st.expander("Add New Asset to Track", expanded=False):
        st.markdown("""
        Add a new company or asset to monitor. The system will start collecting and analyzing news for this asset.
        """)

        with st.form("add_asset_form"):
            asset_name = st.text_input("Asset Name", placeholder="e.g., Tesla")
            ticker = st.text_input("Stock Ticker", placeholder="e.g., TSLA")
            keywords = st.text_area(
                "Search Keywords (one per line)",
                placeholder="tesla\ntsla\nelon musk"
            )

            st.markdown("**Historical Data Collection**")
            collect_historical = st.checkbox(
                "Collect historical data (recommended)",
                value=True,
                help="Automatically collect and analyze news from the past 30 days"
            )

            if collect_historical:
                historical_days = st.slider(
                    "Days of historical data",
                    min_value=7,
                    max_value=60,
                    value=30,
                    help="Collectors will use their maximum supported range if requested days exceed their limits"
                )
            else:
                historical_days = 0

            submitted = st.form_submit_button("Add Asset", type="primary")

            if submitted:
                if not asset_name or not ticker or not keywords:
                    st.error("All fields are required.")
                else:
                    # Parse keywords
                    keyword_list = [k.strip() for k in keywords.split('\n') if k.strip()]

                    # Insert into database
                    conn = get_db_connection()
                    try:
                        with conn.cursor() as cur:
                            if collect_historical:
                                # Add with pending initialization status
                                cur.execute("""
                                    INSERT INTO asset (name, ticker, search_keywords,
                                                         initialization_status, initialization_days)
                                    VALUES (%s, %s, %s, 'pending', %s)
                                """, (asset_name, ticker, keyword_list, historical_days))
                            else:
                                # Add as completed (no historical collection)
                                cur.execute("""
                                    INSERT INTO asset (name, ticker, search_keywords,
                                                         initialization_status)
                                    VALUES (%s, %s, %s, 'completed')
                                """, (asset_name, ticker, keyword_list))
                            conn.commit()

                            if collect_historical:
                                st.success(f"Asset '{asset_name}' added! Historical data collection will begin automatically.")
                                st.info(f"The system will collect news from the past {historical_days} days. Check the collector logs for progress.")
                            else:
                                st.success(f"Asset '{asset_name}' added successfully!")
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Error adding asset: {e}")
                    finally:
                        conn.close()

    st.markdown("---")

    # Notification Settings
    st.subheader("Notification Settings")

    st.markdown("""
    Configure how you want to be notified when high-confidence alerts are generated.
    Supported channels: Email, SMS, Push (Pushover), Webhook
    """)

    # Get all assets for notification preferences
    assets_for_notif = fetch_data("SELECT id, name, ticker FROM asset ORDER BY name")

    # Load existing notification settings from database
    existing_settings = fetch_data("SELECT * FROM notification_settings WHERE id = 1")
    current_email = existing_settings['notification_email'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings['notification_email'].iloc[0]) else ''
    current_phone = existing_settings['notification_phone'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings['notification_phone'].iloc[0]) else ''
    current_smtp_user = existing_settings['smtp_user'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings['smtp_user'].iloc[0]) else ''
    current_smtp_password = existing_settings['smtp_password'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings['smtp_password'].iloc[0]) else ''
    current_check_interval = int(existing_settings['check_interval'].iloc[0]) if not existing_settings.empty and pd.notna(existing_settings['check_interval'].iloc[0]) else 5

    # Load collection schedule settings
    current_smart_scheduling = bool(existing_settings['enable_smart_scheduling'].iloc[0]) if not existing_settings.empty and 'enable_smart_scheduling' in existing_settings.columns and pd.notna(existing_settings['enable_smart_scheduling'].iloc[0]) else True
    current_interval_market = int(existing_settings['collection_interval_market_hours'].iloc[0]) if not existing_settings.empty and 'collection_interval_market_hours' in existing_settings.columns and pd.notna(existing_settings['collection_interval_market_hours'].iloc[0]) else 15
    current_interval_after = int(existing_settings['collection_interval_after_hours'].iloc[0]) if not existing_settings.empty and 'collection_interval_after_hours' in existing_settings.columns and pd.notna(existing_settings['collection_interval_after_hours'].iloc[0]) else 30
    current_interval_weekend = int(existing_settings['collection_interval_weekends'].iloc[0]) if not existing_settings.empty and 'collection_interval_weekends' in existing_settings.columns and pd.notna(existing_settings['collection_interval_weekends'].iloc[0]) else 120
    current_interval_fixed = int(existing_settings['collection_interval_fixed'].iloc[0]) if not existing_settings.empty and 'collection_interval_fixed' in existing_settings.columns and pd.notna(existing_settings['collection_interval_fixed'].iloc[0]) else 30
    current_market_open_hour = int(existing_settings['market_open_hour'].iloc[0]) if not existing_settings.empty and 'market_open_hour' in existing_settings.columns and pd.notna(existing_settings['market_open_hour'].iloc[0]) else 9
    current_market_open_minute = int(existing_settings['market_open_minute'].iloc[0]) if not existing_settings.empty and 'market_open_minute' in existing_settings.columns and pd.notna(existing_settings['market_open_minute'].iloc[0]) else 30
    current_market_close_hour = int(existing_settings['market_close_hour'].iloc[0]) if not existing_settings.empty and 'market_close_hour' in existing_settings.columns and pd.notna(existing_settings['market_close_hour'].iloc[0]) else 16
    current_market_close_minute = int(existing_settings['market_close_minute'].iloc[0]) if not existing_settings.empty and 'market_close_minute' in existing_settings.columns and pd.notna(existing_settings['market_close_minute'].iloc[0]) else 0

    # Load existing alert preferences (get first asset's settings as default)
    existing_prefs = fetch_data("""
        SELECT alert_type, min_confidence, notification_channels, quiet_hours_start, quiet_hours_end, enabled
        FROM alert_notification_preferences
        ORDER BY id
        LIMIT 3
    """)

    # Parse existing preferences
    long_prefs = existing_prefs[existing_prefs['alert_type'] == 'long_signal'].iloc[0] if not existing_prefs.empty and 'long_signal' in existing_prefs['alert_type'].values else None
    short_prefs = existing_prefs[existing_prefs['alert_type'] == 'short_signal'].iloc[0] if not existing_prefs.empty and 'short_signal' in existing_prefs['alert_type'].values else None

    # Legacy support - migrate old preferences to new format
    if long_prefs is None:
        hiring_prefs = existing_prefs[existing_prefs['alert_type'] == 'hiring_signal'].iloc[0] if not existing_prefs.empty and 'hiring_signal' in existing_prefs['alert_type'].values else None
        long_prefs = hiring_prefs  # Use hiring_signal as fallback for long_signal

    if short_prefs is None:
        risk_prefs = existing_prefs[existing_prefs['alert_type'] == 'risk_detected'].iloc[0] if not existing_prefs.empty and 'risk_detected' in existing_prefs['alert_type'].values else None
        if risk_prefs is None:
            negative_prefs = existing_prefs[existing_prefs['alert_type'] == 'negative_sentiment'].iloc[0] if not existing_prefs.empty and 'negative_sentiment' in existing_prefs['alert_type'].values else None
            problem_prefs = existing_prefs[existing_prefs['alert_type'] == 'problem_detected'].iloc[0] if not existing_prefs.empty and 'problem_detected' in existing_prefs['alert_type'].values else None
            risk_prefs = negative_prefs if negative_prefs is not None else problem_prefs
        short_prefs = risk_prefs  # Use risk_detected as fallback for short_signal

    if not assets_for_notif.empty:
        with st.form("notification_settings_form"):
            # Check Interval (global setting outside expanders)
            check_interval = st.number_input(
                "Check Interval (minutes)",
                min_value=1,
                max_value=60,
                value=current_check_interval,
                help="How often to check for new alerts"
            )

            st.markdown("---")

            # Collection Schedule Settings
            st.markdown("#### Collection Schedule")
            with st.expander("Configure News Collection Frequency", expanded=False):
                st.markdown("""
                Control how often the collector fetches new posts from social media sources.
                Smart scheduling adjusts collection frequency based on market hours.
                """)

                enable_smart_scheduling = st.checkbox(
                    "Enable Smart Scheduling",
                    value=current_smart_scheduling,
                    help="Automatically adjust collection frequency based on market hours"
                )

                if enable_smart_scheduling:
                    st.markdown("**Market Hours** (US Eastern Time)")
                    col_mkt1, col_mkt2 = st.columns(2)
                    with col_mkt1:
                        market_open_hour = st.number_input(
                            "Market Open Hour (0-23)",
                            min_value=0,
                            max_value=23,
                            value=current_market_open_hour,
                            help="Hour when market opens (ET)"
                        )
                        market_open_minute = st.number_input(
                            "Market Open Minute (0-59)",
                            min_value=0,
                            max_value=59,
                            value=current_market_open_minute,
                            help="Minute when market opens"
                        )
                    with col_mkt2:
                        market_close_hour = st.number_input(
                            "Market Close Hour (0-23)",
                            min_value=0,
                            max_value=23,
                            value=current_market_close_hour,
                            help="Hour when market closes (ET)"
                        )
                        market_close_minute = st.number_input(
                            "Market Close Minute (0-59)",
                            min_value=0,
                            max_value=59,
                            value=current_market_close_minute,
                            help="Minute when market closes"
                        )

                    st.markdown("**Collection Intervals** (minutes)")
                    col_int1, col_int2, col_int3 = st.columns(3)
                    with col_int1:
                        interval_market_hours = st.number_input(
                            "During Market Hours",
                            min_value=5,
                            max_value=120,
                            value=current_interval_market,
                            help="Collection frequency during market hours"
                        )
                    with col_int2:
                        interval_after_hours = st.number_input(
                            "After Market Hours",
                            min_value=5,
                            max_value=240,
                            value=current_interval_after,
                            help="Collection frequency after market closes"
                        )
                    with col_int3:
                        interval_weekends = st.number_input(
                            "Weekends",
                            min_value=15,
                            max_value=480,
                            value=current_interval_weekend,
                            help="Collection frequency on weekends"
                        )
                else:
                    # Use fixed interval when smart scheduling disabled
                    interval_fixed = st.number_input(
                        "Fixed Collection Interval (minutes)",
                        min_value=5,
                        max_value=240,
                        value=current_interval_fixed,
                        help="Collection frequency (same at all times)"
                    )
                    # Set other values to defaults to satisfy database requirements
                    market_open_hour = current_market_open_hour
                    market_open_minute = current_market_open_minute
                    market_close_hour = current_market_close_hour
                    market_close_minute = current_market_close_minute
                    interval_market_hours = current_interval_market
                    interval_after_hours = current_interval_after
                    interval_weekends = current_interval_weekend

            st.markdown("---")

            # Email Settings
            st.markdown("#### Email Settings (SMTP)")
            with st.expander("Configure Email Notifications", expanded=False):
                col1, col2 = st.columns(2)

                with col1:
                    notification_email = st.text_input(
                        "Email Address",
                        value=current_email,
                        help="Email address to receive alerts"
                    )

                    smtp_user = st.text_input(
                        "SMTP Username (for sending email)",
                        value=current_smtp_user,
                        help="Your SMTP username (often your email address)"
                    )

                with col2:
                    smtp_password = st.text_input(
                        "SMTP Password",
                        value=current_smtp_password,
                        type="password",
                        help="Your SMTP password or app-specific password"
                    )

            # SMS/Twilio Settings
            st.markdown("#### SMS Settings (Twilio)")
            with st.expander("Configure SMS Notifications", expanded=False):
                col_sms1, col_sms2 = st.columns(2)

                # Load current Twilio settings
                current_twilio_sid = existing_settings['twilio_account_sid'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('twilio_account_sid', pd.Series([None])).iloc[0]) else ''
                current_twilio_token = existing_settings['twilio_auth_token'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('twilio_auth_token', pd.Series([None])).iloc[0]) else ''
                current_twilio_from = existing_settings['twilio_from_number'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('twilio_from_number', pd.Series([None])).iloc[0]) else ''

                with col_sms1:
                    notification_phone = st.text_input(
                        "Your Phone Number (To)",
                        value=current_phone,
                        help="Phone number to receive SMS (e.g., +1234567890)"
                    )

                    twilio_account_sid = st.text_input(
                        "Twilio Account SID",
                        value=current_twilio_sid,
                        help="Get from https://www.twilio.com/console"
                    )

                with col_sms2:
                    twilio_from_number = st.text_input(
                        "Twilio Phone Number (From)",
                        value=current_twilio_from,
                        help="Your Twilio phone number (e.g., +1987654321)"
                    )

                    twilio_auth_token = st.text_input(
                        "Twilio Auth Token",
                        value=current_twilio_token,
                        type="password",
                        help="Your Twilio auth token"
                    )

            # Push/Pushover Settings
            st.markdown("#### Push Notifications (Pushover)")
            with st.expander("Configure Push Notifications", expanded=False):
                col_push1, col_push2 = st.columns(2)

                # Load current Pushover settings
                current_pushover_token = existing_settings['pushover_token'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('pushover_token', pd.Series([None])).iloc[0]) else ''
                current_pushover_user = existing_settings['pushover_user'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('pushover_user', pd.Series([None])).iloc[0]) else ''

                with col_push1:
                    pushover_token = st.text_input(
                        "Pushover App Token",
                        value=current_pushover_token,
                        type="password",
                        help="Get from https://pushover.net/"
                    )

                with col_push2:
                    pushover_user = st.text_input(
                        "Pushover User Key",
                        value=current_pushover_user,
                        help="Your Pushover user/group key"
                    )

            # Webhook Settings
            st.markdown("#### Webhook Notifications")
            with st.expander("Configure Webhook", expanded=False):
                # Load current webhook settings
                current_webhook_url = existing_settings['webhook_url'].iloc[0] if not existing_settings.empty and pd.notna(existing_settings.get('webhook_url', pd.Series([None])).iloc[0]) else ''

                webhook_url = st.text_input(
                    "Webhook URL",
                    value=current_webhook_url,
                    help="Custom HTTP endpoint to receive alert notifications (POST requests with JSON payload)"
                )

            st.markdown("#### Alert Type Preferences")
            with st.expander("Configure Alert Types and Thresholds", expanded=False):
                st.markdown("""
                Configure which alert types to receive and set minimum confidence thresholds for each type.
                """)

                col_long, col_short = st.columns(2)

                with col_long:
                    st.markdown("**Long Signal (Bullish)**")
                    st.caption("Hiring, growth, earnings beats, positive indicators")
                    long_enabled = st.checkbox(
                        "Enable",
                        value=long_prefs['enabled'] if long_prefs is not None else True,
                        key="long_enabled"
                    )
                    long_confidence = st.slider(
                        "Min Confidence",
                        0.0, 1.0,
                        float(long_prefs['min_confidence']) if long_prefs is not None else 0.85,
                        0.05,
                        key="long_conf",
                        disabled=not long_enabled
                    )
                    long_channels = st.multiselect(
                        "Channels",
                        ['email', 'sms', 'push', 'webhook'],
                        default=long_prefs['notification_channels'] if long_prefs is not None else ['email'],
                        key="long_channels",
                        disabled=not long_enabled
                    )

                with col_short:
                    st.markdown("**Short Signal (Bearish)**")
                    st.caption("Problems, negative sentiment, downgrades (severity: weak/moderate/strong)")
                    short_enabled = st.checkbox(
                        "Enable",
                        value=short_prefs['enabled'] if short_prefs is not None else True,
                        key="short_enabled"
                    )
                    short_confidence = st.slider(
                        "Min Confidence",
                        0.0, 1.0,
                        float(short_prefs['min_confidence']) if short_prefs is not None else 0.80,
                        0.05,
                        key="short_conf",
                        disabled=not short_enabled
                    )
                    short_channels = st.multiselect(
                        "Channels",
                        ['email', 'sms', 'push', 'webhook'],
                        default=short_prefs['notification_channels'] if short_prefs is not None else ['email'],
                        key="short_channels",
                        disabled=not short_enabled
                    )

            # AI Analysis Prompt Configuration
            st.markdown("---")
            st.markdown("#### AI Analysis Prompt")
            with st.expander("Configure Claude AI Analysis Prompt", expanded=False):
                st.markdown("""
                Customize the prompt sent to Claude AI for analyzing social media posts.

                **Available placeholders:**
                - `{asset_name}`: Company name
                - `{ticker}`: Stock ticker symbol
                - `{text_to_analyze}`: The post title and content

                The prompt should instruct Claude to return JSON with: sentiment, sentiment_score, category, key_topics, and summary.
                """)

                # Load current prompt from database
                current_prompt_df = fetch_data("SELECT analysis_prompt FROM notification_settings WHERE id = 1")
                current_prompt = current_prompt_df['analysis_prompt'].iloc[0] if not current_prompt_df.empty and pd.notna(current_prompt_df['analysis_prompt'].iloc[0]) else """Analyze this social media post about {asset_name} ({ticker}) from a trading perspective.

{text_to_analyze}

Provide your analysis in JSON format with these fields:
- sentiment: one of "positive", "negative", or "neutral"
- sentiment_score: a number between -1.0 (very bearish/short signal) and 1.0 (very bullish/long signal)
- category: one of "Hiring", "Growth", "Problems", "Product", "Earnings", "Other"
- key_topics: array of 2-5 key topics or themes (as strings)
- summary: brief summary in 1-2 sentences (max 100 words)

Focus on identifying trading signals:
- BULLISH (long signals): hiring, partnerships, product launches, earnings beats, growth indicators, positive guidance
- BEARISH (short signals): problems, layoffs, negative sentiment, downgrades, missed earnings, legal issues

Return ONLY valid JSON, no other text."""

                analysis_prompt = st.text_area(
                    "Analysis Prompt Template",
                    value=current_prompt,
                    height=400,
                    help="The prompt template for Claude AI analysis. Use {asset_name}, {ticker}, and {text_to_analyze} as placeholders."
                )

                st.caption("Changes will take effect for new analyses after saving.")

            st.markdown("#### Quiet Hours")
            with st.expander("Configure Quiet Hours", expanded=False):
                st.markdown("""
                Set time periods when you don't want to receive notifications. Alerts will still be generated but not sent during quiet hours.
                """)

                quiet_col1, quiet_col2 = st.columns(2)

                # Get quiet hours from existing prefs (use first available)
                current_quiet_start = long_prefs['quiet_hours_start'] if long_prefs is not None else None
                current_quiet_end = long_prefs['quiet_hours_end'] if long_prefs is not None else None

                with quiet_col1:
                    quiet_start = st.time_input(
                        "Quiet Hours Start",
                        value=current_quiet_start if current_quiet_start else datetime.strptime("22:00", "%H:%M").time(),
                        help="Don't send notifications after this time"
                    )

                with quiet_col2:
                    quiet_end = st.time_input(
                        "Quiet Hours End",
                        value=current_quiet_end if current_quiet_end else datetime.strptime("07:00", "%H:%M").time(),
                        help="Resume notifications after this time"
                    )

            submit_notif = st.form_submit_button("Save All Settings", type="primary")

            if submit_notif:
                conn1 = None
                conn2 = None
                try:
                    # Update global notification settings in database
                    conn1 = get_db_connection()
                    with conn1.cursor() as cur:
                        # Update or insert notification settings
                        cur.execute("""
                            INSERT INTO notification_settings
                            (id, notification_email, notification_phone, smtp_host, smtp_port,
                             smtp_user, smtp_password, smtp_from,
                             twilio_account_sid, twilio_auth_token, twilio_from_number,
                             pushover_token, pushover_user, webhook_url,
                             check_interval, analysis_prompt,
                             enable_smart_scheduling, collection_interval_market_hours,
                             collection_interval_after_hours, collection_interval_weekends,
                             collection_interval_fixed, market_open_hour, market_open_minute,
                             market_close_hour, market_close_minute,
                             updated_at)
                            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (id) DO UPDATE SET
                                notification_email = EXCLUDED.notification_email,
                                notification_phone = EXCLUDED.notification_phone,
                                smtp_host = EXCLUDED.smtp_host,
                                smtp_port = EXCLUDED.smtp_port,
                                smtp_user = EXCLUDED.smtp_user,
                                smtp_password = EXCLUDED.smtp_password,
                                smtp_from = EXCLUDED.smtp_from,
                                twilio_account_sid = EXCLUDED.twilio_account_sid,
                                twilio_auth_token = EXCLUDED.twilio_auth_token,
                                twilio_from_number = EXCLUDED.twilio_from_number,
                                pushover_token = EXCLUDED.pushover_token,
                                pushover_user = EXCLUDED.pushover_user,
                                webhook_url = EXCLUDED.webhook_url,
                                check_interval = EXCLUDED.check_interval,
                                analysis_prompt = EXCLUDED.analysis_prompt,
                                enable_smart_scheduling = EXCLUDED.enable_smart_scheduling,
                                collection_interval_market_hours = EXCLUDED.collection_interval_market_hours,
                                collection_interval_after_hours = EXCLUDED.collection_interval_after_hours,
                                collection_interval_weekends = EXCLUDED.collection_interval_weekends,
                                collection_interval_fixed = EXCLUDED.collection_interval_fixed,
                                market_open_hour = EXCLUDED.market_open_hour,
                                market_open_minute = EXCLUDED.market_open_minute,
                                market_close_hour = EXCLUDED.market_close_hour,
                                market_close_minute = EXCLUDED.market_close_minute,
                                updated_at = NOW()
                        """, (notification_email, notification_phone,
                              'smtp.gmail.com', 587, smtp_user, smtp_password, smtp_user,
                              twilio_account_sid or None, twilio_auth_token or None, twilio_from_number or None,
                              pushover_token or None, pushover_user or None, webhook_url or None,
                              check_interval, analysis_prompt,
                              enable_smart_scheduling, interval_market_hours,
                              interval_after_hours, interval_weekends,
                              interval_fixed, market_open_hour, market_open_minute,
                              market_close_hour, market_close_minute))
                        conn1.commit()

                    # Update database preferences for all companies
                    conn2 = get_db_connection()
                    with conn2.cursor() as cur:
                        # Delete existing preferences
                        cur.execute("DELETE FROM alert_notification_preferences")

                        # Insert new preferences for each asset
                        for _, asset in assets_for_notif.iterrows():
                            asset_id = asset['id']

                            # Long signal (bullish)
                            if long_enabled:
                                cur.execute("""
                                    INSERT INTO alert_notification_preferences
                                    (asset_id, alert_type, min_confidence, notification_channels,
                                     quiet_hours_start, quiet_hours_end, enabled)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """, (asset_id, 'long_signal', long_confidence,
                                      long_channels, quiet_start, quiet_end, True))

                            # Short signal (bearish)
                            if short_enabled:
                                cur.execute("""
                                    INSERT INTO alert_notification_preferences
                                    (asset_id, alert_type, min_confidence, notification_channels,
                                     quiet_hours_start, quiet_hours_end, enabled)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """, (asset_id, 'short_signal', short_confidence,
                                      short_channels, quiet_start, quiet_end, True))

                        conn2.commit()

                    st.success("Notification settings saved! Changes will take effect within 60 seconds (no restart needed).")

                except Exception as e:
                    if conn1:
                        conn1.rollback()
                    if conn2:
                        conn2.rollback()
                    st.error(f"Error saving notification settings: {e}")
                    with st.expander("Error Details"):
                        st.code(traceback.format_exc())
                finally:
                    if conn1:
                        conn1.close()
                    if conn2:
                        conn2.close()
    else:
        st.info("Add assets first to configure notifications.")

    # ========================================================================
    # UPCOMING EVENTS CALENDAR
    # ========================================================================
    st.markdown("---")
    st.subheader("📅 Upcoming Events Calendar")

    # Fetch upcoming events
    events_query = """
        SELECT
            ae.id,
            ae.event_date,
            ae.event_type,
            ae.description,
            a.name as asset_name,
            a.ticker,
            ae.metadata
        FROM asset_events ae
        JOIN asset a ON ae.asset_id = a.id
        WHERE ae.event_date >= CURRENT_DATE
        ORDER BY ae.event_date ASC
        LIMIT 50
    """

    events_df = fetch_data(events_query)

    if not events_df.empty:
        # Format the data for display
        events_df['event_date'] = pd.to_datetime(events_df['event_date']).dt.strftime('%Y-%m-%d')

        # Get event type icons
        event_icons = {
            'earnings': '💰',
            'product_launch': '🚀',
            'conference': '🎤',
            'filing': '📄',
            'dividend': '💵',
            'other': '📅'
        }

        events_df['icon'] = events_df['event_type'].map(event_icons).fillna('📅')

        # Format event type for display
        events_df['type_display'] = events_df['icon'] + ' ' + events_df['event_type'].str.replace('_', ' ').str.title()

        # Display events in a card-like format
        for _, event in events_df.iterrows():
            with st.expander(f"**{event['event_date']}** - {event['asset_name']} ({event['ticker']}) - {event['type_display']}"):
                st.markdown(f"**Description:** {event['description']}")

                # Display metadata if available
                if pd.notna(event['metadata']) and event['metadata']:
                    import json
                    try:
                        metadata = json.loads(event['metadata']) if isinstance(event['metadata'], str) else event['metadata']
                        if metadata:
                            st.markdown("**Additional Details:**")
                            for key, value in metadata.items():
                                formatted_key = key.replace('_', ' ').title()
                                st.markdown(f"- {formatted_key}: {value}")
                    except:
                        pass

        st.info(f"💡 Tip: The system can automatically collect earnings calendar events using the event collector. Run `docker-compose exec collector python collect_events.py` to update.")
    else:
        st.info("No upcoming events found. Events can be collected using Alpha Vantage API or added manually to the database.")
        st.markdown("""
        **To add events automatically:**
        ```bash
        docker-compose exec collector python collect_events.py
        ```

        This will fetch earnings calendars from Alpha Vantage (25 calls/day free tier).
        """)
