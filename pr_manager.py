"""Pull request management module.

This module handles all PR-related operations including creation, merging,
checking status, and managing PR lifecycle.
"""

import re
import time
import logging
import requests
from typing import Dict, Any, Optional, List

from config import (
    GITHUB_API_URL, BASE_BRANCH, PR_READY_TIMEOUT_SECONDS, 
    PR_CHECK_TIMEOUT_SECONDS, MERGE_METHOD
)
from github_api import session, split_owner_repo, graphql_query
from issue_manager import close_issue

logger = logging.getLogger(__name__)


def get_issue_number_from_pr(repository: str, pr_number: int) -> Optional[int]:
    """Extract the issue number that a PR is associated with.
    
    Checks PR body and branch name for issue references.
    Returns issue number if found, None otherwise.
    """
    owner, repo = split_owner_repo(repository)
    
    pr_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
    response = session.get(pr_url, timeout=60)
    response.raise_for_status()
    pr_data = response.json()
    
    pr_body = (pr_data.get("body") or "").lower()
    pr_branch = (pr_data.get("head", {}).get("ref") or "").lower()
    
    # Try to extract from branch name (e.g., copilot/issue-123-...)
    branch_match = re.search(r'issue[_-](\d+)', pr_branch)
    if branch_match:
        return int(branch_match.group(1))
    
    # Try to extract from PR body (e.g., #123, Fixes #123, Closes #123)
    body_match = re.search(r'(?:fixes|closes|resolves)?\s*#(\d+)', pr_body)
    if body_match:
        return int(body_match.group(1))
    
    return None


def get_pull_requests_for_issue(repository: str, issue_number: int) -> List[Dict[str, Any]]:
    """Find pull requests that reference a specific issue."""
    owner, repo = split_owner_repo(repository)
    
    # Search for PRs that mention the issue
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls"
    params = {
        "state": "all",
        "sort": "created",
        "direction": "desc",
        "per_page": 100,
    }
    
    response = session.get(url, params=params, timeout=60)
    response.raise_for_status()
    all_prs = response.json()
    
    # Filter PRs that reference this issue
    related_prs = []
    for pr in all_prs:
        pr_body = (pr.get("body") or "").lower()
        pr_branch = (pr.get("head", {}).get("ref") or "").lower()
        
        if (f"#{issue_number}" in pr_body or 
            f"issue-{issue_number}" in pr_branch or
            f"fixes #{issue_number}" in pr_body or
            f"closes #{issue_number}" in pr_body):
            related_prs.append(pr)
    
    return related_prs


def close_pull_request(repository: str, pr_number: int, comment: Optional[str] = None) -> bool:
    """Close a pull request without merging.
    
    Optionally add a comment before closing.
    Returns True if successful, False otherwise.
    """
    owner, repo = split_owner_repo(repository)
    
    try:
        # Add comment if provided
        if comment:
            comment_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/issues/{pr_number}/comments"
            comment_payload = {"body": comment}
            comment_response = session.post(comment_url, json=comment_payload, timeout=60)
            comment_response.raise_for_status()
            print(f"[PR #{pr_number}] Added closing comment")
        
        # Close the PR
        url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
        payload = {"state": "closed"}
        response = session.patch(url, json=payload, timeout=60)
        response.raise_for_status()
        print(f"[PR #{pr_number}] ✓ Closed without merging")
        return True
    except requests.HTTPError as e:
        print(f"[PR #{pr_number}] Failed to close: {e}")
        if e.response is not None:
            print(f"[PR #{pr_number}] Response: {e.response.text}")
        return False


def ensure_pr_base_branch(repository: str, pr_number: int, expected_base: str = BASE_BRANCH) -> bool:
    """Ensure PR is targeting the correct base branch.
    
    If not, update it via API.
    Returns True if base is correct or successfully updated, False on error.
    """
    owner, repo = split_owner_repo(repository)
    
    # Get PR details
    pr_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
    pr_response = session.get(pr_url, timeout=60)
    pr_response.raise_for_status()
    pr_data = pr_response.json()
    
    current_base = pr_data.get("base", {}).get("ref")
    
    if current_base == expected_base:
        print(f"[PR #{pr_number}] Base branch is correct: {current_base}")
        return True
    
    print(f"[PR #{pr_number}] Base branch is {current_base}, changing to {expected_base}...")
    
    # Update the base branch
    update_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
    payload = {"base": expected_base}
    
    try:
        update_response = session.patch(update_url, json=payload, timeout=60)
        update_response.raise_for_status()
        print(f"[PR #{pr_number}] ✓ Base branch updated to {expected_base}")
        
        # If we had to change the base, close the PR as it will have conflicts
        print(f"[PR #{pr_number}] ⚠️  Had to change base from {current_base} to {expected_base}")
        print(f"[PR #{pr_number}] This means Copilot branched from {current_base} instead of {expected_base}")
        print(f"[PR #{pr_number}] Conflicts are inevitable - closing this PR and starting fresh")
        
        close_pull_request(repository, pr_number,
                         f"This PR was targeting `{current_base}` instead of `{expected_base}`. "
                         f"Copilot branched from the wrong base, which will cause merge conflicts. "
                         f"Closing this PR - a new cycle will be started with clearer instructions.")
        
        # Close the associated issue
        issue_num = get_issue_number_from_pr(repository, pr_number)
        if issue_num:
            close_issue(repository, issue_num,
                       f"PR #{pr_number} was targeting wrong base branch. "
                       "Closing this issue to restart cycle.")
        
        return False
    except requests.HTTPError as e:
        print(f"[PR #{pr_number}] Failed to update base branch: {e}")
        if e.response is not None:
            print(f"[PR #{pr_number}] Response: {e.response.text}")
        return False


def mark_pr_ready_for_review(repository: str, pr_number: int) -> bool:
    """Mark a draft PR as ready for review using GraphQL API.
    
    Returns True if successful or already ready, False on error.
    """
    owner, repo = split_owner_repo(repository)
    
    # First check if it's a draft
    pr_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
    pr_response = session.get(pr_url, timeout=60)
    pr_response.raise_for_status()
    pr_data = pr_response.json()
    
    is_draft = pr_data.get("draft", False)
    
    if not is_draft:
        print(f"[PR #{pr_number}] Already marked as ready for review")
        return True
    
    # Get the PR node ID for GraphQL
    pr_node_id = pr_data.get("node_id")
    
    if not pr_node_id:
        print(f"[PR #{pr_number}] Could not get PR node ID")
        return False
    
    # Use GraphQL to mark as ready for review
    mutation = """
    mutation($prId: ID!) {
      markPullRequestReadyForReview(input: {pullRequestId: $prId}) {
        pullRequest {
          id
          number
          isDraft
        }
      }
    }
    """
    
    variables = {"prId": pr_node_id}
    
    try:
        result = graphql_query(mutation, variables)
        
        if result.get("data", {}).get("markPullRequestReadyForReview"):
            print(f"[PR #{pr_number}] ✓ Marked as ready for review")
            return True
        else:
            errors = result.get("errors", [])
            print(f"[PR #{pr_number}] Failed to mark as ready: {errors}")
            return False
    except Exception as e:
        print(f"[PR #{pr_number}] Error marking as ready: {e}")
        return False


def merge_pull_request(repository: str, pr_number: int, merge_method: str = MERGE_METHOD) -> bool:
    """Merge a pull request automatically.
    
    Returns True if successful, False otherwise.
    """
    owner, repo = split_owner_repo(repository)
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}/merge"
    
    # Check if PR is mergeable first
    pr_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
    pr_response = session.get(pr_url, timeout=60)
    pr_response.raise_for_status()
    pr_data = pr_response.json()
    
    mergeable = pr_data.get("mergeable")
    mergeable_state = pr_data.get("mergeable_state")
    
    print(f"[PR #{pr_number}] Mergeable: {mergeable}, State: {mergeable_state}")
    
    if mergeable is False:
        print(f"[PR #{pr_number}] Cannot merge - has conflicts or failing checks")
        return False
    
    # Attempt to merge
    payload = {
        "commit_title": f"Merge PR #{pr_number} from Copilot improvement cycle",
        "merge_method": merge_method,
    }
    
    try:
        response = session.put(url, json=payload, timeout=60)
        response.raise_for_status()
        print(f"[PR #{pr_number}] ✓ Successfully merged")
        return True
    except requests.HTTPError as e:
        print(f"[PR #{pr_number}] Failed to merge: {e}")
        if e.response is not None:
            print(f"[PR #{pr_number}] Response: {e.response.text}")
        return False


def wait_for_pr_ready(repository: str, pr_number: int, timeout: int = PR_READY_TIMEOUT_SECONDS) -> bool:
    """Wait for PR to be done.
    
    A PR is considered done when:
    1. The title no longer contains [WIP]
    2. Copilot has requested a reviewer
    
    Returns True if PR is done, False on timeout.
    """
    owner, repo = split_owner_repo(repository)
    start_time = time.time()
    
    print(f"[PR #{pr_number}] Waiting for Copilot to finish work...")
    
    while (time.time() - start_time) < timeout:
        try:
            # Get PR details
            pr_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
            pr_response = session.get(pr_url, timeout=60)
            pr_response.raise_for_status()
            pr_data = pr_response.json()
            
            title = pr_data.get("title", "")
            has_wip = "[WIP]" in title or "[wip]" in title.lower()
            
            # Get review requests
            reviewers_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers"
            reviewers_response = session.get(reviewers_url, timeout=60)
            reviewers_response.raise_for_status()
            review_data = reviewers_response.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning(f"[PR #{pr_number}] Network error while checking status: {e}")
            logger.warning(f"[PR #{pr_number}] Retrying in 10 seconds...")
            time.sleep(10)
            continue
        except requests.HTTPError as e:
            if e.response and e.response.status_code >= 500:
                logger.warning(f"[PR #{pr_number}] Server error {e.response.status_code}, retrying in 10 seconds...")
                time.sleep(10)
                continue
            else:
                raise
        
        requested_reviewers = review_data.get("users", [])
        reviewer_logins = [r.get("login") for r in requested_reviewers]
        has_reviewers = len(reviewer_logins) > 0
        
        # PR is done when no WIP and reviewers requested
        if not has_wip and has_reviewers:
            print(f"[PR #{pr_number}] ✓ Copilot finished!")
            print(f"[PR #{pr_number}]   Title: {title}")
            print(f"[PR #{pr_number}]   Reviewers: {', '.join(reviewer_logins)}")
            return True
        
        # Show what we're waiting for
        waiting_for = []
        if has_wip:
            waiting_for.append("WIP removal")
        if not has_reviewers:
            waiting_for.append("reviewer assignment")
        
        elapsed = int(time.time() - start_time)
        print(f"[PR #{pr_number}] Waiting for: {', '.join(waiting_for)} ({elapsed}s elapsed)")
        time.sleep(30)
    
    print(f"[PR #{pr_number}] Timeout waiting for Copilot to finish")
    return False


def get_pr_check_status(repository: str, pr_number: int) -> Dict[str, Any]:
    """Get detailed status of PR checks/CI runs."""
    owner, repo = split_owner_repo(repository)
    
    # Get the PR to find the head SHA
    pr_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
    pr_response = session.get(pr_url, timeout=60)
    pr_response.raise_for_status()
    pr_data = pr_response.json()
    
    head_sha = pr_data.get("head", {}).get("sha")
    
    if not head_sha:
        return {"checks": [], "total": 0, "passed": 0, "failed": 0, "pending": 0}
    
    # Get check runs for this commit
    checks_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/commits/{head_sha}/check-runs"
    checks_response = session.get(checks_url, timeout=60)
    checks_response.raise_for_status()
    checks_data = checks_response.json()
    
    check_runs = checks_data.get("check_runs", [])
    
    passed = sum(1 for c in check_runs if c.get("conclusion") == "success")
    failed = sum(1 for c in check_runs if c.get("conclusion") in ["failure", "cancelled", "timed_out"])
    pending = sum(1 for c in check_runs if c.get("status") != "completed")
    
    return {
        "checks": check_runs,
        "total": len(check_runs),
        "passed": passed,
        "failed": failed,
        "pending": pending
    }


def wait_for_pr_checks(repository: str, pr_number: int, timeout: int = PR_CHECK_TIMEOUT_SECONDS) -> bool:
    """Wait for PR checks to complete.
    
    Returns True if all checks pass, False otherwise.
    """
    owner, repo = split_owner_repo(repository)
    start_time = time.time()
    
    print(f"[PR #{pr_number}] Waiting for checks to complete...")
    
    while (time.time() - start_time) < timeout:
        try:
            pr_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
            response = session.get(pr_url, timeout=60)
            response.raise_for_status()
            pr_data = response.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning(f"[PR #{pr_number}] Network error while checking status: {e}")
            logger.warning(f"[PR #{pr_number}] Retrying in 10 seconds...")
            time.sleep(10)
            continue
        except requests.HTTPError as e:
            if e.response and e.response.status_code >= 500:
                logger.warning(f"[PR #{pr_number}] Server error {e.response.status_code}, retrying in 10 seconds...")
                time.sleep(10)
                continue
            else:
                raise
        
        mergeable_state = pr_data.get("mergeable_state")
        
        # Get detailed check status
        try:
            check_status = get_pr_check_status(repository, pr_number)
            if check_status["total"] > 0:
                print(f"[PR #{pr_number}] Checks: {check_status['passed']}/{check_status['total']} passed, "
                      f"{check_status['pending']} pending, {check_status['failed']} failed")
                
                # Show which checks are pending or failed
                for check in check_status["checks"]:
                    name = check.get("name")
                    status = check.get("status")
                    conclusion = check.get("conclusion")
                    
                    if status != "completed":
                        print(f"  ⏳ {name}: {status}")
                    elif conclusion != "success":
                        print(f"  ✗ {name}: {conclusion}")
        except Exception as e:
            logger.debug(f"Could not fetch check details: {e}")
        
        # Possible states: clean, dirty, unstable, blocked, unknown, draft
        if mergeable_state == "clean":
            print(f"[PR #{pr_number}] ✓ All checks passed (mergeable_state: clean)")
            return True
        elif mergeable_state in ["dirty", "unstable"]:
            print(f"[PR #{pr_number}] ✗ Checks failed or PR has issues: {mergeable_state}")
            return False
        elif mergeable_state == "blocked":
            print(f"[PR #{pr_number}] Blocked - required checks not complete yet")
        
        elapsed = int(time.time() - start_time)
        print(f"[PR #{pr_number}] Mergeable state: {mergeable_state} - {elapsed}s elapsed")
        time.sleep(30)
    
    print(f"[PR #{pr_number}] Timeout waiting for checks")
    return False


def get_open_copilot_prs(repository: str) -> List[Dict[str, Any]]:
    """Get all open pull requests created by Copilot.
    
    Returns list of PR objects.
    """
    owner, repo = split_owner_repo(repository)
    
    # Get all open PRs
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls"
    params = {
        "state": "open",
        "sort": "created",
        "direction": "desc",
        "per_page": 100,
    }
    
    try:
        response = session.get(url, params=params, timeout=60)
        response.raise_for_status()
        all_prs = response.json()
    except (requests.ConnectionError, requests.Timeout) as e:
        logger.warning(f"Network error fetching open PRs: {e}")
        logger.warning("Retrying in 5 seconds...")
        time.sleep(5)
        response = session.get(url, params=params, timeout=60)
        response.raise_for_status()
        all_prs = response.json()
    
    # Filter for Copilot PRs (created by copilot-swe-agent or has copilot branch pattern)
    copilot_prs = []
    for pr in all_prs:
        user_login = pr.get("user", {}).get("login", "")
        branch_name = pr.get("head", {}).get("ref", "")
        
        # Check if created by Copilot or has copilot branch pattern
        if user_login == "copilot-swe-agent" or branch_name.startswith("copilot/"):
            copilot_prs.append(pr)
    
    return copilot_prs
