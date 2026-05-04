"""Prompt generation module for repository-agnostic improvement cycles."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from github_api import (
    get_repository_commits,
    get_repository_file,
    get_repository_tree,
    split_owner_repo,
)

DEFAULT_CONTEXT_MESSAGE = "No CONTEXT.md file found in the repository."
DEFAULT_README_MESSAGE = "No README.md file found in the repository."
DEFAULT_CONSTRAINTS_MESSAGE = "No DESIGN_CONSTRAINTS.md file found in the repository."
DEFAULT_AGENT_RUNTIME_MESSAGE = "No agent/runtime instruction files found in the repository."
MAX_EMBEDDED_CONTEXT_CHARS = 6000
CORE_CONTEXT_FILES = (
    ("CONTEXT.md", "CONTEXT.md", DEFAULT_CONTEXT_MESSAGE),
    ("README.md", "README.md", DEFAULT_README_MESSAGE),
    ("DESIGN_CONSTRAINTS.md", "DESIGN_CONSTRAINTS.md", DEFAULT_CONSTRAINTS_MESSAGE),
)
AGENT_RUNTIME_CONTEXT_FILES = (
    ("AGENTS.md", "AGENTS.md"),
    ("Pi workspace settings (.pi/settings.json)", ".pi/settings.json"),
    ("Pi agent settings (.pi/agent/settings.json)", ".pi/agent/settings.json"),
    ("Pi model catalog (.pi/agent/models.json)", ".pi/agent/models.json"),
    (
        "GuardianGPT provider extension (.pi/agent/extensions/guardian-gpt-provider.ts)",
        ".pi/agent/extensions/guardian-gpt-provider.ts",
    ),
)
EXCLUDED_DIRECTORIES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
}
EXCLUDED_SUFFIXES = {".pyc"}


def _trim_for_prompt(content: Optional[str], max_chars: int = MAX_EMBEDDED_CONTEXT_CHARS) -> Optional[str]:
    """Trim large file content before embedding it into a prompt."""
    if not content:
        return None

    normalized = content.strip()
    if len(normalized) <= max_chars:
        return normalized

    return normalized[:max_chars].rstrip() + "\n\n[Content truncated for prompt length.]"


def _render_project_context(label: str, content: Optional[str], missing_message: str) -> str:
    """Render a context block with a friendly fallback message."""
    body = _trim_for_prompt(content) or missing_message
    return f"### {label}\n{body}"


def _render_optional_context_blocks(context_files: list[tuple[str, Optional[str]]]) -> str:
    """Render only optional context files that are present."""
    rendered = [
        _render_project_context(label, content, "")
        for label, content in context_files
        if _trim_for_prompt(content)
    ]
    return "\n\n".join(rendered) or DEFAULT_AGENT_RUNTIME_MESSAGE


def read_context_file(repo_path: str) -> Optional[str]:
    """Read a local CONTEXT.md file when present."""
    context_path = Path(repo_path) / "CONTEXT.md"
    if not context_path.exists():
        return None
    return context_path.read_text(encoding="utf-8")


def get_repository_structure(repo_path: str, max_items: int = 100, max_depth: int = 2) -> str:
    """Return a lightweight tree view for a local repository path."""
    root = Path(repo_path)
    if not root.exists():
        return f"Repository path does not exist: {repo_path}"

    lines = []
    for current_root, dirnames, filenames in os.walk(root):
        current_path = Path(current_root)
        rel_path = current_path.relative_to(root)
        depth = 0 if rel_path == Path(".") else len(rel_path.parts)

        dirnames[:] = sorted(
            directory for directory in dirnames if directory not in EXCLUDED_DIRECTORIES
        )
        filenames = sorted(
            filename
            for filename in filenames
            if Path(filename).suffix not in EXCLUDED_SUFFIXES
        )

        if depth > max_depth:
            dirnames[:] = []
            continue

        if rel_path != Path("."):
            lines.append(f"{'  ' * (depth - 1)}{rel_path.name}/")
            if len(lines) >= max_items:
                break

        for filename in filenames:
            lines.append(f"{'  ' * depth}{filename}")
            if len(lines) >= max_items:
                break

        if len(lines) >= max_items:
            break

    if not lines:
        return "Repository structure not available"

    return "Repository structure:\n" + "\n".join(lines)


def get_recent_commits(repo_path: str, limit: int = 10) -> str:
    """Return recent local git commits, or an error string if unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "log", f"--max-count={limit}", "--oneline"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return f"Error fetching commit history: {exc}"

    if result.returncode != 0:
        error_output = (result.stderr or result.stdout).strip()
        return error_output or "No commit history available"

    return result.stdout.strip() or "No commit history available"


def build_improvement_prompt(repository: str, base_branch: str) -> str:
    """Build a repository-aware Copilot prompt for one substantial improvement cycle."""
    owner, repo = split_owner_repo(repository)

    repo_structure = get_repository_tree(repository, base_branch)
    recent_commits = get_repository_commits(repository, base_branch)
    core_context = [
        (label, get_repository_file(repository, path, base_branch), missing_message)
        for label, path, missing_message in CORE_CONTEXT_FILES
    ]
    agent_runtime_context = [
        (label, get_repository_file(repository, path, base_branch))
        for label, path in AGENT_RUNTIME_CONTEXT_FILES
    ]
    project_context = "\n\n".join(
        _render_project_context(label, content, missing_message)
        for label, content, missing_message in core_context
    )
    rendered_agent_runtime_context = _render_optional_context_blocks(agent_runtime_context)

    prompt_parts = [
        f"""
# MISSION: Cohesive Improvement Cycle
**ROLE:** Senior software engineer operating autonomously
**TARGET:** {owner}/{repo} (branch: {base_branch})

You are improving the target repository through one cohesive, high-value improvement package.
Work from evidence in the repository instead of assumptions. Respect the current
architecture, technology choices, and product direction unless the repository
context clearly justifies a change.
Prefer a meaningful slice of work over a tiny patch when the related changes are
clearly connected and can be completed safely in one cycle.
""".strip(),
        f"""
## SITUATION REPORT

### REPOSITORY STRUCTURE
{repo_structure}

### RECENT COMMITS
{recent_commits}
""".strip(),
        f"""
## PROJECT CONTEXT

{project_context}
""".strip(),
        f"""
## AGENT AND RUNTIME CONTEXT

Modern coding-agent repositories may keep binding instructions outside README
files. Treat these files as first-class implementation evidence when present,
especially for wrappers, tools, skills, extensions, generated runtime config,
and project-local agent behavior.

{rendered_agent_runtime_context}
""".strip(),
        """
## DECISION FRAMEWORK

When choosing the next task, prioritize in this order:

1. Correctness, broken behavior, failing tests, or installation/runtime issues.
2. Gaps between documented behavior and the current implementation.
3. FUNCTIONALITY improvements:
   - missing capabilities
   - broken tool behavior
   - configuration, workflow, or runtime logic gaps
   - reliability and security fixes
4. UX improvements:
   - onboarding and setup clarity
   - command and configuration discoverability
   - error-message quality
   - runtime feedback and ergonomics
   - environment variable and configuration usability
5. UI improvements:
   - output formatting and readability
   - status and progress presentation
   - warning and error display clarity
   - color/no-color behavior
   - visual consistency of terminal output
6. Maintainability improvements that make future work safer and easier.
7. Documentation upkeep only as supporting work for the code or UX change you made.

Choose one cohesive improvement theme that can be completed well in a single cycle.
Prefer a package of tightly related edits over a single tiny fix when they share
the same goal, files, or tests.
Avoid broad rewrites unless the repository evidence shows they are necessary.
When there is no urgent bug, explicitly choose one primary lane:
FUNCTIONALITY, UX, or UI.
Supporting edits in adjacent lanes are allowed when they are required to finish
the same improvement cleanly.
Do not choose documentation as the main theme unless the repository context makes
that unavoidable.
""".strip(),
        """
## EXECUTION PROTOCOL

At the START of Each Cycle:
1. Read the repository structure, recent commits, and project context carefully.
2. Read agent/runtime context such as `AGENTS.md`, `.pi/` settings, provider
   extensions, and skill configuration before touching wrappers, tools, or skills.
3. Identify the highest-value missing or broken behavior that can be fixed now.
4. Group the work into one cohesive improvement theme with a complete target outcome.
5. Classify the primary lane as FUNCTIONALITY, UX, or UI.
6. Confirm the relevant files, tests, and constraints before editing.

DO:
- Make a meaningful package of tightly related changes that materially improves the repository.
- Fix the root cause and any directly adjacent gaps needed to make the outcome complete.
- Add or update tests when behavior changes or bugs are fixed.
- Update nearby docs, config, prompts, or UX copy as you go when they are affected by the same change.
- Keep edits aligned with the repo's existing patterns and toolchain.
- Preserve backwards compatibility unless the repository context says otherwise.
- Verify your work and explain any verification gaps clearly.

DO NOT:
- Invent product requirements that are not supported by the repository context.
- Create broad rewrites, speculative abstractions, or dependency churn without evidence.
- Stop at the first small edit when a few nearby follow-up changes are needed to finish the same improvement properly.
- Treat documentation-only work as the default next task when code, UX, or reliability improvements are available.
- Add standalone documentation files, planning docs, or summary documents unless the repository already relies on them.
- Leave partially implemented work without explaining the next best follow-up.

At the END of Each Cycle:
1. Verify the change with the most relevant tests or checks you can run.
2. Summarize exactly what changed, the primary lane, any supporting lane work, and any remaining risks.
3. If the repository already uses `CONTEXT.md`, update it with concise follow-up guidance.

## EXECUTION INSTRUCTIONS

Based on the repository evidence above, identify the most important next improvement theme.
Prefer one primary lane per cycle, but include supporting edits from adjacent lanes when they are part of the same outcome:
- FUNCTIONALITY for behavior, reliability, configuration, workflows, and tests
- UX for usability, clarity, flow, and interaction design
- UI for presentation and terminal visual polish

Keep documentation continuously aligned with the implemented change, but do not
make documentation the headline deliverable unless that is the only clearly
valuable next step.

Implement a complete, substantial slice of work and include any necessary tests.
""".strip(),
    ]

    return "\n\n".join(prompt_parts)
