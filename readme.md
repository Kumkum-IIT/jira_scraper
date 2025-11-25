# Apache Jira Data Scraping Pipeline

A production-ready, fault-tolerant system for extracting public issue data from Apache's Jira instance and transforming it into LLM training format.

## Features

### 1. **Robust Data Scraping**
- Fetches issues, comments, and metadata from Apache Jira
- Handles pagination automatically
- Smart rate limiting with token bucket algorithm
- Exponential backoff retry strategy
- Handles HTTP 429, 5xx errors gracefully
- Request timeout handling (30s default)
- Resume capability from last successful state

### 2. **Fault Tolerance**
- State persistence across interruptions
- Automatic retry with exponential backoff
- Graceful handling of malformed/empty data
- Comprehensive error logging
- Data validation at multiple stages

### 3. **Data Quality**
- Input validation and sanitization
- Text cleaning and normalization
- Structured JSONL output format
- Deduplication via unique IDs
- Metadata enrichment

### 4. **Design Reasoning**
- **JSONL storage** keeps ingestion append-only, stream-friendly, and tooling-compatible.
- **Token bucket rate limiting** plus retries prevent API bans while keeping throughput predictable.

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
pip install -r requirments.txt

```

## Usage
**projects scraped are: "KAFKA", "SPARK", "HADOOP"**

### Advanced Configuration 
# Initialize scraper
```python
scraper = JiraScraper(
    output_dir="data",
    state_dir="state",
    rate_limit_requests=50,
    rate_limit_window=60 # also retry up to 10 times
)

# Scrape a project
scraper.scrape_project('KAFKA', max_issues=5000)

# Transform data
transformer = DataTransformer(input_dir="data", output_dir="processed")
transformer.transform_project('KAFKA')
```


### Resume After Interruption

The scraper automatically saves state after each batch:

```python
# If interrupted, simply run again - it will resume
scraper.scrape_project('KAFKA')  # Resumes from last checkpoint
```

### Retry Strategy
- **Status Codes**: 429, 500, 502, 503, 504
- **Backoff**: Exponential (2, 4, 8, 16, 32 seconds)
- **Max Retries**: 5 (configurable)
- **Timeout**: 30 seconds per request

## Output Format

### Raw Data (JSONL) (under data folder)
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

### Training Corpus (JSONL) (under processed folder in projects_training file)
```json
{
  "id": "abc123...",
  "issue_key": "KAFKA-12345",
  "issue_type": "Bug",
  "status": "Resolved",
  "priority": "Major",
  "resolution": "Fixed",
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

### Derived Tasks (JSONL) (under processed folder in project_tasks file)
The pipeline generates multiple task types from each issue:

**1. Summarization Task:**
```json
{
  "task_type": "summarization",
  "instruction": "Summarize the following software issue in one concise sentence:",
  "input": "Summary: Memory leak...\nDescription: Full text...",
  "output": "Memory leak in consumer",
  "source_issue": "KAFKA-12345",
  "project": "KAFKA"
}
```

**2. Classification Tasks:**
```json
{
  "task_type": "classification",
  "subtask": "issue_type",
  "instruction": "Classify this software issue type (Bug, Feature, Improvement, Task, etc.):",
  "input": "Issue: Memory leak in consumer\n\nDescription: ...",
  "output": "Bug",
  "source_issue": "KAFKA-12345",
  "project": "KAFKA"
}

{
  "task_type": "classification",
  "subtask": "priority",
  "instruction": "Classify the priority level of this issue (Critical, Major, Minor, Trivial):",
  "input": "Memory leak in consumer\n\nWhen consuming...",
  "output": "Major",
  "source_issue": "KAFKA-12345",
  "project": "KAFKA"
}
```

**3. Question-Answer Pairs:**
```json
{
  "task_type": "qa",
  "question": "What is issue KAFKA-12345 about?",
  "answer": "Memory leak in consumer",
  "context": "Issue KAFKA-12345: Memory leak...",
  "source_issue": "KAFKA-12345",
  "project": "KAFKA"
}

{
  "task_type": "qa",
  "question": "What is the current status of KAFKA-12345?",
  "answer": "The issue status is: Resolved",
  "context": "Issue KAFKA-12345: Memory leak...",
  "source_issue": "KAFKA-12345",
  "project": "KAFKA"
}
```
## State Management (under state folder)

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

## Error Handling

### Network Errors
```python
# Automatic retry with exponential backoff
# Logs all failures for debugging
# Gracefully handles timeouts
```

### Malformed Data
- Skips invalid records with warning logs
- Continues processing remaining data
- Logs failed records for manual review

## Edge Cases Covered
- **Empty or overly long descriptions**: cleaning pipeline collapses whitespace and trims control characters.
- **Missing fields**: `_safe_get` prevents KeyErrors, `_validate_issue` drops malformed payloads, and validation stats call out missing metadata.
- **Non-UTF-8/control chars**: `_clean_text` strips null bytes and Jira markup tags.
- **Partial batch failures**: batches persist after every successful write; failures log and leave state pointing at the last good offset.
- **Rate limiting vs hard failures**: token bucket smooths bursts, retries backoff for 429/5xx, and unrecoverable errors log + exit gracefully.
- **Max retries exhausted**: scraper records the error, saves current state, and stops so the operator can resume later.
- **Timeouts**: 30s request timeout prevents hung connections.
- **Corrupt/missing state file**: defaults to a fresh `ScraperState`, effectively restarting the project from scratch while preserving prior data files.

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

### Performance & Optimization Decisions
- **Batch size 50** balances Jira’s search limits with manageable payload size.
- **Connection pooling (`requests.Session`)** avoids TCP setup costs per request.
- **Retry/backoff strategy** keeps the pipeline busy without thrashing the API.
- **Comment cap (10 comments)** limits text cleaning overhead while keeping sufficient context.
- **On-disk streaming** avoids loading entire corpora into memory when transforming or sampling.


