"""
Apache Jira Data Scraping and Transformation Pipeline
A production-ready system for extracting and processing Jira issues for LLM training.
includes derived tasks: summarization, classification, and Q&A pairs.
"""

import json
import time
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import hashlib
import re


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('jira_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class ScraperState:
    """Tracks scraping progress for resumability."""
    project: str
    last_issue_key: Optional[str] = None
    last_start_at: int = 0
    total_issues_scraped: int = 0
    last_updated: str = None
    
    def save(self, state_dir: Path):
        """Save state to disk."""
        state_file = state_dir / f"{self.project}_state.json"
        with open(state_file, 'w') as f:
            json.dump(asdict(self), f, indent=2)
    
    @classmethod
    def load(cls, project: str, state_dir: Path):
        """Load state from disk."""
        state_file = state_dir / f"{project}_state.json"
        if state_file.exists():
            with open(state_file, 'r') as f:
                data = json.load(f)
                return cls(**data)
        return cls(project=project)


class RateLimiter:
    """Implements token bucket rate limiting."""
    
    def __init__(self, max_requests: int = 60, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    def wait_if_needed(self):
        """Wait if rate limit would be exceeded."""
        now = time.time()
        # Remove old requests outside time window
        self.requests = [req_time for req_time in self.requests 
                        if now - req_time < self.time_window]
        
        if len(self.requests) >= self.max_requests:
            sleep_time = self.time_window - (now - self.requests[0]) + 1
            logger.info(f"Rate limit reached. Sleeping for {sleep_time:.2f}s") #Sleeps when the limit is reached to avoid 429s
            time.sleep(sleep_time)
            self.requests = []
        
        self.requests.append(now)


class JiraScraper:
    """Main scraper class for Apache Jira."""
    
    BASE_URL = "https://issues.apache.org/jira"
    
    def __init__(
        self,
        output_dir: str = "data",
        state_dir: str = "state",
        max_retries: int = 5,
        rate_limit_requests: int = 50,
        rate_limit_window: int = 60
    ):
        self.output_dir = Path(output_dir)
        self.state_dir = Path(state_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.state_dir.mkdir(exist_ok=True)
        
        # Setup session with retry logic
        self.session = self._create_session(max_retries)
        
        # Rate limiter
        self.rate_limiter = RateLimiter(rate_limit_requests, rate_limit_window)
        
        logger.info("JiraScraper initialized")
    
    def _create_session(self, max_retries: int) -> requests.Session:
        """Create requests session with retry logic."""
        session = requests.Session()
        
        # Retry on 429, 500, 502, 503, 504
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=2,  # Exponential backoff: 2, 4, 8, 16, 32 seconds
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Set headers
        session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'Apache-Jira-Research-Scraper/1.0'
        })
        
        return session
    
    def _make_request(self, url: str, params: Dict = None) -> Optional[Dict]:
        """Make HTTP request with rate limiting and error handling."""
        self.rate_limiter.wait_if_needed()
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                retry_after = int(e.response.headers.get('Retry-After', 60))
                logger.warning(f"Rate limited. Waiting {retry_after}s")
                time.sleep(retry_after)
                return self._make_request(url, params)
            else:
                logger.error(f"HTTP error: {e}")
                return None
        
        except requests.exceptions.Timeout:
            logger.error(f"Request timeout for {url}")
            return None
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            return None
        
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON response from {url}")
            return None
    
    def get_project_issues(
        self,
        project_key: str,
        start_at: int = 0,
        max_results: int = 50
    ) -> Optional[Dict]:
        """Fetch issues for a project with pagination."""
        url = f"{self.BASE_URL}/rest/api/2/search"
        
        jql = f"project = {project_key} ORDER BY created ASC"
        
        params = {
            'jql': jql,
            'startAt': start_at,
            'maxResults': max_results,
            'fields': ','.join([
                'summary', 'description', 'status', 'priority',
                'assignee', 'reporter', 'created', 'updated',
                'resolutiondate', 'labels', 'components',
                'issuetype', 'comment', 'attachment', 'resolution'
            ])
        }
        
        logger.info(f"Fetching {project_key} issues from {start_at}")
        return self._make_request(url, params)
    
    def scrape_project(self, project_key: str, max_issues: Optional[int] = None):
        """Scrape all issues from a project."""
        logger.info(f"Starting scrape for project: {project_key}")
        
        # Load state
        state = ScraperState.load(project_key, self.state_dir)
        start_at = state.last_start_at
        
        # Output file
        output_file = self.output_dir / f"{project_key}_raw.jsonl"
        mode = 'a' if output_file.exists() else 'w'
        
        total_scraped = state.total_issues_scraped
        batch_size = 50
        
        with open(output_file, mode, encoding='utf-8') as f:
            while True:
                if max_issues and total_scraped >= max_issues:
                    logger.info(f"Reached max issues limit: {max_issues}")
                    break
                
                # Fetch batch
                response = self.get_project_issues(
                    project_key,
                    start_at=start_at,
                    max_results=batch_size
                )
                
                if not response:
                    logger.error("Failed to fetch issues. Saving state and exiting.")
                    break
                
                issues = response.get('issues', [])
                if not issues:
                    logger.info(f"No more issues to fetch for {project_key}")
                    break
                
                # Process and save issues
                for issue in issues:
                    if not self._validate_issue(issue):
                        logger.warning(f"Invalid issue data: {issue.get('key', 'UNKNOWN')}")
                        continue
                    
                    # Write to JSONL
                    f.write(json.dumps(issue, ensure_ascii=False) + '\n')
                    total_scraped += 1
                    
                    # Update state
                    state.last_issue_key = issue['key']
                
                # Update pagination
                start_at += len(issues)
                state.last_start_at = start_at
                state.total_issues_scraped = total_scraped
                state.last_updated = datetime.now().isoformat()
                
                # Save state
                state.save(self.state_dir)
                
                logger.info(
                    f"Progress: {total_scraped} issues scraped from {project_key}"
                )
                
                # Check if we've reached the end
                if start_at >= response.get('total', 0):
                    logger.info(f"Completed scraping {project_key}")
                    break
        
        logger.info(f"Finished scraping {project_key}. Total: {total_scraped} issues")
        return total_scraped
    
    def _validate_issue(self, issue: Dict) -> bool:
        """Validate issue data structure."""
        required_fields = ['key', 'fields']
        return all(field in issue for field in required_fields)


class DerivedTaskGenerator:
    """Generates derived tasks for LLM training: summarization, classification, Q&A."""
    
    def __init__(self):
        pass
    
    def generate_summarization_task(self, issue_data: Dict) -> Dict:
        """Create summarization task from issue."""
        full_text = self._build_full_context(issue_data)
        summary = issue_data.get('summary', '')
        
        return {
            'task_type': 'summarization',
            'input': full_text,
            'output': summary,
            'instruction': 'Summarize the following software issue in one concise sentence:'
        }
    
    def generate_classification_tasks(self, issue_data: Dict) -> List[Dict]:
        """Create multiple classification tasks."""
        description = issue_data.get('description', '')
        if not description:
            return []
        
        tasks = []
        
        # Issue Type Classification
        tasks.append({
            'task_type': 'classification',
            'subtask': 'issue_type',
            'input': f"Issue: {issue_data.get('summary', '')}\n\nDescription: {description}",
            'output': issue_data.get('issue_type', 'Unknown'),
            'instruction': 'Classify this software issue type (Bug, Feature, Improvement, Task, etc.):'
        })
        
        # Priority Classification
        if issue_data.get('priority'):
            tasks.append({
                'task_type': 'classification',
                'subtask': 'priority',
                'input': f"{issue_data.get('summary', '')}\n\n{description}",
                'output': issue_data.get('priority'),
                'instruction': 'Classify the priority level of this issue (Critical, Major, Minor, Trivial):'
            })
        
        # Status Prediction (based on description alone)
        if issue_data.get('status'):
            tasks.append({
                'task_type': 'classification',
                'subtask': 'status',
                'input': description,
                'output': issue_data.get('status'),
                'instruction': 'Based on this issue description, predict its current status:'
            })
        
        # Component Classification
        if issue_data.get('components'):
            tasks.append({
                'task_type': 'classification',
                'subtask': 'component',
                'input': f"{issue_data.get('summary', '')}\n\n{description}",
                'output': ', '.join(issue_data.get('components', [])),
                'instruction': 'Identify which component(s) this issue relates to:'
            })
        
        return tasks
    
    def generate_qa_pairs(self, issue_data: Dict) -> List[Dict]:
        """Generate question-answer pairs from issue data."""
        qa_pairs = []
        
        issue_key = issue_data.get('issue_key', '')
        summary = issue_data.get('summary', '')
        description = issue_data.get('description', '')
        status = issue_data.get('status', '')
        priority = issue_data.get('priority', '')
        resolution = issue_data.get('resolution', '')
        
        context = f"Issue {issue_key}: {summary}\n\n{description}"
        
        # Q&A about issue summary
        if summary:
            qa_pairs.append({
                'task_type': 'qa',
                'question': f'What is issue {issue_key} about?',
                'answer': summary,
                'context': context
            })
        
        # Q&A about status
        if status:
            qa_pairs.append({
                'task_type': 'qa',
                'question': f'What is the current status of {issue_key}?',
                'answer': f'The issue status is: {status}',
                'context': context
            })
        
        # Q&A about priority
        if priority:
            qa_pairs.append({
                'task_type': 'qa',
                'question': f'What is the priority level of {issue_key}?',
                'answer': f'This issue has {priority} priority.',
                'context': context
            })
        
        # Q&A about resolution
        if resolution:
            qa_pairs.append({
                'task_type': 'qa',
                'question': f'How was {issue_key} resolved?',
                'answer': f'Resolution: {resolution}',
                'context': context
            })
        
        # Q&A about reporter/assignee
        if issue_data.get('reporter'):
            qa_pairs.append({
                'task_type': 'qa',
                'question': f'Who reported {issue_key}?',
                'answer': issue_data['reporter'],
                'context': context
            })
        
        if issue_data.get('assignee'):
            qa_pairs.append({
                'task_type': 'qa',
                'question': f'Who is assigned to {issue_key}?',
                'answer': issue_data['assignee'],
                'context': context
            })
        
        # Q&A from comments (if solution provided)
        comments = issue_data.get('comments', [])
        if comments:
            # Look for solution-like comments
            for comment in comments:
                body = comment.get('body', '').lower()
                if any(keyword in body for keyword in ['solution', 'fix', 'resolved', 'workaround']):
                    qa_pairs.append({
                        'task_type': 'qa',
                        'question': f'What was the solution for {issue_key}?',
                        'answer': comment.get('body', '')[:500],  # Limit length
                        'context': context
                    })
                    break  # Only one solution Q&A
        
        return qa_pairs
    
    def _build_full_context(self, issue_data: Dict) -> str:
        """Build full text context from issue."""
        parts = []
        
        if issue_data.get('summary'):
            parts.append(f"Summary: {issue_data['summary']}")
        
        if issue_data.get('description'):
            parts.append(f"Description: {issue_data['description']}")
        
        comments = issue_data.get('comments', [])
        if comments:
            parts.append(f"\nComments ({len(comments)}):")
            for i, comment in enumerate(comments[:5], 1):  # Limit to first 5
                parts.append(f"{i}. {comment.get('body', '')}")
        
        return "\n".join(parts)


class DataTransformer:
    """Transform raw Jira data into LLM training format with derived tasks."""
    
    def __init__(self, input_dir: str = "data", output_dir: str = "processed"):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.task_generator = DerivedTaskGenerator()
    
    def transform_project(self, project_key: str, include_tasks: bool = True):
        """Transform raw project data into training corpus with derived tasks."""
        input_file = self.input_dir / f"{project_key}_raw.jsonl"
        
        # Create separate output files
        base_output = self.output_dir / f"{project_key}_training.jsonl"
        tasks_output = self.output_dir / f"{project_key}_tasks.jsonl"
        
        if not input_file.exists():
            logger.error(f"Input file not found: {input_file}")
            return
        
        logger.info(f"Transforming {project_key} data")
        
        total_records = 0
        total_tasks = 0
        
        with open(input_file, 'r', encoding='utf-8') as infile, \
             open(base_output, 'w', encoding='utf-8') as base_out, \
             open(tasks_output, 'w', encoding='utf-8') as tasks_out:
            
            for line_num, line in enumerate(infile, 1):
                try:
                    issue = json.loads(line)
                    transformed = self._transform_issue(issue)
                    
                    if transformed:
                        # Write base record
                        base_out.write(json.dumps(transformed, ensure_ascii=False) + '\n')
                        total_records += 1
                        
                        # Generate and write derived tasks
                        if include_tasks:
                            tasks = self._generate_all_tasks(transformed)
                            for task in tasks:
                                task['source_issue'] = transformed['issue_key']
                                task['project'] = project_key
                                tasks_out.write(json.dumps(task, ensure_ascii=False) + '\n')
                                total_tasks += 1
                
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON at line {line_num}")
                except Exception as e:
                    logger.error(f"Error transforming issue at line {line_num}: {e}")
        
        logger.info(f"Transformation complete:")
        logger.info(f"  - Base records: {total_records} -> {base_output}")
        logger.info(f"  - Derived tasks: {total_tasks} -> {tasks_output}")
    
    def _transform_issue(self, issue: Dict) -> Optional[Dict]:
        """Transform single issue into training format."""
        try:
            fields = issue.get('fields', {})
            
            # Extract and clean data
            issue_key = issue.get('key', '')
            summary = self._clean_text(fields.get('summary', ''))
            description = self._clean_text(fields.get('description', ''))
            
            # Extract comments
            comments = self._extract_comments(fields.get('comment', {}))
            
            # Build structured record
            record = {
                'id': self._generate_id(issue_key),
                'issue_key': issue_key,
                'issue_type': self._safe_get(fields, 'issuetype', 'name'),
                'status': self._safe_get(fields, 'status', 'name'),
                'priority': self._safe_get(fields, 'priority', 'name'),
                'resolution': self._safe_get(fields, 'resolution', 'name'),
                'summary': summary,
                'description': description,
                'reporter': self._safe_get(fields, 'reporter', 'displayName'),
                'assignee': self._safe_get(fields, 'assignee', 'displayName'),
                'created': fields.get('created'),
                'updated': fields.get('updated'),
                'resolved': fields.get('resolutiondate'),
                'labels': fields.get('labels', []),
                'components': [
                    comp.get('name') for comp in fields.get('components', [])
                ],
                'comments': comments,
                'num_comments': len(comments),
                
                # Combined text for training
                'text': self._create_training_text(
                    issue_key, summary, description, comments
                ),
                
                # Metadata
                'metadata': {
                    'source': 'apache_jira',
                    'scraped_at': datetime.now().isoformat()
                }
            }
            
            return record
        
        except Exception as e:
            logger.error(f"Error transforming issue {issue.get('key')}: {e}")
            return None
    
    def _generate_all_tasks(self, issue_data: Dict) -> List[Dict]:
        """Generate all derived tasks for an issue."""
        tasks = []
        
        # Summarization task
        if issue_data.get('description'):
            summarization = self.task_generator.generate_summarization_task(issue_data)
            tasks.append(summarization)
        
        # Classification tasks
        classification_tasks = self.task_generator.generate_classification_tasks(issue_data)
        tasks.extend(classification_tasks)
        
        # Q&A pairs
        qa_pairs = self.task_generator.generate_qa_pairs(issue_data)
        tasks.extend(qa_pairs)
        
        return tasks
    
    def _clean_text(self, text: Optional[str]) -> str:
        """Clean and normalize text."""
        if not text:
            return ""
        
        # Remove excessive whitespace
        text = ' '.join(text.split())
        
        # Remove null bytes
        text = text.replace('\x00', '')
        
        # Remove common Jira markup artifacts
        text = re.sub(r'\{code[^}]*\}', '', text)
        text = re.sub(r'\{quote\}', '', text)
        text = re.sub(r'\{noformat\}', '', text)
        
        return text.strip()
    
    def _extract_comments(self, comment_data: Dict) -> List[Dict]:
        """Extract and structure comments."""
        comments = []
        
        for comment in comment_data.get('comments', []):
            comments.append({
                'author': self._safe_get(comment, 'author', 'displayName'),
                'body': self._clean_text(comment.get('body', '')),
                'created': comment.get('created')
            })
        
        return comments
    
    def _safe_get(self, obj: Dict, *keys) -> Optional[str]:
        """Safely navigate nested dictionary."""
        for key in keys:
            if obj is None:
                return None
            obj = obj.get(key)
        return obj
    
    def _generate_id(self, issue_key: str) -> str:
        """Generate unique ID for record."""
        return hashlib.md5(issue_key.encode()).hexdigest()
    
    def _create_training_text(
        self,
        issue_key: str,
        summary: str,
        description: str,
        comments: List[Dict]
    ) -> str:
        """Create formatted text for LLM training."""
        parts = [
            f"Issue: {issue_key}",
            f"Summary: {summary}",
        ]
        
        if description:
            parts.append(f"Description: {description}")
        
        if comments:
            parts.append(f"\nComments ({len(comments)}):")
            for i, comment in enumerate(comments[:10], 1):  # Limit to 10 comments
                author = comment.get('author', 'Unknown')
                body = comment.get('body', '')
                if body:
                    parts.append(f"{i}. {author}: {body}")
        
        return "\n".join(parts)


# Example usage
if __name__ == "__main__":
    # Apache projects to scrape
    PROJECTS = ['KAFKA', 'SPARK', 'HADOOP']
    
    # Initialize scraper
    scraper = JiraScraper(
        output_dir="data",
        state_dir="state",
        rate_limit_requests=50
    )
    
    # Scrape projects
    for project in PROJECTS:
        try:
            scraper.scrape_project(project, max_issues=1000)  # Limit for demo
        except Exception as e:
            logger.error(f"Failed to scrape {project}: {e}")
    
    # Transform data with derived tasks
    transformer = DataTransformer(input_dir="data", output_dir="processed")
    
    for project in PROJECTS:
        try:
            transformer.transform_project(project, include_tasks=True)
        except Exception as e:
            logger.error(f"Failed to transform {project}: {e}")
    
    logger.info("Pipeline completed successfully with derived tasks!")