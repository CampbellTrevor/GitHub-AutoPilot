#!/usr/bin/env python3
"""
Example: How to use GitHub AutoPilot programmatically.

This demonstrates how to use the refactored modules directly in your own code.
"""

from config import REPOSITORY, BASE_BRANCH
from prompt_builder import build_improvement_prompt
from metrics import metrics
from github_api import split_owner_repo

def example_prompt_generation():
    """Example: Generate an improvement prompt."""
    print("=" * 60)
    print("Example 1: Generate Improvement Prompt")
    print("=" * 60)
    
    owner, repo = split_owner_repo(REPOSITORY)
    print(f"Repository: {owner}/{repo}")
    print(f"Base Branch: {BASE_BRANCH}")
    
    prompt = build_improvement_prompt(REPOSITORY, BASE_BRANCH)
    print(f"\nGenerated prompt ({len(prompt)} characters):")
    print("-" * 60)
    print(prompt[:500] + "...")
    print("-" * 60)


def example_metrics_tracking():
    """Example: Track metrics across cycles."""
    print("\n" + "=" * 60)
    print("Example 2: Metrics Tracking")
    print("=" * 60)
    
    # Start tracking
    metrics.start_cycle()
    
    # Simulate some activity
    metrics.record_pr_created(101)
    metrics.record_pr_merged()
    
    metrics.record_pr_created(102)
    metrics.record_checks_failed()
    metrics.record_pr_failed()
    
    # Get summary
    summary = metrics.get_summary()
    print(f"\nMetrics Summary:")
    print(f"  PRs Created: {summary['prs_created']}")
    print(f"  PRs Merged: {summary['prs_merged']}")
    print(f"  PRs Failed: {summary['prs_failed']}")
    print(f"  PR Numbers: {summary['pr_numbers']}")


def example_repository_parsing():
    """Example: Parse repository strings."""
    print("\n" + "=" * 60)
    print("Example 3: Repository String Parsing")
    print("=" * 60)
    
    repos = [
        "octocat/Hello-World",
        "CampbellTrevor/ArbitraryML",
        "owner/repo-name-with-dashes"
    ]
    
    for repo in repos:
        owner, name = split_owner_repo(repo)
        print(f"  {repo:40} -> owner: {owner:20} repo: {name}")


if __name__ == "__main__":
    print("\n🤖 GitHub AutoPilot - Usage Examples\n")
    
    example_prompt_generation()
    example_metrics_tracking()
    example_repository_parsing()
    
    print("\n" + "=" * 60)
    print("✅ Examples completed!")
    print("=" * 60)
    print("\nTo run the full automation loop, use:")
    print("  python main.py")
