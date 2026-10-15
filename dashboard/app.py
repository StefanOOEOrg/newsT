"""
News Trading Dashboard
Streamlit application for monitoring and analyzing trading signals.
"""
import os
import sys
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
import logging

# Version
__version__ = "1.2"

# Add shared directory to path
shared_path = Path(__file__).parent / 'shared'
if not shared_path.exists():
    shared_path = Path(__file__).parent.parent / 'shared'
sys.path.insert(0, str(shared_path))

# Add collector directory to path for direct initialization
collector_path = Path(__file__).parent / 'collector'
if not collector_path.exists():
    collector_path = Path(__file__).parent.parent / 'collector'
if collector_path.exists():
    sys.path.insert(0, str(collector_path))

from logging_config import setup_logging

# Load environment variables
load_dotenv()

# Import config
from config import CONSOLE_LOG_LEVEL, DATABASE_LOG_LEVEL, LOG_FORMAT

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# Set up logging (only once)
if 'logger_initialized' not in st.session_state:
    setup_logging(
        service_name='dashboard',
        database_url=DATABASE_URL,
        console_level=CONSOLE_LOG_LEVEL,
        database_level=DATABASE_LOG_LEVEL,
        log_format=LOG_FORMAT
    )
    st.session_state.logger_initialized = True

# Get module-level logger
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="News Trading Dashboard",
    page_icon="📊",
    layout="wide"
)

# Hide Streamlit's default page search/filter box
st.markdown("""
    <style>
        /* Hide the page search box in sidebar */
        [data-testid="stSidebarNav"] {
            display: none;
        }
    </style>
""", unsafe_allow_html=True)

# Import pages
from pages import overview, asset_detail, alerts, events, settings, system_logs, alert_performance

# Sidebar navigation
st.sidebar.title("📊 News Trading")

# Initialize page in session state if not exists
if 'page' not in st.session_state:
    st.session_state.page = "Overview"


def on_nav_change():
    """Callback handler for navigation changes."""
    st.session_state.page = st.session_state.nav_radio


# Radio button navigation
page = st.sidebar.radio(
    "Navigation",
    ["Overview", "Asset Detail", "Events", "Alerts", "Alert Performance", "System Logs", "Settings"],
    index=["Overview", "Asset Detail", "Events", "Alerts", "Alert Performance", "System Logs", "Settings"].index(st.session_state.page),
    key="nav_radio",
    on_change=on_nav_change
)

# Version info
st.sidebar.markdown("---")
st.sidebar.markdown(f"**Version:** {__version__}")

# Route to appropriate page
if page == "Overview":
    overview.render()
elif page == "Asset Detail":
    asset_detail.render()
elif page == "Events":
    events.render()
elif page == "Alerts":
    alerts.render()
elif page == "Alert Performance":
    alert_performance.render()
elif page == "System Logs":
    system_logs.render()
elif page == "Settings":
    settings.render()
