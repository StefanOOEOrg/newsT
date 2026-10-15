"""
Congressional Trades Collector
Fetches congressional trading data from public sources to identify potential trading signals.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests
from dotenv import load_dotenv
from .base import BaseCollector

load_dotenv()

logger = logging.getLogger(__name__)


class CongressionalTradesCollector(BaseCollector):
    """Collects congressional trading data from public APIs."""

    def __init__(self, database_url: str):
        """Initialize the congressional trades collector."""
        super().__init__(database_url)

        # Primary data source: House Stock Watcher (free, no API key needed)
        self.primary_url = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com"

        # Optional premium API support (Benzinga, FMP, etc.)
        self.api_key = os.getenv('CONGRESS_TRADES_API_KEY')  # For premium sources if configured
        self.premium_api_url = os.getenv('CONGRESS_TRADES_API_URL')  # Custom API endpoint

        logger.info("Congressional Trades Collector initialized")

    def fetch_recent_trades(self, days_back: int = 7) -> List[Dict]:
        """
        Fetch recent congressional trades.

        Args:
            days_back: Number of days to look back for trades

        Returns:
            List of trade dictionaries
        """
        try:
            # Try premium API first if configured
            if self.api_key and self.premium_api_url:
                trades = self._fetch_premium_api(days_back)
                if trades:
                    return trades

            # Use House Stock Watcher as primary/fallback source
            trades = self._fetch_house_stock_watcher()
            return trades

        except Exception as e:
            logger.error(f"Error fetching congressional trades: {e}")
            return []

    def _fetch_premium_api(self, days_back: int) -> List[Dict]:
        """
        Fetch trades from premium API (Benzinga, FMP, etc.).

        Args:
            days_back: Number of days to look back

        Returns:
            List of trade dictionaries
        """
        try:
            headers = {}
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'

            params = {
                'limit': 100,
                'days_back': days_back
            }

            response = requests.get(self.premium_api_url, headers=headers, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                trades = data.get('data', [])

                logger.info(f"Premium API: Fetched {len(trades)} trades")
                return self._normalize_premium_trades(trades)
            else:
                logger.warning(f"Premium API returned status {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Error fetching from premium API: {e}")
            return []

    def _fetch_house_stock_watcher(self) -> List[Dict]:
        """
        Fetch trades from House Stock Watcher (primary free source).

        Returns:
            List of trade dictionaries
        """
        try:
            # House Stock Watcher provides JSON files via S3
            url = f"{self.primary_url}/all_transactions.json"

            # Add user agent to avoid blocks
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; NewsTradingBot/1.0; +https://github.com/)'
            }

            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code == 200:
                trades = response.json()
                logger.info(f"House Stock Watcher: Fetched {len(trades)} trades")
                return self._normalize_house_stock_watcher_trades(trades)
            else:
                logger.warning(f"House Stock Watcher returned status {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Error fetching from House Stock Watcher: {e}")
            return []

    def _normalize_premium_trades(self, trades: List[Dict]) -> List[Dict]:
        """
        Normalize premium API data (Benzinga, FMP, etc.) to standard format.

        Args:
            trades: Raw trades from premium API

        Returns:
            Normalized trade dictionaries
        """
        normalized = []

        for trade in trades:
            try:
                # Generic normalization - adjust field names based on your API
                normalized.append({
                    'politician': trade.get('politician', trade.get('representative', 'Unknown')),
                    'ticker': trade.get('ticker', trade.get('symbol', '')).upper(),
                    'transaction_type': trade.get('type', trade.get('transaction_type', 'Unknown')),
                    'amount_range': trade.get('amount', trade.get('amount_range', 'Unknown')),
                    'transaction_date': trade.get('transaction_date', trade.get('date')),
                    'disclosure_date': trade.get('disclosure_date', trade.get('filed_date')),
                    'asset_description': trade.get('asset_description', trade.get('description', '')),
                    'party': trade.get('party', 'Unknown'),
                    'state': trade.get('state', trade.get('district', 'Unknown')),
                    'chamber': trade.get('chamber', 'Unknown'),
                    'source': 'premium_api'
                })
            except Exception as e:
                logger.error(f"Error normalizing premium API trade: {e}")
                continue

        return normalized

    def _normalize_house_stock_watcher_trades(self, trades: List[Dict]) -> List[Dict]:
        """
        Normalize House Stock Watcher data to standard format.

        Args:
            trades: Raw trades from House Stock Watcher

        Returns:
            Normalized trade dictionaries
        """
        normalized = []

        for trade in trades:
            try:
                # Extract ticker from asset description
                ticker = self._extract_ticker(trade.get('ticker', trade.get('asset_description', '')))

                if not ticker:
                    continue  # Skip trades without tickers

                normalized.append({
                    'politician': trade.get('representative', 'Unknown'),
                    'ticker': ticker.upper(),
                    'transaction_type': trade.get('type', 'Unknown'),
                    'amount_range': trade.get('amount', 'Unknown'),
                    'transaction_date': trade.get('transaction_date'),
                    'disclosure_date': trade.get('disclosure_date'),
                    'asset_description': trade.get('asset_description', ''),
                    'party': trade.get('party', 'Unknown'),
                    'state': trade.get('district', 'Unknown'),
                    'chamber': 'house',  # House Stock Watcher is House only
                    'source': 'house_stock_watcher'
                })
            except Exception as e:
                logger.error(f"Error normalizing House Stock Watcher trade: {e}")
                continue

        return normalized

    def _extract_ticker(self, text: str) -> Optional[str]:
        """
        Extract ticker symbol from asset description.

        Args:
            text: Asset description text

        Returns:
            Ticker symbol or None
        """
        if not text:
            return None

        # Common patterns: "AAPL", "Apple Inc (AAPL)", "AAPL - Apple Inc"
        import re

        # Try to find ticker in parentheses
        match = re.search(r'\(([A-Z]{1,5})\)', text)
        if match:
            return match.group(1)

        # Try to find standalone ticker
        match = re.search(r'\b([A-Z]{1,5})\b', text)
        if match:
            return match.group(1)

        return None

    def convert_to_social_posts(self, trades: List[Dict], asset_ticker_map: Dict[str, int]) -> List[Dict]:
        """
        Convert congressional trades to social_posts format.

        Args:
            trades: List of normalized trade dictionaries
            asset_ticker_map: Mapping of ticker symbols to asset_ids

        Returns:
            List of social_posts-compatible dictionaries
        """
        posts = []

        for trade in trades:
            ticker = trade['ticker']

            # Check if we're tracking this asset
            if ticker not in asset_ticker_map:
                continue

            asset_id = asset_ticker_map[ticker]

            # Determine transaction type emoji
            tx_emoji = "🟢" if "purchase" in trade['transaction_type'].lower() else "🔴"

            # Build title
            title = (
                f"{tx_emoji} {trade['politician']} ({trade['party']}-{trade['state']}) "
                f"{trade['transaction_type'].title()} ${ticker} - {trade['amount_range']}"
            )

            # Build content with full details
            content = f"""Congressional Trading Activity:

Politician: {trade['politician']}
Party: {trade['party']}
State/District: {trade['state']}
Chamber: {trade['chamber'].title()}

Ticker: ${ticker}
Transaction Type: {trade['transaction_type'].title()}
Amount Range: {trade['amount_range']}
Asset: {trade['asset_description']}

Transaction Date: {trade['transaction_date']}
Disclosure Date: {trade['disclosure_date']}

Source: {trade['source']}
"""

            # Create post_id (unique identifier)
            post_id = f"congress_{trade['politician']}_{ticker}_{trade['transaction_date']}_{trade['transaction_type']}"
            post_id = post_id.replace(' ', '_').lower()

            # Parse transaction date
            try:
                if trade['transaction_date']:
                    created_at = datetime.strptime(trade['transaction_date'], '%Y-%m-%d')
                else:
                    created_at = datetime.now()
            except Exception:
                created_at = datetime.now()

            # Build URL (link to source if available)
            url = f"https://www.capitoltrades.com/trades?politician={trade['politician'].replace(' ', '-')}"

            post = {
                'asset_id': asset_id,
                'source': 'congressional_trades',
                'post_id': post_id[:255],
                'author': f"{trade['politician']} ({trade['chamber'].title()})",
                'title': title[:500],
                'content': content[:5000],
                'url': url[:500],
                'score': 100,  # High importance score for congressional trades
                'created_at': created_at
            }

            posts.append(post)

        return posts

    def collect_for_asset(self, asset_id: int, asset_name: str, ticker: str, keywords: List[str]) -> List[Dict]:
        """
        Collect congressional trades for a specific asset.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Stock ticker symbol
            keywords: List of keywords (not used for congressional trades)

        Returns:
            List of post dictionaries
        """
        if not ticker:
            logger.warning(f"No ticker provided for {asset_name}, skipping")
            return []

        # Fetch all recent trades
        all_trades = self.fetch_recent_trades(days_back=7)

        # Filter for this specific ticker
        ticker_trades = [trade for trade in all_trades if trade['ticker'] == ticker.upper()]

        if not ticker_trades:
            logger.debug(f"No congressional trades found for {ticker}")
            return []

        # Convert to social_posts format
        asset_ticker_map = {ticker: asset_id}
        posts = self.convert_to_social_posts(ticker_trades, asset_ticker_map)

        return posts
