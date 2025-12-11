"""GitHub API client module.

This module provides functions for interacting with GitHub's REST and GraphQL APIs,
including rate limiting, retries, and common API operations.
"""

import time
import logging
import requests
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

from config import GITHUB_API_URL, GITHUB_TOKEN

logger = logging.getLogger(__name__)

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
