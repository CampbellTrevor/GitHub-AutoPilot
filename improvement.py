import os
import sys
import time
import signal
import logging
import requests
import subprocess
import json
import re
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime

GITHUB_API_URL = "https://api.github.com"

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('improvement.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
_shutdown_requested = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    logger.info("Shutdown signal received. Finishing current cycle...")
    _shutdown_requested = True

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# -----------------------------
# Configuration
# -----------------------------
GITHUB_TOKEN = "token"  # PAT or GitHub Actions token
REPOSITORY = os.getenv("TARGET_REPOSITORY", "CampbellTrevor/ArbitraryML")  # e.g., "CampbellTrevor/my-project"
BASE_BRANCH = os.getenv("BASE_BRANCH", "Iterate")

# How often to poll for PR creation (seconds)
PR_POLL_INTERVAL_SECONDS = int(os.getenv("PR_POLL_INTERVAL_SECONDS", "60"))

# Maximum time to wait for Copilot to create a PR (seconds)
MAX_WAIT_FOR_PR_SECONDS = int(os.getenv("MAX_WAIT_FOR_PR_SECONDS", "3600"))  # 1 hour

# Whether to automatically merge PRs (True) or leave them for manual review (False)
AUTO_MERGE_PRS = os.getenv("AUTO_MERGE_PRS", "true").lower() in ("true", "1", "yes")

# Maximum time to wait for PR to be ready (not draft) before merging (seconds)
PR_READY_TIMEOUT_SECONDS = int(os.getenv("PR_READY_TIMEOUT_SECONDS", "1800"))  # 30 minutes

# Maximum time to wait for PR checks to complete before merging (seconds)
PR_CHECK_TIMEOUT_SECONDS = int(os.getenv("PR_CHECK_TIMEOUT_SECONDS", "600"))  # 10 minutes

# Merge method: squash, merge, or rebase
MERGE_METHOD = os.getenv("MERGE_METHOD", "squash")

# Delay between improvement cycles (seconds) - prevents spamming
DELAY_BETWEEN_CYCLES_SECONDS = int(os.getenv("DELAY_BETWEEN_CYCLES_SECONDS", "10"))  # 10 seconds

# Maximum number of cycles to run (0 = unlimited)
MAX_CYCLES = int(os.getenv("MAX_CYCLES", "0"))

# Maximum consecutive failures before stopping
MAX_CONSECUTIVE_FAILURES = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "3"))


if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN environment variable is required")

session = requests.Session()
session.headers.update(
    {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
)

# Cache for Copilot bot ID
_copilot_bot_id: Optional[str] = None

# Metrics tracking
_metrics = {
    "total_prs_created": 0,
    "total_prs_merged": 0,
    "total_prs_failed": 0,
    "total_checks_passed": 0,
    "total_checks_failed": 0,
    "cycle_start_time": None,
    "pr_numbers": [],
}


# -----------------------------
# Helper functions
# -----------------------------
def retry_on_failure(func, max_retries: int = 3, delay: int = 5):
    """
    Retry a function on failure with exponential backoff.
    """
    for attempt in range(max_retries):
        try:
            return func()
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                raise
            wait_time = delay * (2 ** attempt)
            logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)


def check_rate_limit() -> None:
    """
    Check GitHub API rate limit and wait if necessary.
    """
    try:
        response = session.get(f"{GITHUB_API_URL}/rate_limit", timeout=10)
        response.raise_for_status()
        data = response.json()
        
        core_remaining = data.get("resources", {}).get("core", {}).get("remaining", 0)
        core_reset = data.get("resources", {}).get("core", {}).get("reset", 0)
        
        if core_remaining < 100:  # Low on rate limit
            reset_time = datetime.fromtimestamp(core_reset)
            wait_seconds = (reset_time - datetime.now()).total_seconds()
            if wait_seconds > 0:
                logger.warning(f"Rate limit low ({core_remaining} remaining). Waiting {int(wait_seconds)}s until reset...")
                time.sleep(min(wait_seconds + 10, 3600))  # Wait but cap at 1 hour
    except Exception as e:
        logger.warning(f"Could not check rate limit: {e}")


def graphql_query(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute a GraphQL query against GitHub API.
    """
    check_rate_limit()
    
    url = "https://api.github.com/graphql"
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    response = session.post(url, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def split_owner_repo(repo: str) -> Tuple[str, str]:
    if "/" not in repo:
        raise ValueError(f"Invalid repository: {repo}. Expected 'owner/repo'.")
    owner, name = repo.split("/", 1)
    return owner, name


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
    """
    Trigger Copilot coding agent via gh CLI.
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


def get_copilot_bot_id(repository: str) -> str:
    """
    Get the Copilot bot ID for assigning issues.
    Uses the login 'copilot-swe-agent' as per GitHub documentation.
    """
    global _copilot_bot_id
    
    if _copilot_bot_id:
        return _copilot_bot_id
    
    owner, repo = split_owner_repo(repository)
    
    query = """
    query($owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        suggestedActors(capabilities: [CAN_BE_ASSIGNED], first: 100) {
          nodes {
            login
            __typename
            ... on Bot {
              id
            }
            ... on User {
              id
            }
          }
        }
      }
    }
    """
    
    variables = {"owner": owner, "repo": repo}
    result = graphql_query(query, variables)
    
    # Find copilot-swe-agent in the suggested actors
    actors = result.get("data", {}).get("repository", {}).get("suggestedActors", {}).get("nodes", [])
    
    for actor in actors:
        if actor.get("login") == "copilot-swe-agent":
            _copilot_bot_id = actor.get("id")
            return _copilot_bot_id
    
    raise RuntimeError(
        f"Copilot coding agent not found in repository {repository}. "
        "Please ensure Copilot coding agent is enabled for this repository."
    )


def get_repository_id(repository: str) -> str:
    """
    Get the GraphQL global ID for a repository.
    """
    owner, repo = split_owner_repo(repository)
    
    query = """
    query($owner: String!, $repo: String!) {
      repository(owner: $owner, name: $repo) {
        id
      }
    }
    """
    
    variables = {"owner": owner, "repo": repo}
    result = graphql_query(query, variables)
    
    repo_id = result.get("data", {}).get("repository", {}).get("id")
    if not repo_id:
        raise RuntimeError(f"Could not fetch repository ID for {repository}")
    
    return repo_id


def create_issue_for_copilot(
    repository: str,
    title: str,
    body: str,
    labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Create a GitHub issue and assign it to Copilot coding agent using GraphQL API.
    
    Returns the created issue object.
    """
    # Get the IDs needed for the GraphQL mutation
    repo_id = get_repository_id(repository)
    bot_id = get_copilot_bot_id(repository)
    
    # Create the issue and assign to Copilot in one mutation
    mutation = """
    mutation($repoId: ID!, $title: String!, $body: String!, $botId: ID!) {
      createIssue(input: {
        repositoryId: $repoId,
        title: $title,
        body: $body,
        assigneeIds: [$botId]
      }) {
        issue {
          id
          number
          title
          url
          assignees(first: 10) {
            nodes {
              login
            }
          }
        }
      }
    }
    """
    
    variables = {
        "repoId": repo_id,
        "title": title,
        "body": body,
        "botId": bot_id,
    }
    
    result = graphql_query(mutation, variables)
    
    issue_data = result.get("data", {}).get("createIssue", {}).get("issue", {})
    if not issue_data:
        errors = result.get("errors", [])
        raise RuntimeError(f"Failed to create issue: {errors}")
    
    # Convert GraphQL response to REST API format for compatibility
    return {
        "number": issue_data.get("number"),
        "title": issue_data.get("title"),
        "html_url": issue_data.get("url"),
        "assignees": issue_data.get("assignees", {}).get("nodes", []),
    }


def get_issue(repository: str, issue_number: int) -> Dict[str, Any]:
    """
    Fetch a GitHub issue by number.
    """
    owner, repo = split_owner_repo(repository)
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/issues/{issue_number}"
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def close_pull_request(repository: str, pr_number: int, comment: Optional[str] = None) -> bool:
    """
    Close a pull request without merging.
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


def close_issue(repository: str, issue_number: int, comment: Optional[str] = None) -> bool:
    """
    Close a GitHub issue.
    Optionally add a comment before closing.
    Returns True if successful, False otherwise.
    """
    owner, repo = split_owner_repo(repository)
    
    try:
        # Add comment if provided
        if comment:
            comment_url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/issues/{issue_number}/comments"
            comment_payload = {"body": comment}
            comment_response = session.post(comment_url, json=comment_payload, timeout=60)
            comment_response.raise_for_status()
            print(f"[Issue #{issue_number}] Added closing comment")
        
        # Close the issue
        url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/issues/{issue_number}"
        payload = {"state": "closed"}
        response = session.patch(url, json=payload, timeout=60)
        response.raise_for_status()
        print(f"[Issue #{issue_number}] ✓ Closed successfully")
        return True
    except requests.HTTPError as e:
        print(f"[Issue #{issue_number}] Failed to close: {e}")
        if e.response is not None:
            print(f"[Issue #{issue_number}] Response: {e.response.text}")
        return False


def get_issue_number_from_pr(repository: str, pr_number: int) -> Optional[int]:
    """
    Extract the issue number that a PR is associated with.
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
    import re
    branch_match = re.search(r'issue[_-](\d+)', pr_branch)
    if branch_match:
        return int(branch_match.group(1))
    
    # Try to extract from PR body (e.g., #123, Fixes #123, Closes #123)
    body_match = re.search(r'(?:fixes|closes|resolves)?\s*#(\d+)', pr_body)
    if body_match:
        return int(body_match.group(1))
    
    return None


def get_pull_requests_for_issue(repository: str, issue_number: int) -> List[Dict[str, Any]]:
    """
    Find pull requests that reference a specific issue.
    Copilot creates PRs that are linked to the issue it was assigned.
    """
    owner, repo = split_owner_repo(repository)
    
    # Search for PRs that mention the issue
    # Copilot creates branches like copilot/issue-123-...
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
        # Check if PR body or branch mentions the issue
        pr_body = (pr.get("body") or "").lower()
        pr_branch = (pr.get("head", {}).get("ref") or "").lower()
        
        if (f"#{issue_number}" in pr_body or 
            f"issue-{issue_number}" in pr_branch or
            f"fixes #{issue_number}" in pr_body or
            f"closes #{issue_number}" in pr_body):
            related_prs.append(pr)
    
    return related_prs


def ensure_pr_base_branch(repository: str, pr_number: int, expected_base: str = BASE_BRANCH) -> bool:
    """
    Ensure PR is targeting the correct base branch.
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
        
        # If we had to change the base, it means Copilot branched from the wrong base
        # This will inevitably cause conflicts once Copilot starts making changes
        # Close the PR immediately and start a new cycle
        print(f"[PR #{pr_number}] ⚠️  Had to change base from {current_base} to {expected_base}")
        print(f"[PR #{pr_number}] This means Copilot branched from {current_base} instead of {expected_base}")
        print(f"[PR #{pr_number}] Conflicts are inevitable - closing this PR and starting fresh")
        
        # Close the PR
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
    """
    Mark a draft PR as ready for review using GraphQL API.
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
    """
    Merge a pull request automatically.
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
    """
    Wait for PR to be done. A PR is considered done when:
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
    """
    Get detailed status of PR checks/CI runs.
    """
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
    """
    Wait for PR checks to complete.
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
    """
    Get all open pull requests created by Copilot.
    
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


def wait_for_existing_prs_to_complete(repository: str, timeout: int = PR_READY_TIMEOUT_SECONDS) -> bool:
    """
    Check for existing open Copilot PRs and wait for them to be ready.
    Returns True if all PRs are ready or no PRs exist, False on timeout.
    """
    print("\n[Pre-cycle check] Checking for existing open Copilot PRs...")
    
    copilot_prs = get_open_copilot_prs(repository)
    
    if not copilot_prs:
        print("[Pre-cycle check] No existing open Copilot PRs found")
        return True
    
    print(f"[Pre-cycle check] Found {len(copilot_prs)} open Copilot PR(s)")
    
    for pr in copilot_prs:
        pr_number = pr.get("number")
        title = pr.get("title")
        
        print(f"[Pre-cycle check] PR #{pr_number}: {title}")
        
        # Wait for this PR to be ready
        pr_ready = wait_for_pr_ready(repository, pr_number, timeout)
        
        if not pr_ready:
            print(f"[Pre-cycle check] ⚠️  PR #{pr_number} did not become ready in time")
            return False
        
        # If auto-merge is enabled, try to merge it
        if AUTO_MERGE_PRS:
            print(f"[Pre-cycle check] Auto-merge enabled - attempting to merge PR #{pr_number}")
            
            # Ensure PR is targeting the correct base branch
            base_ok = ensure_pr_base_branch(repository, pr_number)
            if not base_ok:
                print(f"[Pre-cycle check] ⚠️  Could not verify/update base branch for PR #{pr_number}")
                return False
            
            # Mark as ready for review if it's a draft
            mark_pr_ready_for_review(repository, pr_number)
            
            checks_passed = wait_for_pr_checks(repository, pr_number)
            
            if checks_passed:
                merge_success = merge_pull_request(repository, pr_number)
                
                if merge_success:
                    print(f"[Pre-cycle check] ✓ PR #{pr_number} merged successfully")
                    
                    # Close the associated issue
                    issue_num = get_issue_number_from_pr(repository, pr_number)
                    if issue_num:
                        close_issue(repository, issue_num, 
                                   f"PR #{pr_number} has been merged. Closing this issue.")
                else:
                    print(f"[Pre-cycle check] ⚠️  Failed to merge PR #{pr_number}")
                    return False
            else:
                print(f"[Pre-cycle check] ✗ Checks failed for PR #{pr_number}")
                print(f"[Pre-cycle check] Closing failed PR and cleaning up...")
                
                # Close the PR with explanation
                close_pull_request(repository, pr_number, 
                                 "This PR failed required checks and is being closed. "
                                 "A new improvement cycle will be started.")
                
                # Close and clean up the associated issue
                issue_num = get_issue_number_from_pr(repository, pr_number)
                if issue_num:
                    close_issue(repository, issue_num, 
                               f"PR #{pr_number} failed checks and was closed. "
                               "This issue is being closed as well.")
                
                print(f"[Pre-cycle check] ✓ Cleaned up failed PR #{pr_number}")
                # Continue to next cycle instead of failing
                continue
        else:
            print(f"[Pre-cycle check] Auto-merge disabled - PR #{pr_number} left open")
            print(f"[Pre-cycle check] ⚠️  Please merge manually before starting new cycle")
            return False
    
    print("[Pre-cycle check] ✓ All existing PRs handled")
    return True


def wait_for_copilot_pr(
    repository: str,
    issue_number: int,
    poll_interval: int = PR_POLL_INTERVAL_SECONDS,
    max_wait: int = MAX_WAIT_FOR_PR_SECONDS,
) -> Optional[Dict[str, Any]]:
    """
    Poll until Copilot creates a PR for the assigned issue.
    
    Returns the PR object if found, or None if timeout reached.
    """
    start_time = time.time()
    
    while (time.time() - start_time) < max_wait:
        try:
            # Check if issue is still open
            issue = get_issue(repository, issue_number)
            issue_state = issue.get("state")
            
            print(f"[Issue #{issue_number}] state: {issue_state}")
            
            # Look for PRs created by Copilot
            prs = get_pull_requests_for_issue(repository, issue_number)
            
            if prs:
                print(f"[Issue #{issue_number}] Found {len(prs)} related PR(s)")
                # Return the most recent PR
                return prs[0]
            
            # Check if issue was closed without a PR (unlikely but possible)
            if issue_state == "closed":
                print(f"[Issue #{issue_number}] Issue closed without PR found")
                return None
                
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning(f"[Issue #{issue_number}] Network error: {e}")
            logger.warning(f"[Issue #{issue_number}] Retrying in 10 seconds...")
            time.sleep(10)
            continue
        except requests.HTTPError as e:
            if e.response and e.response.status_code >= 500:
                logger.warning(f"[Issue #{issue_number}] Server error {e.response.status_code}, retrying in 10 seconds...")
                time.sleep(10)
                continue
            else:
                print(f"[Issue #{issue_number}] Error checking status: {e}")
        
        elapsed = int(time.time() - start_time)
        remaining = int(max_wait - elapsed)
        print(f"[Issue #{issue_number}] Waiting for Copilot PR... ({elapsed}s elapsed, {remaining}s remaining)")
        time.sleep(poll_interval)
    
    print(f"[Issue #{issue_number}] Timeout reached after {max_wait}s")
    return None


def pretty_print_pr_summary(issue: Dict[str, Any], pr: Optional[Dict[str, Any]]) -> None:
    """
    Print a summary of the issue and PR created by Copilot.
    """
    issue_number = issue.get("number")
    issue_title = issue.get("title")
    issue_url = issue.get("html_url")

    print("\n=== Copilot Coding Agent Summary ===")
    print(f"Issue: #{issue_number} - {issue_title}")
    print(f"Issue URL: {issue_url}")

    if pr:
        pr_number = pr.get("number")
        pr_title = pr.get("title")
        pr_url = pr.get("html_url")
        pr_state = pr.get("state")
        print(f"\nPull Request Created:")
        print(f"  PR #{pr_number}: {pr_title}")
        print(f"  State: {pr_state}")
        print(f"  URL: {pr_url}")
    else:
        print("\nNo pull request was created (yet).")


# -----------------------------
# Domain-specific prompt builder
# -----------------------------
def build_improvement_prompt(repository: str, base_branch: str) -> str:
    owner, repo = split_owner_repo(repository)

    return f"""
You are a senior machine learning engineer working on {owner}/{repo} - ArbitraryML, an automated ML pipeline that generates complete ML solutions for any arbitrary CSV file using AI-assisted analysis.

PROJECT CONTEXT:
ArbitraryML uses AI agents (Google Gemini or placeholder mode) to automatically analyze unlabeled data and determine the best ML approach. The pipeline ASSUMES UNSUPERVISED LEARNING by default and intelligently decides between clustering, anomaly detection, PU learning, or other unsupervised methods based on data characteristics.

CORE PHILOSOPHY: 
**Default to Unsupervised** - Assume no labeled target exists. The AI agent analyzes the data and selects the most appropriate unsupervised approach:
- **Clustering**: Group similar rows (K-means, DBSCAN, hierarchical)
- **Anomaly Detection**: Identify outliers and unusual patterns (Isolation Forest, One-Class SVM, LOF)
- **PU Learning**: If patterns suggest some positive examples exist in unlabeled data
- **Dimensionality Reduction**: PCA, t-SNE, UMAP for pattern discovery
- **Association Rules**: Find correlations and frequent patterns
- **Density Estimation**: Understand data distribution

CORE PIPELINE STAGES:
1. **Analyze Data Structure**: Examine CSV for patterns, distributions, correlations, and data characteristics
2. **Select Unsupervised Approach**: AI agent intelligently chooses the best method(s) based on data properties
3. **Engineer Features**: Create representations suitable for the chosen unsupervised method
4. **Implement Solution**: Apply clustering, anomaly detection, or other selected approaches with tuning
5. **Evaluate & Interpret**: Assess quality (silhouette scores, anomaly scores, etc.) and generate insights
6. **Generate Output**: Create comprehensive reports showing discovered patterns, clusters, anomalies

PRIMARY MISSION: Build an intelligent unsupervised ML system that can discover meaningful patterns, clusters, and anomalies in any arbitrary dataset without requiring labeled data.

Priority Focus Areas:

1. **Unsupervised Method Selection & Intelligence:**
   - AI agent intelligently selects the best unsupervised approach(es) for the data
   - Implement multiple unsupervised techniques and compare results
   - Add PU (Positive-Unlabeled) learning when patterns suggest it's appropriate
   - Detect when semi-supervised methods could be beneficial
   - Automatically determine optimal number of clusters or anomaly thresholds
   - Add ensemble approaches combining multiple unsupervised methods

2. **Feature Engineering & Data Processing:**
   - Expand automatic feature generation capabilities (interactions, polynomials, aggregations)
   - Improve handling of missing data with intelligent imputation strategies
   - Add automatic outlier detection and handling
   - Implement feature scaling and normalization strategies per algorithm requirements
   - Add dimensionality reduction when appropriate (PCA, feature selection)
   - Handle time-series features, text data, and other special data types

3. **Unsupervised Algorithm Implementation:**
   - Implement multiple clustering algorithms (K-means, DBSCAN, hierarchical, Gaussian Mixture)
   - Add robust anomaly detection methods (Isolation Forest, One-Class SVM, LOF, Elliptic Envelope)
   - Implement PU learning algorithms for detecting positive examples in unlabeled data
   - Add dimensionality reduction techniques (PCA, t-SNE, UMAP) for visualization and pattern discovery
   - Implement density estimation and distribution analysis
   - Add association rule mining for finding correlations

4. **Unsupervised Evaluation & Interpretability:**
   - Implement clustering quality metrics (silhouette score, Davies-Bouldin, Calinski-Harabasz)
   - Add anomaly detection evaluation (contamination analysis, score distributions)
   - Implement cluster profiling and characterization
   - Add visualization of discovered patterns (cluster plots, anomaly heatmaps, dendrograms)
   - Generate actionable insights about discovered groups and outliers
   - Add cluster stability analysis and consistency metrics
   - Implement feature importance for cluster/anomaly discrimination

5. **Pipeline Robustness & Error Handling:**
   - Improve error handling throughout the pipeline with clear, actionable messages
   - Add data validation and quality checks at each stage
   - Implement logging and progress tracking for long-running operations
   - Add graceful degradation when AI services are unavailable
   - Improve placeholder mode to be more intelligent and useful
   - Add pipeline checkpointing for resumability

6. **Visualization-First Output & Reporting:**
   - **PRIMARY FOCUS**: Make reporting HEAVILY visualization-based
   - Generate comprehensive visualizations tailored to the unsupervised method used:
     * **Clustering**: Scatter plots with cluster colors, dendrograms, silhouette plots, cluster size distributions, 2D/3D projections (PCA/t-SNE/UMAP), pair plots showing cluster separation
     * **Anomaly Detection**: Anomaly score distributions, outlier scatter plots with scores, feature-wise anomaly heatmaps, decision boundary visualizations, contamination analysis plots
     * **PU Learning**: Positive/unlabeled separation plots, confidence score distributions, decision boundary visualizations
     * **Dimensionality Reduction**: 2D/3D embeddings with interactive exploration, explained variance plots, component loading heatmaps
     * **General**: Correlation matrices, feature distribution plots, data quality heatmaps, missing data patterns
   - Create interactive HTML reports with embedded visualizations (plotly, bokeh)
   - Generate static plot exports (PNG/SVG) for presentations
   - Add data exploration dashboards showing multiple views simultaneously
   - Visualize data quality and preprocessing steps
   - Include visual comparison of different methods tried
   - Minimal text, maximum visual insights - let plots tell the story
   - Add model export functionality (pickle, joblib) as secondary to visualizations

7. **Testing & Code Quality:**
   - Add comprehensive unit tests for each pipeline stage
   - Implement integration tests with diverse sample datasets
   - Add performance benchmarking and regression testing
   - Improve code modularity and maintainability
   - Add type hints and clear docstrings in the code itself
   - Implement continuous testing with GitHub Actions

Guidelines:
1. Think end-to-end: every change should improve the overall pipeline intelligence
2. Prioritize automation - reduce manual decision-making wherever possible
3. Handle edge cases gracefully - the pipeline should work on diverse, messy real-world data
4. Make AI interactions robust - handle API failures, rate limits, and placeholder mode elegantly
5. Build incrementally - extend working features rather than rewriting from scratch
6. Consider production deployment - code should be production-ready, not just experimental
7. Focus on interpretability - users need to understand what the model does and why
8. Optimize for speed - pipelines should run efficiently even on larger datasets
9. Document in code - use clear docstrings, type hints, and inline comments where needed

Documentation Philosophy:
- Do NOT create excessive separate documentation files
- Document IN THE CODE with clear docstrings and type hints
- Keep README as a holistic overview only, not detailed feature explanations
- Avoid creating lengthy markdown files for each feature
- Self-documenting code is preferred over external documentation
- If extensive knowledge management is needed in the future, use GitHub Wiki instead

CRITICAL - Implementation Requirements:
- You MUST actually implement all code changes yourself - don't just suggest or outline changes
- Write complete, working code for every change you make
- After making changes, you MUST verify them with comprehensive unit tests
- IMPORTANT: The Google Gemini API may NOT be available during your work - ensure placeholder mode works fully
- Use offline testing methods: mock AI API calls, create synthetic test datasets, use fixtures
- All tests must be self-contained and runnable without external API services
- If code depends on Gemini API, mock it completely in tests and ensure placeholder mode is functional
- Run all tests locally to ensure everything works before submitting the PR
- Fix any test failures yourself - the PR should be ready to merge

Deliverables:
- ONE comprehensive pull request with a clear, unified theme
- Detailed PR description explaining what was changed and why
- Well-structured commits that show logical progression
- Complete unit tests for all changed functionality
- Code with clear docstrings and type hints (NOT separate documentation files)
- Update README only if it affects the high-level overview
- All tests passing with mocked dependencies
- Example outputs demonstrating new capabilities

Build intelligence. Automate decisions. Handle edge cases. Make it production-ready. Document in code, not files. Implement everything yourself. Test thoroughly.
""".strip()


# -----------------------------
# Single improvement cycle
# -----------------------------
def run_single_improvement_cycle(cycle_index: int) -> None:
    """
    Run one "improvement cycle":
      1. Check for existing open Copilot PRs and wait for them to complete.
      2. Trigger Copilot via gh CLI with base branch specified.
      3. Wait for Copilot to finish working on the PR.
      4. Merge if checks pass.
    """
    print(f"\n========== Starting improvement cycle #{cycle_index} ==========")
    
    # Check for existing open PRs before starting new cycle
    existing_prs_ready = wait_for_existing_prs_to_complete(REPOSITORY)
    
    if not existing_prs_ready:
        raise RuntimeError(
            f"Cannot start cycle #{cycle_index}: existing Copilot PRs are not ready. "
            "Please resolve existing PRs before starting a new cycle."
        )
    
    print(f"\n[Cycle #{cycle_index}] Ready to trigger Copilot\n")

    prompt = build_improvement_prompt(REPOSITORY, BASE_BRANCH)

    print(f"Triggering Copilot via gh CLI (base branch: {BASE_BRANCH})...")
    pr_number = trigger_copilot_via_gh_cli(REPOSITORY, BASE_BRANCH, prompt)
    
    if pr_number is None:
        raise RuntimeError(f"Failed to trigger Copilot via gh CLI")
    
    # If pr_number is -1, it means job was queued but PR not created yet
    # We need to poll for the PR to be created
    if pr_number == -1:
        print(f"\nPolling for Copilot to create PR...")
        
        # Get all open Copilot PRs and wait for a new one
        start_time = time.time()
        max_wait = 300  # 5 minutes to create PR
        
        while (time.time() - start_time) < max_wait:
            copilot_prs = get_open_copilot_prs(REPOSITORY)
            
            if copilot_prs:
                # Get the most recent PR
                latest_pr = copilot_prs[0]
                pr_number = latest_pr.get("number")
                print(f"✓ Found Copilot PR #{pr_number}")
                break
            
            elapsed = int(time.time() - start_time)
            print(f"Waiting for PR creation... ({elapsed}s elapsed)")
            time.sleep(10)
        
        if pr_number == -1:
            raise RuntimeError(f"Copilot did not create a PR within {max_wait}s")

    print(f"\n=== Copilot Triggered ===")
    print(f"PR #{pr_number} created")
    owner, repo = split_owner_repo(REPOSITORY)
    pr_url = f"https://github.com/{owner}/{repo}/pull/{pr_number}"
    print(f"URL: {pr_url}")
    
    # Track metrics
    _metrics["total_prs_created"] += 1
    _metrics["pr_numbers"].append(pr_number)

    # Automatically merge the PR if enabled
    if AUTO_MERGE_PRS:
        print(f"\n[PR #{pr_number}] Auto-merge enabled - attempting to merge...")
        
        # Wait for Copilot to finish working (no WIP, reviewer assigned)
        pr_ready = wait_for_pr_ready(REPOSITORY, pr_number)
        
        if not pr_ready:
            print(f"[PR #{pr_number}] ⚠️  PR did not become ready in time - skipping merge")
            print(f"[PR #{pr_number}] Copilot may still be working on it")
        else:
            # Verify base branch is correct (should be since we specified it)
            base_ok = ensure_pr_base_branch(REPOSITORY, pr_number)
            if not base_ok:
                print(f"[PR #{pr_number}] ⚠️  Base branch issue - PR was closed")
                print(f"[Cycle #{cycle_index}] Will retry with a new cycle")
                return
            
            # Mark as ready for review if it's a draft
            mark_pr_ready_for_review(REPOSITORY, pr_number)
            
            # Wait for checks to complete
            checks_passed = wait_for_pr_checks(REPOSITORY, pr_number)
            
            if checks_passed:
                # Attempt to merge
                merge_success = merge_pull_request(REPOSITORY, pr_number)
                
                if merge_success:
                    print(f"[PR #{pr_number}] ✓ PR merged successfully!")
                    print(f"[PR #{pr_number}] Changes are now in {BASE_BRANCH}")
                    _metrics["total_prs_merged"] += 1
                    
                    # No issue to close since we used gh CLI
                else:
                    print(f"[PR #{pr_number}] ⚠️  Failed to merge PR - continuing anyway")
                    _metrics["total_prs_failed"] += 1
            else:
                print(f"[PR #{pr_number}] ✗ Checks failed - closing PR")
                _metrics["total_checks_failed"] += 1
                _metrics["total_prs_failed"] += 1
                
                # Close the PR with explanation
                close_pull_request(REPOSITORY, pr_number, 
                                 "This PR failed required checks and is being closed. "
                                 "A new improvement cycle will be started.")
                
                print(f"[PR #{pr_number}] ✓ Cleaned up failed PR")
                print(f"[Cycle #{cycle_index}] Will retry with a new cycle")
    else:
        print(f"\n[PR #{pr_number}] Auto-merge disabled - PR left open for manual review")
        print(f"[PR #{pr_number}] Review and merge manually: {pr_url}")

    print(f"========== Finished improvement cycle #{cycle_index} ==========\n")


# -----------------------------
# Continuous loop
# -----------------------------
def continuous_improvement_loop() -> None:
    """
    Continuous improvement loop that:

    - Starts an agent task.
    - Polls the API until the task is finished (completed/failed/cancelled).
    - Merges the PR if checks pass.
    - Waits before starting the next cycle.
    - Repeats until MAX_CYCLES reached or shutdown requested.

    You can stop the loop with Ctrl+C for graceful shutdown.
    """
    global _shutdown_requested
    
    cycle_index = 1
    consecutive_failures = 0
    successful_cycles = 0
    
    _metrics["cycle_start_time"] = time.time()
    
    logger.info("="*60)
    logger.info("Starting Continuous Improvement Loop")
    logger.info("="*60)
    logger.info(f"Repository: {REPOSITORY}")
    logger.info(f"Base Branch: {BASE_BRANCH}")
    logger.info(f"Auto-merge: {AUTO_MERGE_PRS}")
    logger.info(f"Max Cycles: {MAX_CYCLES if MAX_CYCLES > 0 else 'Unlimited'}")
    logger.info(f"Delay Between Cycles: {DELAY_BETWEEN_CYCLES_SECONDS}s")
    logger.info("="*60)
    
    try:
        while True:
            # Check if shutdown requested
            if _shutdown_requested:
                logger.info("Shutdown requested. Stopping gracefully.")
                break
            
            # Check if max cycles reached
            if MAX_CYCLES > 0 and cycle_index > MAX_CYCLES:
                logger.info(f"Max cycles ({MAX_CYCLES}) reached. Stopping.")
                break
            
            # Check if too many consecutive failures
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error(f"Too many consecutive failures ({consecutive_failures}). Stopping.")
                break
            
            try:
                logger.info(f"\nStarting cycle #{cycle_index}...")
                run_single_improvement_cycle(cycle_index)
                consecutive_failures = 0  # Reset on success
                successful_cycles += 1
                
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"[cycle #{cycle_index}] Error during cycle: {e}", exc_info=True)
                logger.warning(f"Consecutive failures: {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")
            
            cycle_index += 1
            
            # Delay before next cycle (unless shutting down)
            if not _shutdown_requested and (MAX_CYCLES == 0 or cycle_index <= MAX_CYCLES):
                if DELAY_BETWEEN_CYCLES_SECONDS > 0:
                    logger.info(f"Waiting {DELAY_BETWEEN_CYCLES_SECONDS}s before next cycle...")
                    # Sleep in small increments to allow graceful shutdown
                    for _ in range(DELAY_BETWEEN_CYCLES_SECONDS):
                        if _shutdown_requested:
                            break
                        time.sleep(1)
    
    finally:
        total_time = time.time() - _metrics["cycle_start_time"] if _metrics["cycle_start_time"] else 0
        
        logger.info("="*60)
        logger.info("Continuous Improvement Loop Finished")
        logger.info("="*60)
        logger.info(f"Total Runtime: {int(total_time)}s ({int(total_time/60)}m)")
        logger.info(f"Total Cycles Attempted: {cycle_index - 1}")
        logger.info(f"Successful Cycles: {successful_cycles}")
        logger.info(f"Failed Cycles: {(cycle_index - 1) - successful_cycles}")
        logger.info(f"PRs Created: {_metrics['total_prs_created']}")
        logger.info(f"PRs Merged: {_metrics['total_prs_merged']}")
        logger.info(f"PRs Failed: {_metrics['total_prs_failed']}")
        if _metrics['pr_numbers']:
            logger.info(f"PR Numbers: {', '.join(f'#{n}' for n in _metrics['pr_numbers'])}")
        logger.info("="*60)


def main():
    continuous_improvement_loop()


if __name__ == "__main__":
    main()