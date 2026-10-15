"""
Events Page - View and analyze upcoming financial events.

Shows:
- Event calendar with timeline visualization
- Event details with news coverage leading up to event
- Sentiment trends pre/post event
- Alert history around events
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
from services.database import fetch_data

# Event type icons
EVENT_ICONS = {
    'earnings': '💰',
    'product_launch': '🚀',
    'conference': '🎤',
    'filing': '📄',
    'dividend': '💵',
    'other': '📅'
}

# Event type colors for visualization
EVENT_COLORS = {
    'earnings': '#FFD700',      # Gold
    'product_launch': '#FF6B6B', # Red
    'conference': '#4ECDC4',     # Teal
    'filing': '#95E1D3',         # Mint
    'dividend': '#45B7D1',       # Blue
    'other': '#CCCCCC'           # Gray
}


def render():
    """Render the Events page."""
    st.title("📅 Events Calendar")

    # Fetch all upcoming events
    events_query = """
        SELECT
            ae.id,
            ae.asset_id,
            ae.event_date,
            ae.event_type,
            ae.description,
            ae.metadata,
            a.name as asset_name,
            a.ticker
        FROM asset_events ae
        JOIN asset a ON ae.asset_id = a.id
        WHERE ae.event_date >= CURRENT_DATE - INTERVAL '30 days'
        ORDER BY ae.event_date ASC
    """

    events_df = fetch_data(events_query)

    if events_df.empty:
        st.info("No events found. Run `docker-compose exec collector python collect_events.py` to fetch events.")
        return

    # Format data
    events_df['event_date'] = pd.to_datetime(events_df['event_date'])

    # ========================================================================
    # EVENT TIMELINE VISUALIZATION
    # ========================================================================
    st.subheader("📊 Event Timeline")

    # Create timeline chart
    fig_timeline = go.Figure()

    # Group events by type for better visualization
    for event_type in events_df['event_type'].unique():
        type_events = events_df[events_df['event_type'] == event_type]

        fig_timeline.add_trace(go.Scatter(
            x=type_events['event_date'],
            y=[event_type] * len(type_events),
            mode='markers+text',
            name=event_type.replace('_', ' ').title(),
            marker=dict(
                size=15,
                color=EVENT_COLORS.get(event_type, '#CCCCCC'),
                line=dict(width=2, color='white')
            ),
            text=type_events['ticker'],
            textposition='top center',
            hovertemplate='<b>%{text}</b><br>%{x|%Y-%m-%d}<br><extra></extra>'
        ))

    fig_timeline.update_layout(
        height=300,
        xaxis_title="Date",
        yaxis_title="Event Type",
        hovermode='closest',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )

    st.plotly_chart(fig_timeline, use_container_width=True)

    # ========================================================================
    # CALENDAR VIEW
    # ========================================================================
    st.markdown("---")
    st.subheader("📆 Calendar View")

    # Filter options
    col1, col2 = st.columns([2, 1])

    with col1:
        time_filter = st.selectbox(
            "Time Range",
            ["Next 7 Days", "Next 30 Days", "Next 90 Days", "All Upcoming", "Past & Upcoming"]
        )

    with col2:
        type_filter = st.multiselect(
            "Event Types",
            options=events_df['event_type'].unique(),
            default=events_df['event_type'].unique()
        )

    # Apply filters
    filtered_df = events_df[events_df['event_type'].isin(type_filter)].copy()

    if time_filter == "Next 7 Days":
        cutoff = datetime.now() + timedelta(days=7)
        filtered_df = filtered_df[filtered_df['event_date'] <= cutoff]
    elif time_filter == "Next 30 Days":
        cutoff = datetime.now() + timedelta(days=30)
        filtered_df = filtered_df[filtered_df['event_date'] <= cutoff]
    elif time_filter == "Next 90 Days":
        cutoff = datetime.now() + timedelta(days=90)
        filtered_df = filtered_df[filtered_df['event_date'] <= cutoff]
    elif time_filter == "All Upcoming":
        filtered_df = filtered_df[filtered_df['event_date'] >= datetime.now()]

    # Display events grouped by date
    if not filtered_df.empty:
        # Group by date
        for date_str, date_events in filtered_df.groupby(filtered_df['event_date'].dt.date):
            # Date header
            days_until = (pd.Timestamp(date_str) - pd.Timestamp.now()).days

            if days_until < 0:
                time_indicator = f"({abs(days_until)} days ago)"
            elif days_until == 0:
                time_indicator = "(Today)"
            elif days_until == 1:
                time_indicator = "(Tomorrow)"
            else:
                time_indicator = f"(in {days_until} days)"

            st.markdown(f"### {date_str} {time_indicator}")

            # Display events for this date
            for _, event in date_events.iterrows():
                icon = EVENT_ICONS.get(event['event_type'], '📅')
                event_type_display = event['event_type'].replace('_', ' ').title()

                with st.expander(f"{icon} **{event['ticker']}** - {event['asset_name']} - {event_type_display}"):
                    col1, col2 = st.columns([2, 1])

                    with col1:
                        st.markdown(f"**Description:** {event['description']}")

                        # Show metadata
                        if pd.notna(event['metadata']) and event['metadata']:
                            import json
                            try:
                                metadata = json.loads(event['metadata']) if isinstance(event['metadata'], str) else event['metadata']
                                if metadata:
                                    st.markdown("**Details:**")
                                    for key, value in metadata.items():
                                        st.markdown(f"- {key.replace('_', ' ').title()}: {value}")
                            except:
                                pass

                    with col2:
                        # Quick stats button
                        if st.button("📊 View Analysis", key=f"view_{event['id']}"):
                            st.session_state.selected_event_id = event['id']
                            st.session_state.show_event_detail = True

            st.markdown("---")
    else:
        st.info("No events found for the selected filters.")

    # ========================================================================
    # EVENT DETAIL VIEW
    # ========================================================================
    if st.session_state.get('show_event_detail', False) and st.session_state.get('selected_event_id'):
        event_id = st.session_state.selected_event_id

        # Get event details
        event_detail = events_df[events_df['id'] == event_id].iloc[0]

        st.markdown("---")
        st.subheader(f"📈 Event Analysis: {event_detail['asset_name']} - {event_detail['event_type'].replace('_', ' ').title()}")

        # Calculate time windows
        event_date = pd.Timestamp(event_detail['event_date'])
        event_date_dt = event_date.to_pydatetime()  # Convert to Python datetime for Plotly
        pre_event_start = event_date - pd.Timedelta(days=14)  # 2 weeks before
        post_event_end = event_date + pd.Timedelta(days=7)    # 1 week after

        # ----------------------------------------------------------------
        # News Coverage Leading Up to Event
        # ----------------------------------------------------------------
        st.markdown("#### 📰 News Coverage")

        news_query = f"""
            SELECT
                sp.created_at,
                sp.title,
                sp.url,
                sp.source,
                aa.sentiment,
                aa.sentiment_score
            FROM social_posts sp
            LEFT JOIN ai_analysis aa ON sp.id = aa.post_id
            WHERE sp.asset_id = {event_detail['asset_id']}
              AND sp.created_at >= '{pre_event_start}'
              AND sp.created_at <= '{post_event_end}'
            ORDER BY sp.created_at DESC
            LIMIT 50
        """

        news_df = fetch_data(news_query)

        if not news_df.empty:
            news_df['created_at'] = pd.to_datetime(news_df['created_at'])

            # News volume chart
            news_df['date'] = news_df['created_at'].dt.date
            daily_counts = news_df.groupby('date').size().reset_index(name='count')

            fig_news_volume = go.Figure()
            fig_news_volume.add_trace(go.Bar(
                x=pd.to_datetime(daily_counts['date']),
                y=daily_counts['count'],
                name='Articles',
                marker_color='#4ECDC4'
            ))

            # Add event date line as a shape
            fig_news_volume.add_shape(
                type="line",
                x0=pd.Timestamp(event_date_dt),
                x1=pd.Timestamp(event_date_dt),
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="red", width=2, dash="dash")
            )

            # Add annotation for event date
            fig_news_volume.add_annotation(
                x=pd.Timestamp(event_date_dt),
                y=1,
                yref="paper",
                text="Event Date",
                showarrow=False,
                yanchor="bottom"
            )

            fig_news_volume.update_layout(
                title="News Volume Over Time",
                xaxis_title="Date",
                yaxis_title="Number of Articles",
                height=300
            )

            st.plotly_chart(fig_news_volume, use_container_width=True)

            # Recent articles
            with st.expander(f"📄 View Articles ({len(news_df)} total)"):
                for _, article in news_df.head(10).iterrows():
                    sentiment_emoji = "😊" if article['sentiment'] == 'positive' else "😐" if article['sentiment'] == 'neutral' else "😟"
                    st.markdown(f"{sentiment_emoji} **{article['title']}**")
                    st.caption(f"{article['created_at'].strftime('%Y-%m-%d %H:%M')} - {article['source']}")
                    if pd.notna(article['url']):
                        st.markdown(f"[Read more]({article['url']})")
                    st.markdown("---")
        else:
            st.info("No news articles found for this time period.")

        # ----------------------------------------------------------------
        # Sentiment Trends Pre/Post Event
        # ----------------------------------------------------------------
        st.markdown("#### 📊 Sentiment Trends")

        sentiment_query = f"""
            SELECT
                DATE(sp.created_at) as date,
                AVG(aa.sentiment_score) as avg_sentiment,
                COUNT(*) as article_count
            FROM social_posts sp
            JOIN ai_analysis aa ON sp.id = aa.post_id
            WHERE sp.asset_id = {event_detail['asset_id']}
              AND sp.created_at >= '{pre_event_start}'
              AND sp.created_at <= '{post_event_end}'
            GROUP BY DATE(sp.created_at)
            ORDER BY date
        """

        sentiment_df = fetch_data(sentiment_query)

        if not sentiment_df.empty:
            sentiment_df['date'] = pd.to_datetime(sentiment_df['date'])

            fig_sentiment = go.Figure()

            # Sentiment line
            fig_sentiment.add_trace(go.Scatter(
                x=sentiment_df['date'],
                y=sentiment_df['avg_sentiment'],
                mode='lines+markers',
                name='Avg Sentiment',
                line=dict(color='#45B7D1', width=3),
                marker=dict(size=8)
            ))

            # Add event date line as a shape
            fig_sentiment.add_shape(
                type="line",
                x0=pd.Timestamp(event_date_dt),
                x1=pd.Timestamp(event_date_dt),
                y0=-1,
                y1=1,
                line=dict(color="red", width=2, dash="dash")
            )

            # Add annotation for event date
            fig_sentiment.add_annotation(
                x=pd.Timestamp(event_date_dt),
                y=1,
                text="Event Date",
                showarrow=False,
                yanchor="bottom"
            )

            # Add neutral line
            fig_sentiment.add_hline(
                y=0,
                line_dash="dot",
                line_color="gray",
                annotation_text="Neutral"
            )

            fig_sentiment.update_layout(
                title="Sentiment Score Over Time",
                xaxis_title="Date",
                yaxis_title="Average Sentiment Score",
                height=350,
                yaxis=dict(range=[-1, 1])
            )

            st.plotly_chart(fig_sentiment, use_container_width=True)

            # Sentiment statistics
            col1, col2, col3 = st.columns(3)

            # Pre-event sentiment (7 days before)
            pre_event = sentiment_df[sentiment_df['date'] < event_date]
            if not pre_event.empty:
                pre_avg = pre_event['avg_sentiment'].mean()
                with col1:
                    st.metric("Pre-Event Sentiment (Avg)", f"{pre_avg:.2f}")

            # Event day sentiment (if available)
            event_day = sentiment_df[sentiment_df['date'] == event_date.date()]
            if not event_day.empty:
                event_avg = event_day['avg_sentiment'].iloc[0]
                with col2:
                    st.metric("Event Day Sentiment", f"{event_avg:.2f}")

            # Post-event sentiment (7 days after)
            post_event = sentiment_df[sentiment_df['date'] > event_date]
            if not post_event.empty:
                post_avg = post_event['avg_sentiment'].mean()
                delta = post_avg - pre_avg if not pre_event.empty else None
                with col3:
                    st.metric("Post-Event Sentiment (Avg)", f"{post_avg:.2f}",
                             delta=f"{delta:+.2f}" if delta is not None else None)

        else:
            st.info("No sentiment data available for this time period.")

        # ----------------------------------------------------------------
        # Alert History Around Event
        # ----------------------------------------------------------------
        st.markdown("#### 🚨 Alerts Around Event")

        alerts_query = f"""
            SELECT
                a.timestamp,
                a.alert_type,
                a.severity,
                a.description,
                a.confidence_score
            FROM alerts a
            WHERE a.asset_id = {event_detail['asset_id']}
              AND a.timestamp >= '{pre_event_start}'
              AND a.timestamp <= '{post_event_end}'
            ORDER BY a.timestamp DESC
        """

        alerts_df = fetch_data(alerts_query)

        if not alerts_df.empty:
            alerts_df['timestamp'] = pd.to_datetime(alerts_df['timestamp'])

            # Alert timeline
            for _, alert in alerts_df.iterrows():
                severity_emoji = "🔴" if alert['severity'] == 'high' else "🟡" if alert['severity'] == 'medium' else "🟢"
                days_diff = (pd.Timestamp(alert['timestamp']) - event_date).days

                if days_diff < 0:
                    timing = f"{abs(days_diff)} days before event"
                elif days_diff == 0:
                    timing = "Event day"
                else:
                    timing = f"{days_diff} days after event"

                st.markdown(f"{severity_emoji} **{alert['alert_type'].replace('_', ' ').title()}** ({timing})")
                st.caption(f"{alert['timestamp'].strftime('%Y-%m-%d %H:%M')} - Confidence: {alert['confidence_score']:.2%}")
                st.markdown(f"> {alert['description']}")
                st.markdown("---")
        else:
            st.info("No alerts found for this time period.")

        # Close button
        if st.button("✖ Close Analysis"):
            st.session_state.show_event_detail = False
            st.rerun()


# Initialize session state
if 'show_event_detail' not in st.session_state:
    st.session_state.show_event_detail = False
if 'selected_event_id' not in st.session_state:
    st.session_state.selected_event_id = None
