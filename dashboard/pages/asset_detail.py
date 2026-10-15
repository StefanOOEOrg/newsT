"""
Asset Detail Page - Detailed view of individual asset with charts and posts.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

from services.database import fetch_data
from services.stock_data import fetch_stock_data
from services.formatting import get_sentiment_emoji
from components.charts import create_multi_overlay_chart


def render():
    """Render the Asset Detail page."""
    # Fetch assets
    assets_df = fetch_data("SELECT id, name, ticker FROM asset ORDER BY name")

    if assets_df.empty:
        st.warning("No assets found.")
    else:
        # Initialize session state for selected asset if not exists
        if 'selected_asset' not in st.session_state:
            st.session_state.selected_asset = assets_df['name'].tolist()[0]

        # Track previous company to detect changes
        if 'previous_asset' not in st.session_state:
            st.session_state.previous_asset = st.session_state.selected_asset

        # Compact layout: Asset selector + Metric toggles in one row
        asset_names = assets_df['name'].tolist()
        # Find index of previously selected asset (or use first if not found)
        try:
            default_asset_index = asset_names.index(st.session_state.selected_asset)
        except ValueError:
            default_asset_index = 0
            st.session_state.selected_asset = asset_names[0]

        # Create compact row with asset selector and toggles
        col_asset, col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1, 1])

        with col_asset:
            selected_asset = st.selectbox(
                "Asset",
                options=asset_names,
                index=default_asset_index,
                format_func=lambda x: f"{x} ({assets_df[assets_df['name']==x]['ticker'].values[0]})",
                key="asset_selector",
                label_visibility="collapsed"
            )

        with col1:
            show_volume = st.checkbox("Volume", value=False, key="toggle_volume")
        with col2:
            show_sentiment = st.checkbox("Sentiment", value=False, key="toggle_sentiment")
        with col3:
            show_mentions = st.checkbox("Mentions", value=False, key="toggle_mentions")
        with col4:
            show_alerts = st.checkbox("Alert Signals", value=True, key="toggle_alerts")
        with col5:
            show_signal_strength = st.checkbox("Signal Strength", value=True, key="toggle_signal_strength")

        # Update session state when company changes
        if selected_asset != st.session_state.selected_asset:
            st.session_state.selected_asset = selected_asset
            st.session_state.previous_asset = selected_asset

        asset_id = int(assets_df[assets_df['name'] == selected_asset]['id'].values[0])

        # Fixed time range - user can adjust via chart's range selector
        days = 90  # Load last 90 days by default

        # Calculate common date range for all charts to ensure synchronized x-axis
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Fetch data for multi-overlay chart
        ticker = assets_df[assets_df['name'] == selected_asset]['ticker'].values[0]
        stock_data = fetch_stock_data(ticker, days)

        # Fetch metrics
        metrics_query = """
            SELECT date, mention_count, sentiment_avg
            FROM daily_metrics
            WHERE asset_id = %s
              AND date >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY date
        """
        metrics_df = fetch_data(metrics_query, (asset_id, days))

        # Convert date column and calculate moving average
        if not metrics_df.empty:
            metrics_df['date'] = pd.to_datetime(metrics_df['date'])
            metrics_df['sentiment_ma7'] = metrics_df['sentiment_avg'].rolling(window=7, min_periods=1).mean()

        # Fetch alerts
        alerts_query = """
            SELECT
                timestamp as alert_timestamp,
                alert_type,
                confidence_score,
                description
            FROM alerts
            WHERE asset_id = %s
              AND timestamp >= CURRENT_DATE - INTERVAL '%s days'
              AND alert_type IN ('long_signal', 'short_signal')
            ORDER BY timestamp
        """
        alerts_df = fetch_data(alerts_query, (asset_id, days))

        # Create and display multi-overlay chart
        multi_fig = create_multi_overlay_chart(
            stock_data=stock_data,
            metrics_df=metrics_df,
            alerts_df=alerts_df,
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            show_volume=show_volume,
            show_sentiment=show_sentiment,
            show_mentions=show_mentions,
            show_alerts=show_alerts,
            show_signal_strength=show_signal_strength
        )

        st.plotly_chart(multi_fig, use_container_width=True)

        # Stock price data availability info (only shown if data fetch failed)
        if stock_data is None or stock_data.empty:
            st.info(f"Stock price data not available for ticker '{ticker}'. This is optional - news analysis continues normally.")

        # Alert signals chart - positioned after volume chart
        alerts_query = """
            SELECT
                timestamp as alert_timestamp,
                alert_type,
                confidence_score,
                description
            FROM alerts
            WHERE asset_id = %s
              AND timestamp >= CURRENT_DATE - INTERVAL '%s days'
              AND alert_type IN ('long_signal', 'short_signal')
            ORDER BY timestamp
        """
        alerts_df = fetch_data(alerts_query, (asset_id, days))

        # Fetch metrics based on selected time range
        metrics_query = """
            SELECT date, mention_count, sentiment_avg
            FROM daily_metrics
            WHERE asset_id = %s
              AND date >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY date
        """
        metrics_df = fetch_data(metrics_query, (asset_id, days))

        # Convert date column to datetime for proper plotting
        if not metrics_df.empty:
            metrics_df['date'] = pd.to_datetime(metrics_df['date'])

            # Calculate 7-day moving average for sentiment
            metrics_df['sentiment_ma7'] = metrics_df['sentiment_avg'].rolling(window=7, min_periods=1).mean()

        # Category breakdown
        category_query = """
            SELECT aa.category, COUNT(*) as count
            FROM social_posts sp
            JOIN ai_analysis aa ON sp.id = aa.post_id
            WHERE sp.asset_id = %s
            GROUP BY aa.category
        """
        category_df = fetch_data(category_query, (asset_id,))

        if not category_df.empty:
            st.subheader("Category Breakdown")

            # Show pie chart
            fig_pie = px.pie(
                category_df,
                values='count',
                names='category',
                title='Post Categories'
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        # Recent posts with pagination
        active_filter = st.session_state.get(f'category_filter_{asset_id}')
        if active_filter:
            st.subheader(f"Recent Posts - {active_filter}")
        else:
            st.subheader("Recent Posts with Analysis")

        # Category filter buttons (directly above posts list)
        if not category_df.empty:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown("**Filter by category:**")
            with col2:
                if st.button("Reset Filter", key=f"reset_filter_{asset_id}"):
                    if f'category_filter_{asset_id}' in st.session_state:
                        del st.session_state[f'category_filter_{asset_id}']
                    st.rerun()

            # Create category buttons
            categories = category_df.to_dict('records')
            cols = st.columns(len(categories))
            for idx, (col, cat_data) in enumerate(zip(cols, categories)):
                with col:
                    category = cat_data['category']
                    count = cat_data['count']
                    is_active = st.session_state.get(f'category_filter_{asset_id}') == category
                    button_type = "primary" if is_active else "secondary"
                    if st.button(f"{category} ({count})", key=f"cat_{asset_id}_{category}", type=button_type):
                        st.session_state[f'category_filter_{asset_id}'] = category
                        st.session_state[f'posts_limit_{asset_id}'] = 20  # Reset pagination
                        st.rerun()

        # Initialize session state for pagination
        if f'posts_limit_{asset_id}' not in st.session_state:
            st.session_state[f'posts_limit_{asset_id}'] = 20

        # Build query with optional category filter
        where_clause = "WHERE sp.asset_id = %s"
        query_params = [asset_id]

        if active_filter:
            where_clause += " AND aa.category = %s"
            query_params.append(active_filter)

        # Get total count of posts
        count_query = f"""
            SELECT COUNT(*) as total
            FROM social_posts sp
            JOIN ai_analysis aa ON sp.id = aa.post_id
            {where_clause}
        """
        total_posts = fetch_data(count_query, tuple(query_params))['total'].values[0]

        # Fetch posts with current limit
        posts_query = f"""
            SELECT
                sp.title,
                sp.url,
                sp.created_at,
                aa.sentiment,
                aa.sentiment_score,
                aa.category,
                aa.summary
            FROM social_posts sp
            JOIN ai_analysis aa ON sp.id = aa.post_id
            {where_clause}
            ORDER BY sp.created_at DESC
            LIMIT %s
        """
        query_params.append(st.session_state[f'posts_limit_{asset_id}'])
        posts_df = fetch_data(posts_query, tuple(query_params))

        if not posts_df.empty:
            # Display posts
            for _, post in posts_df.iterrows():
                # Create header with title, score, and category
                col1, col2, col3 = st.columns([6, 1.5, 1.5])
                with col1:
                    # Use expander for the title
                    expander_label = f"{get_sentiment_emoji(post['sentiment'])} {post['title'][:80]}..."
                with col2:
                    # Show sentiment score on the right
                    st.markdown(f"<div style='text-align: right; padding-top: 10px;'><strong>{post['sentiment_score']:+.2f}</strong></div>", unsafe_allow_html=True)
                with col3:
                    # Show category badge on the right
                    category_colors = {
                        'Hiring': '#28a745',
                        'Growth': '#17a2b8',
                        'Problems': '#dc3545',
                        'Product': '#ffc107',
                        'Earnings': '#6f42c1',
                        'Other': '#6c757d'
                    }
                    color = category_colors.get(post['category'], '#6c757d')
                    st.markdown(f"<div style='text-align: right; padding-top: 10px;'><span style='background-color: {color}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 0.85em;'>{post['category']}</span></div>", unsafe_allow_html=True)

                # Expander for details
                with st.expander(expander_label):
                    st.markdown(f"**Summary:** {post['summary']}")
                    st.markdown(f"[View Original Post]({post['url']})")
                    st.caption(f"Posted: {post['created_at']}")

            # Show "Load More" button if there are more posts
            if len(posts_df) < total_posts:
                remaining = total_posts - len(posts_df)
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    if st.button(f"Load More ({remaining} remaining)", key=f"load_more_{asset_id}", use_container_width=True):
                        st.session_state[f'posts_limit_{asset_id}'] += 20
                        st.rerun()
            else:
                st.caption(f"Showing all {total_posts} posts")
        else:
            st.info("No analyzed posts yet.")
