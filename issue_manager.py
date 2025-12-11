"""Issue management module.

This module handles creating, tracking, and closing GitHub issues,
particularly for Copilot coding agent tasks.
"""

import logging
import requests
from typing import Dict, Any, Optional, List

from config import GITHUB_API_URL
from github_api import session, split_owner_repo, get_repository_id, get_copilot_bot_id, graphql_query

logger = logging.getLogger(__name__)


def create_issue_for_copilot(
    repository: str,
    title: str,
    body: str,
    labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a GitHub issue and assign it to Copilot coding agent using GraphQL API.
    
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
    """Fetch a GitHub issue by number."""
    owner, repo = split_owner_repo(repository)
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/issues/{issue_number}"
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def close_issue(repository: str, issue_number: int, comment: Optional[str] = None) -> bool:
    """Close a GitHub issue.
    
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
