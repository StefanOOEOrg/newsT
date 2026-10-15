"""
System Logs Page - View system logs from all services.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from services.database import fetch_data


def render():
    """Render the System Logs page."""
    st.title("📋 System Logs")

    # Filters
    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])

    with col1:
        service_filter = st.selectbox(
            "Service",
            ["All", "collector", "analyzer", "dashboard", "notifier"],
            index=0
        )

    with col2:
        level_filter = st.selectbox(
            "Level",
            ["All", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            index=3  # Default to WARNING
        )

    with col3:
        time_range = st.selectbox(
            "Time Range",
            ["Last Hour", "Last 6 Hours", "Last 24 Hours", "Last 7 Days", "All"],
            index=2
        )

    with col4:
        # Add label placeholder to align button at bottom with selectboxes
        st.markdown('<div style="height: 1.5rem;"></div>', unsafe_allow_html=True)
        if st.button("🗑️ Clear Logs", type="secondary", use_container_width=True):
            # Import database connection
            from services.database import get_db_connection
            import psycopg2

            try:
                conn = get_db_connection()
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM system_logs")
                    deleted_count = cur.rowcount
                    conn.commit()
                conn.close()
                st.success(f"✅ Deleted {deleted_count} log entries")
                st.rerun()
            except Exception as e:
                st.error(f"Error clearing logs: {e}")

    # Build query with filters
    where_clauses = []
    params = []

    if service_filter != "All":
        where_clauses.append("service = %s")
        params.append(service_filter)

    # Level filter: show selected level and all higher severity levels
    # Hierarchy: DEBUG < INFO < WARNING < ERROR < CRITICAL
    if level_filter != "All":
        level_hierarchy = {
            "DEBUG": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            "INFO": ["INFO", "WARNING", "ERROR", "CRITICAL"],
            "WARNING": ["WARNING", "ERROR", "CRITICAL"],
            "ERROR": ["ERROR", "CRITICAL"],
            "CRITICAL": ["CRITICAL"]
        }
        levels_to_show = level_hierarchy.get(level_filter, [level_filter])
        placeholders = ", ".join(["%s"] * len(levels_to_show))
        where_clauses.append(f"level IN ({placeholders})")
        params.extend(levels_to_show)

    # Time range filter
    if time_range == "Last Hour":
        where_clauses.append("timestamp >= NOW() - INTERVAL '1 hour'")
    elif time_range == "Last 6 Hours":
        where_clauses.append("timestamp >= NOW() - INTERVAL '6 hours'")
    elif time_range == "Last 24 Hours":
        where_clauses.append("timestamp >= NOW() - INTERVAL '24 hours'")
    elif time_range == "Last 7 Days":
        where_clauses.append("timestamp >= NOW() - INTERVAL '7 days'")

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    # Fetch logs
    query = f"""
        SELECT
            timestamp,
            service,
            level,
            logger,
            message
        FROM system_logs
        {where_sql}
        ORDER BY timestamp DESC
        LIMIT 500
    """

    logs_df = fetch_data(query, tuple(params) if params else None)

    if not logs_df.empty:
        # Format timestamp
        logs_df['timestamp'] = pd.to_datetime(logs_df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')

        # Color coding for levels
        def get_level_color(level):
            colors = {
                'DEBUG': '🔵',
                'INFO': '🟢',
                'WARNING': '🟡',
                'ERROR': '🔴',
                'CRITICAL': '🔴'
            }
            return colors.get(level, '⚪')

        logs_df['level_icon'] = logs_df['level'].apply(get_level_color)
        logs_df['level_display'] = logs_df['level_icon'] + ' ' + logs_df['level']

        # Display statistics
        st.markdown("---")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Logs", len(logs_df))

        with col2:
            errors = len(logs_df[logs_df['level'] == 'ERROR'])
            st.metric("Errors", errors, delta=None if errors == 0 else f"{errors} errors", delta_color="inverse")

        with col3:
            warnings = len(logs_df[logs_df['level'] == 'WARNING'])
            st.metric("Warnings", warnings, delta=None if warnings == 0 else f"{warnings} warnings", delta_color="inverse")

        with col4:
            services = logs_df['service'].nunique()
            st.metric("Services", services)

        st.markdown("---")

        # Display logs table
        display_df = logs_df[['timestamp', 'service', 'level_display', 'logger', 'message']]
        display_df.columns = ['Timestamp', 'Service', 'Level', 'Logger', 'Message']

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            height=600,
            column_config={
                "Timestamp": st.column_config.TextColumn("Timestamp", width="small"),
                "Service": st.column_config.TextColumn("Service", width="small"),
                "Level": st.column_config.TextColumn("Level", width="small"),
                "Logger": st.column_config.TextColumn("Logger", width="small"),
                "Message": st.column_config.TextColumn("Message", width=None)  # None = auto-expand to fill remaining space
            }
        )

    else:
        st.info("No logs found for the selected filters.")
