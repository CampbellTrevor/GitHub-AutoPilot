"""Prompt generation module.

This module contains the logic for building improvement prompts for Copilot.
The prompts are generally applicable and adapt to any repository based on:
- Repository structure and files
- Recent commit history
- A central CONTEXT.md file (if present) for project-specific guidance
"""

import os
import subprocess
from typing import Optional
from github_api import split_owner_repo, get_repository_tree, get_repository_commits, get_repository_file


def get_repository_structure(repo_path: str = ".") -> str:
    """Get a summary of the repository structure.
    
    Args:
        repo_path: Path to the repository (default: current directory)
        
    Returns:
        String representation of the repository structure
    """
    try:
        # Use tree command if available, otherwise fall back to find
        tree_cmd = subprocess.run(
            ["tree", "-L", "2", "-I", "node_modules|.git|__pycache__|*.pyc|dist|build", repo_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if tree_cmd.returncode == 0:
            return tree_cmd.stdout
        
        # Fallback: use find command
        find_cmd = subprocess.run(
            ["find", repo_path, "-maxdepth", "2", "-type", "f", 
             "!", "-path", "*/.*", "!", "-path", "*/node_modules/*", 
             "!", "-path", "*/__pycache__/*"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if find_cmd.returncode == 0 and find_cmd.stdout.strip():
            files = find_cmd.stdout.strip().split("\n")
            return "Repository files:\n" + "\n".join(f"  {f}" for f in files[:50])  # Limit to 50 files
        
        return "Unable to determine repository structure"
        
    except Exception as e:
        return f"Error reading repository structure: {e}"


def get_recent_commits(repo_path: str = ".", limit: int = 10) -> str:
    """Get recent commit history.
    
    Args:
        repo_path: Path to the repository (default: current directory)
        limit: Number of recent commits to fetch
        
    Returns:
        String representation of recent commits
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "log", f"-{limit}", "--oneline", "--decorate"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            return result.stdout.strip()
        
        return "Unable to fetch commit history"
        
    except Exception as e:
        return f"Error reading commit history: {e}"


def read_context_file(repo_path: str = ".") -> Optional[str]:
    """Read the CONTEXT.md file if it exists.
    
    Args:
        repo_path: Path to the repository (default: current directory)
        
    Returns:
        Contents of CONTEXT.md or None if it doesn't exist
    """
    context_path = os.path.join(repo_path, "CONTEXT.md")
    
    if os.path.exists(context_path):
        try:
            with open(context_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading CONTEXT.md: {e}"
    
    return None


def build_improvement_prompt(repository: str, base_branch: str) -> str:
    """Build a comprehensive improvement prompt for Copilot coding agent.
    
    This implementation is generally applicable to any repository. It:
    - Analyzes the repository structure
    - Reviews recent commits
    - Reads project-specific context from CONTEXT.md (if present)
    - Instructs the agent to generate and work on prioritized tasks
    
    Args:
        repository: Repository in 'owner/repo' format
        base_branch: Target branch for improvements
        
    Returns:
        Formatted prompt string for Copilot
    """
    owner, repo = split_owner_repo(repository)
    
    # Gather repository information from the target repository via GitHub API
    repo_structure = get_repository_tree(repository, base_branch)
    recent_commits = get_repository_commits(repository, base_branch)
    context_content = get_repository_file(repository, "CONTEXT.md", base_branch)
    
    # Build the prompt
    prompt_parts = []
    
    # Header
    prompt_parts.append(f"""You are working on the repository {owner}/{repo} (branch: {base_branch}).

Your role is to continuously improve this codebase by identifying and implementing the next most valuable changes.""")
    
    # Repository structure
    prompt_parts.append(f"""
## REPOSITORY STRUCTURE

{repo_structure}
""")
    
    # Recent commits
    prompt_parts.append(f"""
## RECENT COMMITS (Last 10)

{recent_commits}
""")
    
    # Project-specific context
    if context_content:
        prompt_parts.append(f"""
## PROJECT CONTEXT (from CONTEXT.md)

{context_content}
""")
    else:
        prompt_parts.append("""
## PROJECT CONTEXT

No CONTEXT.md file found. Use the repository structure, code, and commit history to understand the project.
""")
    
    # Core instructions
    prompt_parts.append("""
## YOUR TASK - CYCLE-BASED CONTINUOUS IMPROVEMENT

### At the START of Each Cycle:
1. **Review Current State:**
   - Examine the repository structure and key files
   - Review recent commits to understand what's been done
   - Read CONTEXT.md (if present, if not present make a CONTEXT.md file) for project-specific priorities and context

2. **Generate Prioritized Task List:**
   - Based on the repository state, recent work, and context, create a list of 3-5 high-value improvements
   - Prioritize tasks by impact and feasibility
   - Consider: bug fixes, feature additions, code quality, testing, performance, documentation-in-code
   - Format as a checklist in your PR description

3. **Select and Execute:**
   - Pick the highest-priority task from your list
   - Implement it completely with working code
   - Test your changes thoroughly

### At the END of Each Cycle (Before Completing):
1. **Review CONTEXT.md:**
   - Re-read CONTEXT.md to ensure alignment with project goals
   - Check if priorities have shifted

2. **Update Task List:**
   - Mark completed tasks as done
   - Reprioritize remaining tasks based on:
     * New insights from your work
     * Updated context from CONTEXT.md
     * Recent commits from other contributors
   
3. **Prepare for Next Cycle:**
   - Note what should be done next (for the next agent cycle)
   - Ensure your work integrates cleanly

## CRITICAL RULES

### DO:
- ✅ Implement complete, working code changes
- ✅ Write tests for your changes
- ✅ Document code with clear docstrings and type hints
- ✅ Make minimal, focused changes per cycle
- ✅ Fix bugs and improve code quality
- ✅ Read and respect CONTEXT.md priorities
- ✅ Update README if your changes affect high-level usage
- ✅ Create a clear, descriptive PR title and description
- ✅ Include your task checklist in the PR description

### DO NOT:
- ❌ Create standalone documentation files (CONTEXT.md is the exception, maintained by humans)
- ❌ Create TODO.md, PLAN.md, ROADMAP.md, or similar planning documents
- ❌ Create extensive markdown files for features or processes
- ❌ Make incomplete or half-finished changes
- ❌ Break existing functionality
- ❌ Add dependencies without careful consideration
- ❌ Ignore test failures

## DOCUMENTATION PHILOSOPHY

**Document IN the code, not in separate files:**
- Use clear function/class names
- Write comprehensive docstrings
- Add inline comments for complex logic
- Use type hints
- Keep README as high-level overview only
- Let CONTEXT.md be the single source of project-level guidance (human-maintained)

## DELIVERABLES FOR THIS CYCLE

1. **Working Code:** Complete implementation of your highest-priority task
2. **Tests:** Unit tests validating your changes
3. **PR Description:** 
   - Clear title describing what you did
   - Checklist showing completed and remaining prioritized tasks
   - Brief explanation of changes
4. **No New Documentation Files:** Document in code only

## QUALITY STANDARDS

- Code must be production-ready
- All tests must pass
- Changes must be minimal and focused
- Code must be well-structured and maintainable
- Error handling must be robust
- Security vulnerabilities must be avoided

Begin by analyzing the repository and generating your prioritized task list. Then implement the top priority item.
""")
    
    return "\n".join(prompt_parts).strip()
