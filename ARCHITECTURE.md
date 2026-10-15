# System Architecture

## Overview

The News Trading System is built as a microservices architecture using Docker containers. Each service has a specific responsibility and communicates through a shared PostgreSQL database.

## System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Interface                          │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │              Streamlit Dashboard (Port 8501)              │ │
│  │  - Overview Page        - Alerts Page                     │ │
│  │  - Company Detail Page  - Settings Page                   │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  │ Read/Write
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PostgreSQL Database                        │
│                         (Port 5432)                             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Tables:                                                   │  │
│  │ • companies       - Companies to track                   │  │
│  │ • social_posts    - Raw Reddit posts                     │  │
│  │ • ai_analysis     - AI analysis results                  │  │
│  │ • daily_metrics   - Aggregated daily stats               │  │
│  │ • alerts          - Generated alerts                     │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                    ▲                           ▲
                    │                           │
         Write      │                           │      Write
                    │                           │
    ┌───────────────┴──────────┐    ┌──────────┴───────────────┐
    │  Collector Service       │    │   Analyzer Service       │
    │  (Python + PRAW)         │    │   (Python + Claude AI)   │
    │                          │    │                          │
    │  • Runs every 6 hours    │    │  • Runs every hour       │
    │  • Searches Reddit       │    │  • Analyzes posts        │
    │  • Stores posts          │    │  • Generates alerts      │
    └──────────────────────────┘    └──────────────────────────┘
                    │                           │
                    │                           │
                    ▼                           ▼
    ┌───────────────────────────┐   ┌──────────────────────────┐
    │   Reddit API              │   │   Anthropic Claude API   │
    │   (PRAW)                  │   │   (Claude 3.5 Sonnet)    │
    └───────────────────────────┘   └──────────────────────────┘
```

## Data Flow

### 1. Data Collection Flow

```
Reddit → Collector Service → PostgreSQL (social_posts table)
```

1. Collector service wakes up every 6 hours
2. Fetches list of companies from database
3. For each company:
   - Searches Reddit using company keywords
   - Checks for duplicates
   - Stores new posts in `social_posts` table

### 2. Analysis Flow

```
PostgreSQL (social_posts) → Analyzer Service → Claude API → PostgreSQL (ai_analysis, alerts)
```

1. Analyzer service wakes up every hour
2. Queries for unanalyzed posts (posts without ai_analysis entry)
3. For each post (batch of 10):
   - Sends post content to Claude API
   - Receives structured analysis (sentiment, category, topics, summary)
   - Stores analysis in `ai_analysis` table
   - Generates alerts based on analysis
   - Updates `daily_metrics` table

### 3. Visualization Flow

```
User → Dashboard → PostgreSQL → Dashboard → User
```

1. User opens dashboard in browser
2. Dashboard queries database for:
   - Company metrics
   - Historical trends
   - Recent posts with analysis
   - Alerts
3. Data is visualized using Plotly charts
4. User can interact with data and add new companies

## Service Details

### Collector Service

**Technology**: Python, PRAW (Python Reddit API Wrapper), APScheduler

**Schedule**: Every 6 hours

**Responsibilities**:
- Authenticate with Reddit API
- Search configured subreddits (r/stocks, r/wallstreetbets, r/investing)
- Filter posts by company keywords
- Store unique posts in database
- Handle rate limiting and errors

**Key Features**:
- Duplicate detection (checks `post_id`)
- Rate limiting (2 second delays between requests)
- Robust error handling
- Configurable search keywords per company

### Analyzer Service

**Technology**: Python, Anthropic Claude API, APScheduler

**Schedule**: Every hour

**Responsibilities**:
- Fetch unanalyzed posts
- Send to Claude AI for analysis
- Parse and store structured results
- Generate alerts based on analysis
- Update daily metrics

**Key Features**:
- Batch processing (10 posts at a time)
- Structured JSON output from Claude
- Multiple alert types (hiring, sentiment, problems)
- Automatic metric aggregation

**AI Analysis Output**:
```json
{
  "sentiment": "positive|negative|neutral",
  "sentiment_score": 0.75,
  "category": "Hiring|Growth|Problems|Product|Earnings|Other",
  "key_topics": ["topic1", "topic2", "topic3"],
  "summary": "Brief summary of the post..."
}
```

### Dashboard Service

**Technology**: Python, Streamlit, Plotly, Pandas

**Port**: 8501

**Responsibilities**:
- Provide web interface for users
- Display metrics and visualizations
- Allow company management
- Show alerts and analysis

**Pages**:
1. **Overview**: Company dashboard with 7-day metrics
2. **Company Detail**: Deep dive with charts and posts
3. **Alerts**: Filtered alert feed
4. **Settings**: Add companies, view system status

### Database Service

**Technology**: PostgreSQL 15

**Port**: 5432

**Responsibilities**:
- Store all application data
- Provide ACID transactions
- Support array and JSON data types
- Persist data across restarts

**Key Features**:
- Automatic schema initialization on first run
- Sample companies pre-loaded
- Indexes for query performance
- Volume-based persistence

## Scaling Considerations

### Current Limitations (Prototype)

- Single database instance
- Services run on same host
- No caching layer
- No message queue
- Synchronous processing

### Future Scaling Options

1. **Database**:
   - Add read replicas
   - Implement connection pooling
   - Consider time-series database for metrics

2. **Collector**:
   - Add more data sources (Twitter, news sites)
   - Implement distributed crawling
   - Use message queue for asynchronous processing

3. **Analyzer**:
   - Add caching for API responses
   - Implement batch processing queue
   - Scale horizontally with multiple workers

4. **Dashboard**:
   - Add caching layer (Redis)
   - Implement WebSocket for real-time updates
   - Scale with load balancer

## Security Considerations

### Current Implementation

- API keys stored in environment variables
- Database uses basic authentication
- Services communicate via internal Docker network
- No external authentication

### Production Recommendations

- Use secrets management (AWS Secrets Manager, Vault)
- Implement user authentication (OAuth, JWT)
- Add HTTPS/TLS encryption
- Implement rate limiting
- Add input validation and sanitization
- Use read-only database users where possible
- Regular security updates

## Monitoring and Observability

### Current Logging

- Each service logs to stdout
- Accessible via `docker-compose logs`
- Basic error handling

### Production Recommendations

- Centralized logging (ELK stack, CloudWatch)
- Metrics collection (Prometheus, Grafana)
- Error tracking (Sentry)
- Performance monitoring (New Relic, DataDog)
- Alerting for service failures

## Cost Estimates (Monthly)

### API Costs

- **Reddit API**: Free (with rate limits)
- **Anthropic Claude API**:
  - ~$3 per 1M input tokens
  - ~$15 per 1M output tokens
  - Estimated: $10-50/month depending on volume

### Infrastructure (if deployed to cloud)

- **AWS/GCP/Azure**:
  - Database (RDS/Cloud SQL): $20-100/month
  - Compute (EC2/Compute Engine): $20-50/month
  - Storage: $5-10/month
  - **Total**: $45-160/month

### Local Development

- **Free** (runs on your machine)
- Only API costs apply

## Deployment Options

### 1. Local Development (Current)

```bash
docker-compose up --build
```

**Pros**: Free, easy to test, full control
**Cons**: Not accessible remotely, requires local resources

### 2. Cloud VM (AWS EC2, DigitalOcean, etc.)

1. Launch VM with Docker installed
2. Clone repository
3. Set environment variables
4. Run `docker-compose up -d`

**Pros**: Accessible 24/7, scalable
**Cons**: Monthly costs, maintenance required

### 3. Container Orchestration (Kubernetes, ECS)

1. Create container images
2. Deploy to Kubernetes cluster
3. Configure services and ingress

**Pros**: Highly scalable, production-ready
**Cons**: Complex setup, higher costs

### 4. Serverless (AWS Lambda, Cloud Functions)

1. Refactor services as serverless functions
2. Use managed database (RDS, Aurora)
3. Deploy dashboard to Cloud Run/App Engine

**Pros**: Pay per use, auto-scaling
**Cons**: Significant refactoring needed

## Technology Choices

### Why Docker?

- **Consistency**: Same environment everywhere
- **Isolation**: Services don't interfere
- **Portability**: Deploy anywhere
- **Easy setup**: One command to start

### Why PostgreSQL?

- **Reliability**: ACID compliance
- **Features**: Arrays, JSON, full-text search
- **Performance**: Good for analytical queries
- **Open source**: Free, well-documented

### Why Python?

- **Libraries**: Excellent ecosystem (PRAW, Anthropic, Streamlit)
- **Readability**: Easy to understand and modify
- **Prototyping**: Fast development cycle
- **Data science**: Good for analytics and ML

### Why Streamlit?

- **Speed**: Build dashboards quickly
- **Python-native**: No JavaScript required
- **Interactive**: Built-in widgets and charts
- **Open source**: Free and extensible

### Why Claude AI?

- **Quality**: State-of-the-art language understanding
- **Structured output**: Good at following JSON schemas
- **Long context**: Can handle large posts
- **Cost-effective**: Competitive pricing

## Next Steps

To extend this system:

1. **Add data sources**: Twitter API, financial news feeds
2. **Improve analysis**: Fine-tune prompts, add more categories
3. **Add backtesting**: Correlate signals with actual stock movements
4. **Implement trading**: Connect to broker APIs (Alpaca, Interactive Brokers)
5. **Add notifications**: Email/SMS alerts for signals
6. **Build mobile app**: React Native or Flutter dashboard
7. **Add ML models**: Predict stock movements from signals
8. **Implement paper trading**: Test strategies without real money
