"""
Utility scripts for Jira scraper pipeline.
Includes data validation, analysis, and helper functions.
"""

import json
import logging
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, List, Tuple
from datetime import datetime
import statistics


logger = logging.getLogger(__name__)


class DataValidator:
    """Validates scraped and transformed data quality."""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def validate_raw_data(self, file_path: Path) -> Dict:
        """Validate raw JSONL file."""
        stats = {
            'total_records': 0,
            'valid_records': 0,
            'invalid_records': 0,
            'missing_fields': defaultdict(int),
            'empty_fields': defaultdict(int)
        }
        
        required_fields = ['key', 'fields']
        important_fields = ['summary', 'description', 'status', 'created']
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                stats['total_records'] += 1
                
                try:
                    record = json.loads(line)
                    
                    # Check required fields
                    if all(field in record for field in required_fields):
                        stats['valid_records'] += 1
                    else:
                        stats['invalid_records'] += 1
                        missing = [f for f in required_fields if f not in record]
                        for field in missing:
                            stats['missing_fields'][field] += 1
                    
                    # Check important fields
                    fields = record.get('fields', {})
                    for field in important_fields:
                        if field not in fields:
                            stats['missing_fields'][field] += 1
                        elif not fields[field]:
                            stats['empty_fields'][field] += 1
                
                except json.JSONDecodeError:
                    stats['invalid_records'] += 1
                    logger.error(f"Invalid JSON at line {line_num}")
                except Exception as e:
                    stats['invalid_records'] += 1
                    logger.error(f"Error at line {line_num}: {e}")
        
        return stats
    
    def validate_training_data(self, file_path: Path) -> Dict:
        """Validate training corpus quality."""
        stats = {
            'total_records': 0,
            'valid_records': 0,
            'with_description': 0,
            'with_comments': 0,
            'text_lengths': [],
            'comment_counts': [],
            'issues_by_status': Counter(),
            'issues_by_type': Counter(),
            'issues_by_priority': Counter()
        }
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    stats['total_records'] += 1
                    
                    # Check required fields
                    if record.get('issue_key') and record.get('text'):
                        stats['valid_records'] += 1
                    
                    # Track content richness
                    if record.get('description'):
                        stats['with_description'] += 1
                    
                    if record.get('comments'):
                        stats['with_comments'] += 1
                        stats['comment_counts'].append(record['num_comments'])
                    
                    # Track text length
                    text_length = len(record.get('text', ''))
                    stats['text_lengths'].append(text_length)
                    
                    # Track metadata
                    stats['issues_by_status'][record.get('status', 'Unknown')] += 1
                    stats['issues_by_type'][record.get('issue_type', 'Unknown')] += 1
                    stats['issues_by_priority'][record.get('priority', 'Unknown')] += 1
                
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.error(f"Validation error: {e}")
        
        # Calculate statistics
        if stats['text_lengths']:
            stats['avg_text_length'] = statistics.mean(stats['text_lengths'])
            stats['median_text_length'] = statistics.median(stats['text_lengths'])
            stats['min_text_length'] = min(stats['text_lengths'])
            stats['max_text_length'] = max(stats['text_lengths'])
        
        if stats['comment_counts']:
            stats['avg_comments'] = statistics.mean(stats['comment_counts'])
            stats['median_comments'] = statistics.median(stats['comment_counts'])
        
        return stats


class DataAnalyzer:
    """Analyzes scraped data for insights."""
    
    @staticmethod
    def analyze_project_activity(file_path: Path) -> Dict:
        """Analyze temporal patterns in project activity."""
        activity_by_month = defaultdict(int)
        activity_by_year = defaultdict(int)
        resolution_times = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    
                    # Parse created date
                    created = record.get('created')
                    if created:
                        try:
                            dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                            activity_by_month[dt.strftime('%Y-%m')] += 1
                            activity_by_year[dt.year] += 1
                        except:
                            pass
                    
                    # Calculate resolution time
                    resolved = record.get('resolved')
                    if created and resolved:
                        try:
                            created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                            resolved_dt = datetime.fromisoformat(resolved.replace('Z', '+00:00'))
                            resolution_days = (resolved_dt - created_dt).days
                            if resolution_days >= 0:
                                resolution_times.append(resolution_days)
                        except:
                            pass
                
                except:
                    continue
        
        results = {
            'activity_by_month': dict(sorted(activity_by_month.items())),
            'activity_by_year': dict(sorted(activity_by_year.items())),
        }
        
        if resolution_times:
            results['resolution_stats'] = {
                'avg_days': statistics.mean(resolution_times),
                'median_days': statistics.median(resolution_times),
                'min_days': min(resolution_times),
                'max_days': max(resolution_times)
            }
        
        return results
    
    @staticmethod
    def analyze_contributors(file_path: Path) -> Dict:
        """Analyze contributor patterns."""
        reporters = Counter()
        assignees = Counter()
        commenters = Counter()
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    
                    reporter = record.get('reporter')
                    if reporter:
                        reporters[reporter] += 1
                    
                    assignee = record.get('assignee')
                    if assignee:
                        assignees[assignee] += 1
                    
                    for comment in record.get('comments', []):
                        author = comment.get('author')
                        if author:
                            commenters[author] += 1
                
                except:
                    continue
        
        return {
            'top_reporters': reporters.most_common(10),
            'top_assignees': assignees.most_common(10),
            'top_commenters': commenters.most_common(10),
            'total_unique_reporters': len(reporters),
            'total_unique_assignees': len(assignees),
            'total_unique_commenters': len(commenters)
        }
    
    @staticmethod
    def find_high_quality_issues(file_path: Path, min_length: int = 500) -> List[str]:
        """Find issues with rich content for sampling."""
        high_quality = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    
                    # Criteria for high quality
                    text_length = len(record.get('text', ''))
                    has_description = bool(record.get('description'))
                    num_comments = record.get('num_comments', 0)
                    
                    if (text_length >= min_length and 
                        has_description and 
                        num_comments >= 3):
                        high_quality.append({
                            'issue_key': record['issue_key'],
                            'text_length': text_length,
                            'num_comments': num_comments,
                            'summary': record.get('summary', '')[:100]
                        })
                
                except:
                    continue
        
        return sorted(high_quality, key=lambda x: x['text_length'], reverse=True)


class CorpusMerger:
    """Merge multiple project corpora into a single training set."""
    
    @staticmethod
    def merge_corpora(
        input_files: List[Path],
        output_file: Path,
        deduplicate: bool = True
    ):
        """Merge multiple JSONL files into one."""
        seen_ids = set()
        total_records = 0
        unique_records = 0
        
        with open(output_file, 'w', encoding='utf-8') as outf:
            for input_file in input_files:
                logger.info(f"Processing {input_file}")
                
                with open(input_file, 'r', encoding='utf-8') as inf:
                    for line in inf:
                        try:
                            record = json.loads(line)
                            total_records += 1
                            
                            record_id = record.get('id')
                            
                            if deduplicate:
                                if record_id in seen_ids:
                                    continue
                                seen_ids.add(record_id)
                            
                            outf.write(json.dumps(record, ensure_ascii=False) + '\n')
                            unique_records += 1
                        
                        except:
                            continue
        
        logger.info(f"Merged {unique_records} unique records from {total_records} total")
        return unique_records


class DataSampler:
    """Sample data for manual inspection and testing."""
    
    @staticmethod
    def sample_records(
        input_file: Path,
        output_file: Path,
        sample_size: int = 100,
        random_seed: int = 42
    ):
        """Sample random records from corpus."""
        import random
        random.seed(random_seed)
        
        # Load all records
        records = []
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except:
                    continue
        
        # Sample
        sample = random.sample(records, min(sample_size, len(records)))
        
        # Write sample
        with open(output_file, 'w', encoding='utf-8') as f:
            for record in sample:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        
        logger.info(f"Sampled {len(sample)} records to {output_file}")


def print_statistics_report(stats: Dict):
    """Print formatted statistics report."""
    print("\n" + "="*60)
    print("DATA QUALITY REPORT")
    print("="*60)
    
    print(f"\nTotal Records: {stats.get('total_records', 0)}")
    print(f"Valid Records: {stats.get('valid_records', 0)}")
    print(f"Invalid Records: {stats.get('invalid_records', 0)}")
    
    if stats.get('with_description') is not None:
        pct = (stats['with_description'] / stats['total_records'] * 100) if stats['total_records'] > 0 else 0
        print(f"With Description: {stats['with_description']} ({pct:.1f}%)")
    
    if stats.get('with_comments') is not None:
        pct = (stats['with_comments'] / stats['total_records'] * 100) if stats['total_records'] > 0 else 0
        print(f"With Comments: {stats['with_comments']} ({pct:.1f}%)")
    
    if stats.get('avg_text_length'):
        print(f"\nText Length Statistics:")
        print(f"  Average: {stats['avg_text_length']:.0f} chars")
        print(f"  Median: {stats['median_text_length']:.0f} chars")
        print(f"  Range: {stats['min_text_length']:.0f} - {stats['max_text_length']:.0f} chars")
    
    if stats.get('avg_comments'):
        print(f"\nComment Statistics:")
        print(f"  Average: {stats['avg_comments']:.1f} comments")
        print(f"  Median: {stats['median_comments']:.0f} comments")
    
    if stats.get('issues_by_status'):
        print(f"\nTop Issue Statuses:")
        for status, count in stats['issues_by_status'].most_common(5):
            print(f"  {status}: {count}")
    
    if stats.get('issues_by_type'):
        print(f"\nTop Issue Types:")
        for itype, count in stats['issues_by_type'].most_common(5):
            print(f"  {itype}: {count}")
    
    print("\n" + "="*60 + "\n")


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Validate training data
    validator = DataValidator()
    
    for project in ['KAFKA', 'SPARK', 'HADOOP']:
        file_path = Path(f"processed/{project}_training.jsonl")
        
        if file_path.exists():
            print(f"\nValidating {project}...")
            stats = validator.validate_training_data(file_path)
            print_statistics_report(stats)
            
            # Analyze activity
            analyzer = DataAnalyzer()
            activity = analyzer.analyze_project_activity(file_path)
            
            print(f"\nActivity Analysis for {project}:")
            print(f"Years with activity: {list(activity['activity_by_year'].keys())}")
            
            if 'resolution_stats' in activity:
                print(f"Average resolution time: {activity['resolution_stats']['avg_days']:.1f} days")
            
            # Find high-quality samples
            high_quality = analyzer.find_high_quality_issues(file_path)
            print(f"\nHigh-quality issues found: {len(high_quality)}")
            if high_quality:
                print(f"Top issue: {high_quality[0]['issue_key']} ({high_quality[0]['text_length']} chars)")
    
    # Merge all corpora
    print("\nMerging corpora...")
    input_files = [
        Path(f"processed/{project}_training.jsonl")
        for project in ['KAFKA', 'SPARK', 'HADOOP']
        if Path(f"processed/{project}_training.jsonl").exists()
    ]
    
    if input_files:
        merger = CorpusMerger()
        output_file = Path("processed/combined_training.jsonl")
        merger.merge_corpora(input_files, output_file, deduplicate=True)
        
        # Sample for inspection
        sampler = DataSampler()
        sampler.sample_records(
            output_file,
            Path("processed/sample_100.jsonl"),
            sample_size=100
        )