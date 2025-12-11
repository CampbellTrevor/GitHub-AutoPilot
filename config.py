"""Configuration module for GitHub AutoPilot.

This module centralizes all configuration values and environment variables
for the continuous improvement automation system.
"""

import os

# GitHub API Configuration
GITHUB_API_URL = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "token")  # PAT or GitHub Actions token

# Repository Configuration
REPOSITORY = os.getenv("TARGET_REPOSITORY", "CampbellTrevor/ArbitraryML")  # e.g., "owner/repo"
BASE_BRANCH = os.getenv("BASE_BRANCH", "Iterate")

# Polling and Timeout Configuration
PR_POLL_INTERVAL_SECONDS = int(os.getenv("PR_POLL_INTERVAL_SECONDS", "60"))
MAX_WAIT_FOR_PR_SECONDS = int(os.getenv("MAX_WAIT_FOR_PR_SECONDS", "3600"))  # 1 hour
PR_READY_TIMEOUT_SECONDS = int(os.getenv("PR_READY_TIMEOUT_SECONDS", "1800"))  # 30 minutes
PR_CHECK_TIMEOUT_SECONDS = int(os.getenv("PR_CHECK_TIMEOUT_SECONDS", "600"))  # 10 minutes

# Merge Configuration
AUTO_MERGE_PRS = os.getenv("AUTO_MERGE_PRS", "true").lower() in ("true", "1", "yes")
MERGE_METHOD = os.getenv("MERGE_METHOD", "squash")  # squash, merge, or rebase

# Loop Control Configuration
DELAY_BETWEEN_CYCLES_SECONDS = int(os.getenv("DELAY_BETWEEN_CYCLES_SECONDS", "10"))
MAX_CYCLES = int(os.getenv("MAX_CYCLES", "0"))  # 0 = unlimited
MAX_CONSECUTIVE_FAILURES = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "3"))

# Validate required configuration
if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN environment variable is required")
