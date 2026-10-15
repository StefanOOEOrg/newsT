"""Chart creation components."""
from datetime import datetime
from typing import Optional
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def create_multi_overlay_chart(
    stock_data: Optional[pd.DataFrame],
    metrics_df: pd.DataFrame,
    alerts_df: pd.DataFrame,
    ticker: str,
    start_date: datetime,
    end_date: datetime,
    show_volume: bool = True,
    show_sentiment: bool = True,
    show_mentions: bool = True,
    show_alerts: bool = True,
    show_signal_strength: bool = True
) -> go.Figure:
    """
    Create an advanced multi-overlay chart similar to Garmin Connect.

    Args:
        stock_data: Stock price and volume data (always displayed)
        metrics_df: Daily metrics (mentions, sentiment)
        alerts_df: Trading alerts
        ticker: Stock ticker symbol
        start_date: Chart start date
        end_date: Chart end date
        show_volume: Toggle trading volume overlay
        show_sentiment: Toggle sentiment overlay
        show_mentions: Toggle mentions overlay
        show_alerts: Toggle alert markers
        show_signal_strength: Toggle daily signal strength bars

    Returns:
        Plotly figure with multiple overlays
    """
    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 1. Stock Price (primary y-axis, left) - ALWAYS DISPLAYED
    if stock_data is not None and not stock_data.empty:
        fig.add_trace(
            go.Scatter(
                x=stock_data['Date'],
                y=stock_data['Close'],
                name='Stock Price',
                line=dict(color='#2ca02c', width=2),
                hovertemplate='<b>Price:</b> $%{y:.2f}<extra></extra>'
            ),
            secondary_y=False
        )

    # 2. Trading Volume (secondary y-axis, right) - as bars with transparency
    if show_volume and stock_data is not None and not stock_data.empty:
        fig.add_trace(
            go.Bar(
                x=stock_data['Date'],
                y=stock_data['Volume'],
                name='Volume',
                marker=dict(color='rgba(31, 119, 180, 0.2)'),
                hovertemplate='<b>Volume:</b> %{y:,.0f}<extra></extra>',
                yaxis='y3'  # Will create third y-axis
            ),
            secondary_y=True
        )

    # 3. Sentiment Score (secondary y-axis, right)
    if show_sentiment and not metrics_df.empty:
        # Add sentiment line
        fig.add_trace(
            go.Scatter(
                x=metrics_df['date'],
                y=metrics_df['sentiment_avg'],
                name='Sentiment',
                line=dict(color='#ff7f0e', width=2),
                hovertemplate='<b>Sentiment:</b> %{y:.2f}<extra></extra>'
            ),
            secondary_y=True
        )

        # Add 7-day moving average
        if 'sentiment_ma7' in metrics_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=metrics_df['date'],
                    y=metrics_df['sentiment_ma7'],
                    name='Sentiment (7-day MA)',
                    line=dict(color='#ff7f0e', width=1, dash='dash'),
                    opacity=0.6,
                    hovertemplate='<b>Sentiment MA:</b> %{y:.2f}<extra></extra>'
                ),
                secondary_y=True
            )

    # 4. Mention Count (secondary y-axis, right)
    if show_mentions and not metrics_df.empty:
        fig.add_trace(
            go.Scatter(
                x=metrics_df['date'],
                y=metrics_df['mention_count'],
                name='Mentions',
                line=dict(color='#9467bd', width=2),
                hovertemplate='<b>Mentions:</b> %{y}<extra></extra>'
            ),
            secondary_y=True
        )

    # 5. Alert Markers (overlaid on chart)
    if show_alerts and not alerts_df.empty:
        alerts_df['alert_timestamp'] = pd.to_datetime(alerts_df['alert_timestamp'])

        # Long signals (green triangles pointing up)
        long_signals = alerts_df[alerts_df['alert_type'] == 'long_signal']
        if not long_signals.empty and stock_data is not None and not stock_data.empty:
            # Find stock prices at alert times
            long_with_prices = pd.merge_asof(
                long_signals.sort_values('alert_timestamp'),
                stock_data.sort_values('Date'),
                left_on='alert_timestamp',
                right_on='Date',
                direction='nearest',
                tolerance=pd.Timedelta('1day')
            )

            fig.add_trace(
                go.Scatter(
                    x=long_with_prices['alert_timestamp'],
                    y=long_with_prices['Close'],
                    mode='markers',
                    marker=dict(
                        size=15,
                        color='#28a745',
                        symbol='triangle-up',
                        line=dict(width=2, color='white')
                    ),
                    name='Long Signal',
                    hovertemplate='<b>Long Signal</b><br>' +
                                 'Date: %{x}<br>' +
                                 'Price: $%{y:.2f}<br>' +
                                 '<extra></extra>'
                ),
                secondary_y=False
            )

        # Short signals (red triangles pointing down)
        short_signals = alerts_df[alerts_df['alert_type'] == 'short_signal']
        if not short_signals.empty and stock_data is not None and not stock_data.empty:
            short_with_prices = pd.merge_asof(
                short_signals.sort_values('alert_timestamp'),
                stock_data.sort_values('Date'),
                left_on='alert_timestamp',
                right_on='Date',
                direction='nearest',
                tolerance=pd.Timedelta('1day')
            )

            fig.add_trace(
                go.Scatter(
                    x=short_with_prices['alert_timestamp'],
                    y=short_with_prices['Close'],
                    mode='markers',
                    marker=dict(
                        size=15,
                        color='#dc3545',
                        symbol='triangle-down',
                        line=dict(width=2, color='white')
                    ),
                    name='Short Signal',
                    hovertemplate='<b>Short Signal</b><br>' +
                                 'Date: %{x}<br>' +
                                 'Price: $%{y:.2f}<br>' +
                                 '<extra></extra>'
                ),
                secondary_y=False
            )

    # 6. Daily Signal Strength (as bars, secondary y-axis)
    if show_signal_strength and not alerts_df.empty:
        # Aggregate signals by date
        alerts_df_copy = alerts_df.copy()
        alerts_df_copy['alert_timestamp'] = pd.to_datetime(alerts_df_copy['alert_timestamp'])
        alerts_df_copy['date'] = alerts_df_copy['alert_timestamp'].dt.date

        # Calculate daily aggregates
        daily_agg = alerts_df_copy.groupby(['date', 'alert_type']).agg({
            'confidence_score': 'sum'
        }).reset_index()

        # Pivot to get long and short signals in separate columns
        daily_pivot = daily_agg.pivot(index='date', columns='alert_type', values='confidence_score').fillna(0)

        # Create net confidence (positive for long, negative for short)
        daily_summary = pd.DataFrame({
            'date': pd.to_datetime(daily_pivot.index),
            'long_confidence': daily_pivot.get('long_signal', 0),
            'short_confidence': daily_pivot.get('short_signal', 0)
        })
        daily_summary['net_confidence'] = daily_summary['long_confidence'] - daily_summary['short_confidence']
        daily_summary['color'] = daily_summary['net_confidence'].apply(
            lambda x: 'rgba(40, 167, 69, 0.4)' if x > 0 else 'rgba(220, 53, 69, 0.4)'
        )

        # Add bar chart
        fig.add_trace(
            go.Bar(
                x=daily_summary['date'],
                y=daily_summary['net_confidence'],
                name='Signal Strength',
                marker=dict(
                    color=daily_summary['color'],
                    line=dict(width=0.5, color='rgba(0,0,0,0.2)')
                ),
                hovertemplate='<b>Net Signal Strength:</b> %{y:.2f}<br>' +
                             '<b>Date:</b> %{x}<extra></extra>',
                yaxis='y4'  # Fourth y-axis for signal strength
            ),
            secondary_y=True
        )

    # Configure layout with dark theme to match dashboard
    fig.update_layout(
        title=dict(
            text=f"{ticker} - Multi-Metric Analysis",
            font=dict(size=20, color='#ffffff')
        ),
        height=800,
        hovermode='x unified',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(20, 20, 20, 0.95)",
            bordercolor="#444444",
            borderwidth=1,
            font=dict(size=11, color='#ffffff')
        ),
        xaxis=dict(
            title='Date',
            title_font=dict(color='#ffffff'),
            range=[start_date, end_date],
            showgrid=True,
            gridcolor='rgba(80, 80, 80, 0.3)',
            gridwidth=1,
            tickfont=dict(color='#cccccc')
        ),
        plot_bgcolor='#000000',  # Black background to match dashboard
        paper_bgcolor='#0e1117'  # Dark background to match Streamlit dark theme
    )

    # Set y-axis titles with dark theme colors
    fig.update_yaxes(
        title_text="Stock Price (USD)",
        title_font=dict(color='#ffffff'),
        secondary_y=False,
        showgrid=True,
        gridcolor='rgba(80, 80, 80, 0.3)',
        gridwidth=1,
        tickfont=dict(color='#cccccc')
    )
    fig.update_yaxes(
        title_text="Metrics (Sentiment / Mentions / Volume)",
        title_font=dict(color='#ffffff'),
        secondary_y=True,
        showgrid=False,
        tickfont=dict(color='#cccccc')
    )

    # Add range slider with dark theme colors
    fig.update_xaxes(
        rangeslider_visible=True,
        rangeslider=dict(
            bgcolor='#1a1a1a',
            bordercolor='#444444',
            borderwidth=1
        ),
        rangeselector=dict(
            buttons=list([
                dict(count=7, label="1w", step="day", stepmode="backward"),
                dict(count=1, label="1m", step="month", stepmode="backward"),
                dict(count=3, label="3m", step="month", stepmode="backward"),
                dict(step="all", label="All")
            ]),
            bgcolor="rgba(20, 20, 20, 0.95)",
            activecolor="#4CAF50",
            bordercolor='#444444',
            borderwidth=1,
            font=dict(color='#ffffff')
        )
    )

    return fig
