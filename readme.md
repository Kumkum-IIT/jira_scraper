# Apache Jira Data Scraping Pipeline

A production-ready, fault-tolerant system for extracting public issue data from Apache's Jira instance and transforming it into LLM training format.

## Features

### 1. **Robust Data Scraping**
- ✅ Fetches issues, comments, and metadata from Apache Jira
- ✅ Handles pagination automatically
- ✅ Smart rate limiting with token bucket algorithm
- ✅ Exponential backoff retry strategy
- ✅ Handles HTTP 429, 5xx errors gracefully
- ✅ Request timeout handling (30s default)
- ✅ Resume capability from last successful state

### 2. **Fault Tolerance**
- ✅ State persistence across interruptions
- ✅ Automatic retry with exponential backoff
- ✅ Graceful handling of malformed/empty data
- ✅ Comprehensive error logging
- ✅ Data validation at multiple stages

### 3. **Data Quality**
- ✅ Input validation and sanitization
- ✅ Text cleaning and normalization
- ✅ Structured JSONL output format
- ✅ Deduplication via unique IDs
- ✅ Metadata enrichment

## Architecture

```
┌─────────────────┐
│  Jira REST API  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│      JiraScraper            │
│  - Rate Limiting            │
│  - Retry Logic              │
│  - State Management         │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│   Raw JSONL Storage         │
│   (project_raw.jsonl)       │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│    DataTransformer          │
│  - Cleaning                 │
│  - Structuring              │
│  - Formatting               │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Training Corpus            │
│  (project_training.jsonl)   │
└─────────────────────────────┘
```

## Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install requests urllib3

# Create necessary directories
mkdir -p data state processed logs
```

## Usage

### Basic Usage

```python
from jira_scraper import JiraScraper, DataTransformer

# Initialize scraper
scraper = JiraScraper(
    output_dir="data",
    state_dir="state",
    rate_limit_requests=50,
    rate_limit_window=60
)

# Scrape a project
scraper.scrape_project('KAFKA', max_issues=5000)

# Transform data
transformer = DataTransformer(input_dir="data", output_dir="processed")
transformer.transform_project('KAFKA')
```

### Advanced Configuration

```python
# Custom rate limiting
scraper = JiraScraper(
    rate_limit_requests=30,  # 30 requests
    rate_limit_window=60,     # per 60 seconds
    max_retries=10            # retry up to 10 times
)

# Scrape multiple projects
projects = ['KAFKA', 'SPARK', 'HADOOP', 'FLINK', 'HBASE']
for project in projects:
    scraper.scrape_project(project)
```

### Resume After Interruption

The scraper automatically saves state after each batch:

```python
# If interrupted, simply run again - it will resume
scraper.scrape_project('KAFKA')  # Resumes from last checkpoint
```

## Rate Limiting Strategy

### Token Bucket Algorithm
- Default: 50 requests per 60 seconds
- Configurable based on API limits
- Automatic backoff when limit approached
- Respects HTTP 429 Retry-After headers

### Retry Strategy
- **Status Codes**: 429, 500, 502, 503, 504
- **Backoff**: Exponential (2, 4, 8, 16, 32 seconds)
- **Max Retries**: 5 (configurable)
- **Timeout**: 30 seconds per request

## Output Format

### Raw Data (JSONL)
```json
{
  "key": "KAFKA-12345",
  "fields": {
    "summary": "Issue summary",
    "description": "Detailed description",
    "status": {"name": "Open"},
    "priority": {"name": "Major"},
    "comment": {"comments": [...]},
    ...
  }
}
```

### Training Corpus (JSONL)
```json
{
  "id": "abc123...",
  "issue_key": "KAFKA-12345",
  "issue_type": "Bug",
  "status": "Resolved",
  "priority": "Major",
  "summary": "Memory leak in consumer",
  "description": "Detailed description...",
  "reporter": "John Doe",
  "assignee": "Jane Smith",
  "created": "2024-01-15T10:30:00.000+0000",
  "updated": "2024-01-20T15:45:00.000+0000",
  "labels": ["performance", "memory"],
  "components": ["consumer"],
  "comments": [
    {
      "author": "John Doe",
      "body": "I can reproduce this...",
      "created": "2024-01-16T09:00:00.000+0000"
    }
  ],
  "num_comments": 5,
  "text": "Issue: KAFKA-12345\nSummary: Memory leak...",
  "metadata": {
    "source": "apache_jira",
    "scraped_at": "2024-01-25T12:00:00"
  }
}
```

## Error Handling

### Network Errors
```python
# Automatic retry with exponential backoff
# Logs all failures for debugging
# Gracefully handles timeouts
```

### Data Validation
```python
def _validate_issue(self, issue: Dict) -> bool:
    """Validates required fields exist"""
    required_fields = ['key', 'fields']
    return all(field in issue for field in required_fields)
```

### Malformed Data
- Skips invalid records with warning logs
- Continues processing remaining data
- Tracks failed records for manual review

## State Management

State files store:
- Last successfully scraped issue key
- Current pagination position
- Total issues scraped
- Last update timestamp

```json
{
  "project": "KAFKA",
  "last_issue_key": "KAFKA-12345",
  "last_start_at": 2500,
  "total_issues_scraped": 2543,
  "last_updated": "2024-01-25T12:30:45"
}
```

## Monitoring & Logging

Logs capture:
- Scraping progress
- Rate limit hits
- HTTP errors
- Retry attempts
- Data validation failures
- Processing statistics

```
2024-01-25 12:00:00 - INFO - Starting scrape for project: KAFKA
2024-01-25 12:00:05 - INFO - Fetching KAFKA issues from 0
2024-01-25 12:00:10 - INFO - Progress: 50 issues scraped from KAFKA
2024-01-25 12:00:15 - WARNING - Rate limit reached. Sleeping for 45.0s
```

## Performance Optimization

### Batch Processing
- Fetches 50 issues per request (configurable)
- Streams data to disk (low memory footprint)
- Incremental state saves

### Resource Usage
- **Memory**: O(batch_size) - typically <100MB
- **Disk**: ~1-5KB per issue
- **Network**: ~50 requests/minute (conservative)

## Recommended Apache Projects

High-quality projects with rich discussion:

1. **KAFKA** - Distributed streaming platform
2. **SPARK** - Big data processing engine
3. **HADOOP** - Distributed storage and computing
4. **FLINK** - Stream processing framework
5. **HBASE** - NoSQL database
6. **CASSANDRA** - Distributed database
7. **AIRFLOW** - Workflow orchestration
8. **BEAM** - Unified data processing

## Scaling Considerations

### For Large-Scale Scraping:

1. **Parallel Processing**
   ```python
   # Use multiprocessing for multiple projects
   from multiprocessing import Pool
   
   with Pool(3) as p:
       p.map(scraper.scrape_project, projects)
   ```

2. **Database Storage**
   - Replace JSONL with PostgreSQL/MongoDB
   - Better query capabilities
   - Easier deduplication

3. **Cloud Deployment**
   - AWS Lambda for serverless scraping
   - S3 for data storage
   - CloudWatch for monitoring

## Data Quality Checks

```python
# Check data quality
import json

def analyze_corpus(file_path):
    stats = {
        'total': 0,
        'with_description': 0,
        'with_comments': 0,
        'avg_text_length': 0
    }
    
    total_length = 0
    
    with open(file_path) as f:
        for line in f:
            record = json.loads(line)
            stats['total'] += 1
            
            if record.get('description'):
                stats['with_description'] += 1
            
            if record.get('comments'):
                stats['with_comments'] += 1
            
            total_length += len(record.get('text', ''))
    
    stats['avg_text_length'] = total_length / stats['total']
    return stats
```

## Best Practices

1. **Start Small**: Test with `max_issues=100` first
2. **Monitor Logs**: Check for rate limit warnings
3. **Validate Output**: Inspect first few records manually
4. **Backup State**: Copy state files before major changes
5. **Rate Limit Buffer**: Stay 20% below API limits

## Troubleshooting

### Issue: Rate limited despite conservative settings
**Solution**: Increase `rate_limit_window` or decrease `rate_limit_requests`

### Issue: Connection timeouts
**Solution**: Increase timeout in `_make_request()` or check network

### Issue: State file corruption
**Solution**: Delete state file to restart, implement JSON validation

### Issue: Memory errors on large projects
**Solution**: Reduce `max_results` batch size, process in chunks

## License

This tool is for research and educational purposes. Respect Apache Jira's terms of service and rate limits.

## Contributing

Contributions welcome! Areas for improvement:
- Database backend support
- Parallel project scraping
- Additional data enrichment
- Export format options (Parquet, CSV)
- Web UI for monitoring