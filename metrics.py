"""Metrics tracking module.

This module provides simple metrics tracking for the continuous improvement loop.
"""

import time
from typing import Dict, Any


class Metrics:
    """Track metrics for the continuous improvement loop."""
    
    def __init__(self):
        self.total_prs_created = 0
        self.total_prs_merged = 0
        self.total_prs_failed = 0
        self.total_checks_passed = 0
        self.total_checks_failed = 0
        self.cycle_start_time = None
        self.pr_numbers = []
    
    def start_cycle(self):
        """Mark the start of a new cycle."""
        self.cycle_start_time = time.time()
    
    def record_pr_created(self, pr_number: int):
        """Record that a PR was created."""
        self.total_prs_created += 1
        self.pr_numbers.append(pr_number)
    
    def record_pr_merged(self):
        """Record that a PR was merged."""
        self.total_prs_merged += 1
    
    def record_pr_failed(self):
        """Record that a PR failed."""
        self.total_prs_failed += 1
    
    def record_checks_passed(self):
        """Record that checks passed."""
        self.total_checks_passed += 1
    
    def record_checks_failed(self):
        """Record that checks failed."""
        self.total_checks_failed += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all metrics."""
        total_time = time.time() - self.cycle_start_time if self.cycle_start_time else 0
        
        return {
            "total_runtime_seconds": int(total_time),
            "total_runtime_minutes": int(total_time / 60),
            "prs_created": self.total_prs_created,
            "prs_merged": self.total_prs_merged,
            "prs_failed": self.total_prs_failed,
            "checks_passed": self.total_checks_passed,
            "checks_failed": self.total_checks_failed,
            "pr_numbers": self.pr_numbers,
        }


# Global metrics instance
metrics = Metrics()
