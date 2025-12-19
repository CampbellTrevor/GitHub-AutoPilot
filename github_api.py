"""GitHub API client module.

This module provides functions for interacting with GitHub's REST and GraphQL APIs,
including rate limiting, retries, and common API operations.
"""

import base64
import time
import logging
import requests
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

from config import GITHUB_API_URL, GITHUB_TOKEN

logger = logging.getLogger(__name__)

# Constants for repository tree fetching
MAX_TREE_ITEMS = 100
MAX_TREE_DEPTH = 2

# Initialize HTTP session with authentication
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


def retry_on_failure(func, max_retries: int = 3, delay: int = 5):
    """Retry a function on failure with exponential backoff."""
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
    """Check GitHub API rate limit and wait if necessary."""
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
    """Execute a GraphQL query against GitHub API."""
    check_rate_limit()
    
    url = "https://api.github.com/graphql"
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    response = session.post(url, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def split_owner_repo(repo: str) -> Tuple[str, str]:
    """Split a repository string into owner and name components."""
    if "/" not in repo:
        raise ValueError(f"Invalid repository: {repo}. Expected 'owner/repo'.")
    owner, name = repo.split("/", 1)
    return owner, name


def validate_repository_access(repository: str) -> None:
    """Validate that the repository exists and is accessible with current credentials.
    
    Args:
        repository: Repository in 'owner/repo' format
        
    Raises:
        RuntimeError: If repository is not accessible with detailed error message
    """
    owner, repo = split_owner_repo(repository)
    
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}"
    
    try:
        response = session.get(url, timeout=30)
        
        if response.status_code == 404:
            raise RuntimeError(
                f"Repository '{repository}' not found or not accessible.\n"
                f"Please check that:\n"
                f"  1. The repository name is correct (format: owner/repo)\n"
                f"  2. The repository exists on GitHub\n"
                f"  3. Your GitHub token has access to this repository\n"
                f"  4. If the repository is private, your token has the required scopes"
            )
        elif response.status_code == 401:
            raise RuntimeError(
                f"Authentication failed for repository '{repository}'.\n"
                f"Please check that:\n"
                f"  1. GH_TOKEN environment variable is set\n"
                f"  2. The token is valid and not expired\n"
                f"  3. You have authenticated with 'gh auth login'"
            )
        elif response.status_code == 403:
            raise RuntimeError(
                f"Access forbidden to repository '{repository}'.\n"
                f"Please check that:\n"
                f"  1. Your GitHub token has the required permissions\n"
                f"  2. The repository allows API access\n"
                f"  3. You haven't exceeded GitHub API rate limits"
            )
        
        response.raise_for_status()
        repo_data = response.json()
        
        logger.info(f"✓ Repository access validated: {repository}")
        logger.info(f"  - Full name: {repo_data.get('full_name')}")
        logger.info(f"  - Private: {repo_data.get('private')}")
        logger.info(f"  - Default branch: {repo_data.get('default_branch')}")
        
    except RuntimeError:
        # Re-raise our custom error messages
        raise
    except requests.RequestException as e:
        raise RuntimeError(
            f"Failed to validate repository access: {e}\n"
            f"Please check your network connection and try again."
        )


def get_copilot_bot_id(repository: str) -> str:
    """Get the Copilot bot ID for assigning issues."""
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
    """Get the GraphQL global ID for a repository."""
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


def get_repository_tree(repository: str, branch: str = "main") -> str:
    """Get repository file tree via GitHub API.
    
    Args:
        repository: Repository in 'owner/repo' format
        branch: Branch name to get tree from
        
    Returns:
        String representation of repository structure
    """
    owner, repo = split_owner_repo(repository)
    
    try:
        # Get the tree via REST API
        url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        response = session.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        tree = data.get("tree", [])
        if not tree:
            return "Unable to fetch repository structure"
        
        # Build a simple tree representation
        # Filter out common excludes and limit depth
        files = []
        for item in tree[:MAX_TREE_ITEMS]:  # Limit to avoid overwhelming output
            path = item.get("path", "")
            item_type = item.get("type", "")
            
            # Skip common excludes
            if any(exclude in path for exclude in [".git/", "node_modules/", "__pycache__/", ".pyc", "dist/", "build/"]):
                continue
            
            # Count depth
            depth = path.count("/")
            if depth > MAX_TREE_DEPTH:  # Limit to avoid overwhelming output
                continue
            
            indent = "  " * depth
            if item_type == "tree":
                files.append(f"{indent}{path.split('/')[-1]}/")
            else:
                files.append(f"{indent}{path.split('/')[-1]}")
        
        if files:
            return "Repository structure:\n" + "\n".join(files)
        
        return "Repository structure not available"
        
    except Exception as e:
        return f"Error fetching repository structure: {e}"


def get_repository_commits(repository: str, branch: str = "main", limit: int = 10) -> str:
    """Get recent commits via GitHub API.
    
    Args:
        repository: Repository in 'owner/repo' format
        branch: Branch name to get commits from
        limit: Number of recent commits to fetch
        
    Returns:
        String representation of recent commits
    """
    owner, repo = split_owner_repo(repository)
    
    try:
        # Get commits via REST API
        url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/commits"
        params = {"sha": branch, "per_page": limit}
        response = session.get(url, params=params, timeout=30)
        response.raise_for_status()
        commits = response.json()
        
        if not commits:
            return "No commits found"
        
        # Format commits similar to git log --oneline
        commit_lines = []
        for commit in commits:
            sha = commit.get("sha", "")[:7]  # Short SHA
            message = commit.get("commit", {}).get("message", "").split("\n")[0]  # First line only
            commit_lines.append(f"{sha} {message}")
        
        return "\n".join(commit_lines)
        
    except Exception as e:
        return f"Error fetching commit history: {e}"


def get_repository_file(repository: str, file_path: str, branch: str = "main") -> Optional[str]:
    """Get contents of a specific file via GitHub API.
    
    Args:
        repository: Repository in 'owner/repo' format
        file_path: Path to file in repository
        branch: Branch name to get file from
        
    Returns:
        File contents as string, or None if file doesn't exist
    """
    owner, repo = split_owner_repo(repository)
    
    try:
        # Get file contents via REST API
        url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/contents/{file_path}"
        params = {"ref": branch}
        response = session.get(url, params=params, timeout=30)
        
        if response.status_code == 404:
            return None
        
        response.raise_for_status()
        data = response.json()
        
        # Decode base64 content
        content = data.get("content", "")
        if content:
            return base64.b64decode(content).decode("utf-8")
        
        return None
        
    except Exception as e:
        logger.warning(f"Error fetching file {file_path}: {e}")
        return None
