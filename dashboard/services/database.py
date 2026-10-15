"""Database service for dashboard."""
import os
import logging
import warnings
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st

# Suppress pandas warning about psycopg2 connections (non-SQLAlchemy connections)
# This warning is cosmetic - psycopg2 works fine with pandas for our use case
warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')


def get_db_connection():
    """
    Create a fresh database connection with error handling.

    Returns:
        Database connection object

    Raises:
        psycopg2.Error: If connection fails

    Note: Caller is responsible for closing the connection.
    """
    try:
        return psycopg2.connect(DATABASE_URL)
    except psycopg2.Error as e:
        logger.error(f"Database connection failed: {e}")
        raise


def fetch_data(query, params=None):
    """
    Execute a SELECT query and return results as a pandas DataFrame.

    Args:
        query: SQL query string
        params: Query parameters (optional)

    Returns:
        DataFrame with query results, empty DataFrame on error
    """
    conn = get_db_connection()
    try:
        df = pd.read_sql_query(query, conn, params=params)
        return df
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        st.error(f"Database error: {e}")
        return pd.DataFrame()
    finally:
        conn.close()
