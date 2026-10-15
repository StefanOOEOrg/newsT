"""
Alpha Vantage Earnings Calendar Collector

Collects earnings calendar data from Alpha Vantage API.
Free tier: 25 API calls/day
API Documentation: https://www.alphavantage.co/documentation/#earnings-calendar
"""
import os
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict
import requests
from .event_collector import EventCollector

logger = logging.getLogger(__name__)


class AlphaVantageEventsCollector(EventCollector):
    """
    Collects earnings calendar from Alpha Vantage API.

    Free tier limitations:
    - 25 API calls per day
    - Earnings calendar for the next 3-12 months
    """

    API_URL = "https://www.alphavantage.co/query"

    def __init__(self, database_url: str):
        """Initialize Alpha Vantage events collector."""
        super().__init__(database_url)

        self.api_key = os.getenv('ALPHAVANTAGE_API_KEY')
        if not self.api_key:
            logger.warning(
                "ALPHAVANTAGE_API_KEY not found in environment. "
                "Get one at https://www.alphavantage.co/support/#api-key"
            )

    def collect_events_for_asset(self, asset_id: int, asset_name: str, ticker: str) -> List[Dict]:
        """
        Collect earnings calendar for a specific asset.

        Args:
            asset_id: Database ID of the asset
            asset_name: Full asset name
            ticker: Stock ticker symbol

        Returns:
            List of event dictionaries
        """
        if not self.api_key:
            logger.warning(f"{self.name}: No API key configured, skipping {ticker}")
            return []

        events = []

        try:
            # Make API request
            params = {
                'function': 'EARNINGS_CALENDAR',
                'symbol': ticker,
                'apikey': self.api_key
            }

            logger.info(f"{self.name}: Fetching earnings calendar for {ticker}")
            response = requests.get(self.API_URL, params=params, timeout=10)

            if response.status_code == 429:
                logger.warning(f"{self.name}: Rate limit exceeded for {ticker}")
                return []
            elif response.status_code != 200:
                logger.error(f"{self.name}: HTTP {response.status_code} for {ticker}")
                return []

            # Alpha Vantage returns CSV format for earnings calendar
            # Parse the CSV response
            lines = response.text.strip().split('\n')

            if len(lines) < 2:
                logger.info(f"{self.name}: No earnings data for {ticker}")
                return []

            # Parse CSV header
            header = lines[0].split(',')

            # Expected columns: symbol, name, reportDate, fiscalDateEnding, estimate, currency
            for line in lines[1:]:
                try:
                    values = line.split(',')
                    if len(values) < 3:
                        continue

                    # Extract fields
                    symbol = values[0] if len(values) > 0 else None
                    report_date_str = values[2] if len(values) > 2 else None
                    fiscal_date_str = values[3] if len(values) > 3 else None
                    estimate = values[4] if len(values) > 4 else None

                    # Skip if no report date
                    if not report_date_str:
                        continue

                    # Parse report date
                    try:
                        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
                    except ValueError:
                        logger.warning(f"{self.name}: Invalid date format for {ticker}: {report_date_str}")
                        continue

                    # Skip past events (keep only future earnings)
                    if report_date < date.today():
                        continue

                    # Skip if event already exists
                    if self.event_exists(asset_id, 'earnings', report_date, self.source_name):
                        continue

                    # Build description
                    description = f"Earnings report for {asset_name}"
                    if fiscal_date_str:
                        description += f" (Fiscal period ending: {fiscal_date_str})"
                    if estimate:
                        try:
                            eps_estimate = float(estimate)
                            description += f"\nEPS Estimate: ${eps_estimate:.2f}"
                        except ValueError:
                            pass

                    # Create event metadata
                    metadata = {
                        'fiscal_date_ending': fiscal_date_str,
                        'eps_estimate': estimate,
                        'symbol': symbol
                    }

                    event = {
                        'asset_id': asset_id,
                        'event_type': 'earnings',
                        'event_date': report_date,
                        'description': description,
                        'source': self.source_name,
                        'metadata': metadata
                    }
                    events.append(event)

                except Exception as e:
                    logger.error(f"{self.name}: Error parsing line for {ticker}: {e}")
                    continue

            logger.info(f"{self.name}: Found {len(events)} upcoming earnings for {ticker}")

        except requests.RequestException as e:
            logger.error(f"{self.name}: Request error for {ticker}: {e}")
        except Exception as e:
            logger.error(f"{self.name}: Error collecting events for {ticker}: {e}")

        return events

    def collect_all_events(self) -> Dict[str, int]:
        """
        Override to add API rate limiting awareness.

        Alpha Vantage free tier: 25 calls/day
        """
        logger.info(f"{self.name}: Starting earnings calendar collection (Rate limit: 25 calls/day)")

        # Call parent implementation
        result = super().collect_all_events()

        logger.info(
            f"{self.name}: API calls used: {len(self.get_assets())}. "
            f"Remaining today: ~{max(0, 25 - len(self.get_assets()))}"
        )

        return result
