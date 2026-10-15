"""
System Logs Page - View application logs from database.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add parent directory to path for database connection
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import get_db_connection

st.title("📋 System Logs")

# Filters
col1, col2, col3, col4 = st.columns(4)

with col1:
    log_level = st.selectbox(
        "Log Level",
        ["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        index=2  # Default to INFO
    )

with col2:
    service = st.selectbox(
        "Service",
        ["ALL", "collector", "analyzer", "dashboard"]
    )

with col3:
    time_range = st.selectbox(
        "Time Range",
        ["Last Hour", "Last 6 Hours", "Last 24 Hours", "Last 7 Days", "All Time"],
        index=2  # Default to Last 24 Hours
    )

with col4:
    limit = st.number_input("Max Records", min_value=10, max_value=1000, value=100, step=10)

# Clear Logs section
st.divider()
if st.button("🗑️ Clear All Logs", type="primary", help="Delete all logs from database"):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM system_logs")
            deleted_count = cur.rowcount
        conn.commit()
        st.success(f"✅ Successfully deleted {deleted_count} log entries")
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        if conn:
            conn.rollback()
        st.error(f"❌ Error clearing logs: {e}")
    finally:
        if conn:
            conn.close()

st.divider()

# Calculate time filter
time_filters = {
    "Last Hour": timedelta(hours=1),
    "Last 6 Hours": timedelta(hours=6),
    "Last 24 Hours": timedelta(days=1),
    "Last 7 Days": timedelta(days=7),
    "All Time": None
}
time_delta = time_filters[time_range]


@st.cache_data(ttl=10)  # Cache for 10 seconds
def get_logs(level_filter, service_filter, time_filter, max_records):
    """Fetch system logs from database."""
    conn = get_db_connection()
    try:
        query = """
            SELECT
                timestamp,
                level,
                service,
                logger,
                message,
                function,
                line_number,
                exception,
                metadata
            FROM system_logs
            WHERE 1=1
        """
        params = []

        # Level filter
        if level_filter != "ALL":
            query += " AND level = %s"
            params.append(level_filter)

        # Service filter
        if service_filter != "ALL":
            query += " AND service = %s"
            params.append(service_filter)

        # Time filter
        if time_filter:
            cutoff_time = datetime.now() - time_filter
            query += " AND timestamp >= %s"
            params.append(cutoff_time)

        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(max_records)

        df = pd.read_sql_query(query, conn, params=params)
        return df
    finally:
        conn.close()


# Fetch logs
try:
    df_logs = get_logs(log_level, service, time_delta, limit)

    if df_logs.empty:
        st.info("No logs found for the selected filters.")
    else:
        st.success(f"Found {len(df_logs)} log entries")

        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            error_count = len(df_logs[df_logs['level'] == 'ERROR'])
            st.metric("Errors", error_count)

        with col2:
            warning_count = len(df_logs[df_logs['level'] == 'WARNING'])
            st.metric("Warnings", warning_count)

        with col3:
            info_count = len(df_logs[df_logs['level'] == 'INFO'])
            st.metric("Info", info_count)

        with col4:
            services = df_logs['service'].nunique()
            st.metric("Services", services)

        # Search box
        search = st.text_input("🔍 Search in messages", "")

        if search:
            df_filtered = df_logs[df_logs['message'].str.contains(search, case=False, na=False)]
        else:
            df_filtered = df_logs

        st.write(f"Showing {len(df_filtered)} of {len(df_logs)} logs")

        # Display logs
        for idx, row in df_filtered.iterrows():
            # Color based on level
            level_colors = {
                'DEBUG': '🔵',
                'INFO': '🟢',
                'WARNING': '🟡',
                'ERROR': '🔴',
                'CRITICAL': '🔥'
            }
            icon = level_colors.get(row['level'], '⚪')

            with st.expander(
                f"{icon} {row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} | "
                f"{row['service']} | {row['level']} | {row['message'][:100]}..."
            ):
                col1, col2 = st.columns([1, 3])

                with col1:
                    st.markdown("**Timestamp:**")
                    st.markdown("**Level:**")
                    st.markdown("**Service:**")
                    st.markdown("**Logger:**")
                    if row['function']:
                        st.markdown("**Function:**")
                    if row['line_number']:
                        st.markdown("**Line:**")

                with col2:
                    st.markdown(row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'))
                    st.markdown(f"**{row['level']}**")
                    st.markdown(row['service'])
                    st.markdown(row['logger'])
                    if row['function']:
                        st.markdown(f"`{row['function']}()`")
                    if row['line_number']:
                        st.markdown(str(row['line_number']))

                st.markdown("**Message:**")
                st.code(row['message'])

                if row['exception']:
                    st.markdown("**Exception:**")
                    st.code(row['exception'], language='python')

                if row['metadata'] and row['metadata'] != {}:
                    st.markdown("**Metadata:**")
                    st.json(row['metadata'])

        # Auto-refresh option
        st.divider()
        auto_refresh = st.checkbox("Auto-refresh (10 seconds)")
        if auto_refresh:
            st.rerun()

except Exception as e:
    st.error(f"Error loading logs: {e}")

# Refresh button
if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()
