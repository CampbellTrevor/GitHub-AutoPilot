# GitHub AutoPilot - Project Context

This file provides project-specific context for the GitHub Copilot coding agent.

## Project Purpose

GitHub AutoPilot is a continuous improvement automation system that uses GitHub Copilot to automatically enhance codebases through iterative cycles.

## Current Priorities

1. **Prompt Builder Improvements** - Make the prompt system generally applicable to any repository
2. **Code Quality** - Maintain clean, well-documented code with comprehensive tests
3. **Reliability** - Ensure robust error handling and graceful degradation
4. **Modularity** - Keep modules focused and loosely coupled

## Architecture Principles

- **Separation of Concerns**: Each module has a single, clear responsibility
- **Configuration Management**: All settings centralized in config.py
- **API Abstraction**: GitHub API interactions isolated in github_api.py
- **Testing**: All new features should include unit tests

## Key Modules

- `config.py` - Configuration and environment variables
- `github_api.py` - GitHub API client with rate limiting
- `copilot_trigger.py` - GitHub CLI integration for triggering Copilot
- `prompt_builder.py` - Dynamic prompt generation for improvement cycles
- `pr_manager.py` - Pull request lifecycle management
- `issue_manager.py` - Issue creation and tracking
- `main.py` - Orchestration loop
- `metrics.py` - Performance tracking

## What NOT to Do

- **No standalone documentation files** - Document in code with docstrings and comments
- **No breaking changes** - Maintain backward compatibility
- **No untested code** - All changes need appropriate tests
- **No over-engineering** - Keep solutions simple and maintainable

## Testing Philosophy

- Unit tests for individual functions
- Integration tests for workflows
- Mock external dependencies (GitHub API, gh CLI)
- Tests must be runnable offline

## Current Focus Areas

As of the latest update, focus on:
1. Making the prompt builder generally applicable (completed)
2. Ensuring the system works with any repository
3. Supporting CONTEXT.md for project-specific guidance
