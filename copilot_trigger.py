"""Copilot CLI integration module.

This module handles triggering the GitHub Copilot coding agent via gh CLI.
"""

import os
import re
import subprocess
from typing import Optional

# Find and use gh CLI executable
def find_gh_executable() -> Optional[str]:
    """Find gh.exe, checking PATH and common install locations."""
    # Try PATH first
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return "gh"
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    
    # Try common install locations on Windows
    common_paths = [
        r"C:\Program Files\GitHub CLI\gh.exe",
        r"C:\Program Files (x86)\GitHub CLI\gh.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe"),
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            return path
    
    return None


def trigger_copilot_via_gh_cli(repository: str, base_branch: str, prompt: str) -> Optional[int]:
    """Trigger Copilot coding agent via gh CLI.
    
    Returns the PR number if successful, None otherwise.
    """
    print(f"Triggering Copilot via gh CLI for branch {base_branch}...")
    
    # Find gh executable
    gh_cmd = find_gh_executable()
    if not gh_cmd:
        print("ERROR: gh CLI not found. Please install GitHub CLI: https://cli.github.com/")
        print("After installing, restart VS Code completely.")
        return None
    
    print(f"Using gh CLI: {gh_cmd}")
    
    # Check if gh is authenticated with stored credentials (not just env var)
    print("Checking gh CLI authentication...")
    auth_check_result = subprocess.run(
        [gh_cmd, "auth", "status"],
        capture_output=True,
        text=True,
        timeout=10
    )
    
    if auth_check_result.returncode != 0:
        print("✗ gh CLI is not authenticated")
        print("\nPlease authenticate gh CLI by running:")
        print("  gh auth login")
        print("\nThen re-run this script.")
        return None
    
    # Check if using environment variable (which won't work for agent-task)
    auth_output = auth_check_result.stdout + auth_check_result.stderr
    if "GITHUB_TOKEN" in auth_output or "environment variable" in auth_output.lower():
        print("✗ gh CLI is authenticated via environment variable")
        print("  agent-task command requires stored credentials, not environment variables")
        print("\nPlease authenticate gh CLI with stored credentials:")
        print("  gh auth login")
        print("\nThen re-run this script.")
        return None
    
    print("✓ gh CLI is authenticated with stored credentials")
    
    # Set environment for gh CLI
    # Use clean environment without GITHUB_TOKEN/GH_TOKEN to let gh use stored credentials
    env = os.environ.copy()
    # Remove tokens from environment - gh will use stored credentials from keyring
    env.pop("GITHUB_TOKEN", None)
    env.pop("GH_TOKEN", None)
    
    # Build the gh agent-task command
    cmd = [
        gh_cmd,
        "agent-task",
        "create",
        prompt,
        "--repo", repository,
        "--base", base_branch
    ]
    
    try:
        print(f"Running: gh agent-task create --repo {repository} --base {base_branch} <prompt>")
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            check=False
        )
        
        if result.returncode != 0:
            error_msg = result.stderr
            print(f"gh CLI error: {error_msg}")
            return None
        
        # Parse output - gh agent-task returns a job ID, not a PR number immediately
        output = result.stdout
        print(f"gh CLI output: {output}")
        
        # Check if job was queued successfully
        if "job" in output.lower() and "queued" in output.lower():
            print("✓ Copilot job queued successfully")
            print("Waiting for Copilot to create PR...")
            
            # The PR will be created shortly, we need to poll for it
            # Return a sentinel value to indicate we need to poll
            return -1
        
        # Look for PR URL or number in output (in case format changes)
        pr_match = re.search(r'pull/(\d+)', output)
        if pr_match:
            pr_number = int(pr_match.group(1))
            print(f"✓ Copilot triggered, PR #{pr_number}")
            return pr_number
        
        # Alternative: look for just the PR number
        pr_match = re.search(r'#(\d+)', output)
        if pr_match:
            pr_number = int(pr_match.group(1))
            print(f"✓ Copilot triggered, PR #{pr_number}")
            return pr_number
        
        print("⚠️  Unexpected output format from gh CLI")
        return None
        
    except subprocess.TimeoutExpired:
        print("gh CLI command timed out")
        return None
    except FileNotFoundError:
        print("ERROR: gh CLI not found. Please install GitHub CLI: https://cli.github.com/")
        return None
    except Exception as e:
        print(f"Error running gh CLI: {e}")
        return None
