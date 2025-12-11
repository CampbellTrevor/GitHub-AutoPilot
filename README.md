# GitHub AutoPilot

A continuous improvement automation system that uses GitHub Copilot to automatically enhance your codebase through iterative cycles.

## What It Does

GitHub AutoPilot creates a continuous improvement loop:

1. **Triggers GitHub Copilot** to work on improvements via the `gh` CLI
2. **Monitors progress** as Copilot creates pull requests with enhancements
3. **Validates changes** by waiting for CI checks to pass
4. **Automatically merges** successful PRs (optional)
5. **Repeats the cycle** to continuously improve your codebase

The system is designed to run autonomously, creating a self-improving codebase that gets better over time.

## Architecture

The codebase is organized into focused modules with clear separation of concerns:

```
├── config.py           # Configuration and environment variables
├── github_api.py       # GitHub REST and GraphQL API client
├── issue_manager.py    # Issue creation and lifecycle management
├── pr_manager.py       # Pull request operations and monitoring
├── copilot_trigger.py  # GitHub Copilot CLI integration
├── prompt_builder.py   # Improvement prompt generation
├── metrics.py          # Performance metrics tracking
├── main.py            # Main orchestration loop
└── improvement.py      # Legacy monolithic file (deprecated)
```

### Module Responsibilities

- **config.py**: Centralizes all configuration values and environment variables
- **github_api.py**: Handles all GitHub API interactions with rate limiting and retries
- **issue_manager.py**: Creates and manages GitHub issues for Copilot tasks
- **pr_manager.py**: Manages PR lifecycle from creation through merge
- **copilot_trigger.py**: Integrates with GitHub CLI to trigger Copilot agent
- **prompt_builder.py**: Generates improvement prompts tailored to your project
- **metrics.py**: Tracks performance metrics across improvement cycles
- **main.py**: Orchestrates the continuous improvement loop

## Prerequisites

1. **GitHub CLI (`gh`)** - [Install here](https://cli.github.com/)
   ```bash
   # Authenticate with stored credentials (required for agent-task)
   gh auth login
   ```

2. **Python 3.7+** with the following packages:
   ```bash
   pip install requests
   ```

3. **GitHub Personal Access Token** with the following scopes:
   - `repo` (full repository access)
   - `workflow` (if using GitHub Actions)

4. **GitHub Copilot** enabled for your repository

## Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/CampbellTrevor/GitHub-AutoPilot.git
   cd GitHub-AutoPilot
   ```

2. **Set required environment variables:**
   ```bash
   export GITHUB_TOKEN="your_github_token_here"
   export TARGET_REPOSITORY="owner/repo"  # e.g., "CampbellTrevor/ArbitraryML"
   export BASE_BRANCH="main"  # or your target branch
   ```

3. **Verify GitHub CLI authentication:**
   ```bash
   gh auth status
   ```
   Make sure you're authenticated with **stored credentials**, not just environment variables.

## Usage

### Basic Usage

Run a single improvement cycle:
```bash
python main.py
```

### Run Indefinitely

Set `MAX_CYCLES=0` to run until manually stopped:
```bash
export MAX_CYCLES=0
python main.py
```

Stop gracefully with `Ctrl+C` - the current cycle will complete before shutdown.

### Run N Cycles

Run a specific number of cycles:
```bash
export MAX_CYCLES=5
python main.py
```

## Configuration

All configuration is done via environment variables:

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `GITHUB_TOKEN` | GitHub Personal Access Token | `ghp_xxxxx...` |
| `TARGET_REPOSITORY` | Repository to improve | `owner/repo` |
| `BASE_BRANCH` | Branch to target for PRs | `main` |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTO_MERGE_PRS` | `true` | Automatically merge PRs that pass checks |
| `MERGE_METHOD` | `squash` | Merge method: `squash`, `merge`, or `rebase` |
| `MAX_CYCLES` | `0` | Max cycles to run (0 = unlimited) |
| `DELAY_BETWEEN_CYCLES_SECONDS` | `10` | Wait time between cycles |
| `MAX_CONSECUTIVE_FAILURES` | `3` | Stop after N consecutive failures |
| `PR_POLL_INTERVAL_SECONDS` | `60` | How often to check for PR creation |
| `MAX_WAIT_FOR_PR_SECONDS` | `3600` | Max time to wait for PR creation |
| `PR_READY_TIMEOUT_SECONDS` | `1800` | Max time to wait for PR to be ready |
| `PR_CHECK_TIMEOUT_SECONDS` | `600` | Max time to wait for checks |

### Example Configuration

```bash
# Basic setup
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxx"
export TARGET_REPOSITORY="CampbellTrevor/ArbitraryML"
export BASE_BRANCH="Iterate"

# Advanced settings
export AUTO_MERGE_PRS="true"
export MERGE_METHOD="squash"
export MAX_CYCLES="10"
export DELAY_BETWEEN_CYCLES_SECONDS="30"

# Run it
python main.py
```

## How It Works

### Improvement Cycle Flow

```
┌─────────────────────────────────────┐
│  1. Check for existing open PRs     │
│     - Wait for them to complete     │
│     - Merge if checks pass          │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  2. Trigger GitHub Copilot          │
│     - Build improvement prompt      │
│     - Call gh agent-task create     │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  3. Wait for PR creation            │
│     - Poll for new Copilot PR       │
│     - Wait up to 5 minutes          │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  4. Wait for Copilot to finish      │
│     - No [WIP] in title             │
│     - Reviewer assigned             │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  5. Validate base branch            │
│     - Ensure targeting correct base │
│     - Close if branched from wrong  │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  6. Wait for CI checks              │
│     - Monitor check status          │
│     - Timeout if checks take too    │
│       long                          │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  7. Merge or close                  │
│     - Auto-merge if checks pass     │
│     - Close with comment if failed  │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  8. Wait before next cycle          │
│     - Configurable delay            │
│     - Prevents API spam             │
└─────────────────────────────────────┘
```

### Error Handling

The system is designed to be resilient:

- **Network errors**: Automatic retries with exponential backoff
- **Rate limiting**: Monitors GitHub API rate limits and waits if needed
- **Failed PRs**: Automatically closes failed PRs and starts fresh
- **Wrong base branch**: Detects and corrects base branch mismatches
- **Consecutive failures**: Stops after configurable number of failures
- **Graceful shutdown**: Ctrl+C completes current cycle before stopping

## Monitoring

The system provides detailed logging:

- **Console output**: Real-time progress updates
- **Log file**: `improvement.log` with full details
- **Metrics tracking**: PRs created, merged, failed, and cycle times

### Example Output

```
============================================================
Starting Continuous Improvement Loop
============================================================
Repository: CampbellTrevor/ArbitraryML
Base Branch: Iterate
Auto-merge: True
Max Cycles: 5
Delay Between Cycles: 10s
============================================================

========== Starting improvement cycle #1 ==========
[Pre-cycle check] Checking for existing open Copilot PRs...
[Pre-cycle check] No existing open Copilot PRs found

[Cycle #1] Ready to trigger Copilot

Triggering Copilot via gh CLI (base branch: Iterate)...
✓ Copilot job queued successfully
Waiting for Copilot to create PR...
✓ Found Copilot PR #42

=== Copilot Triggered ===
PR #42 created
URL: https://github.com/CampbellTrevor/ArbitraryML/pull/42

[PR #42] Auto-merge enabled - attempting to merge...
[PR #42] Waiting for Copilot to finish work...
[PR #42] ✓ Copilot finished!
[PR #42] Checks: 3/3 passed, 0 pending, 0 failed
[PR #42] ✓ All checks passed (mergeable_state: clean)
[PR #42] ✓ Successfully merged
[PR #42] Changes are now in Iterate

========== Finished improvement cycle #1 ==========
```

## Customizing Prompts

Edit `prompt_builder.py` to customize the improvement prompts sent to Copilot:

```python
def build_improvement_prompt(repository: str, base_branch: str) -> str:
    """Build a comprehensive improvement prompt for Copilot coding agent."""
    return """
    Your custom prompt here...
    
    Focus areas:
    1. Add comprehensive tests
    2. Improve error handling
    3. Refactor for clarity
    ...
    """
```

## Troubleshooting

### "gh CLI not found"
Install GitHub CLI from https://cli.github.com/

### "gh CLI is not authenticated"
Run `gh auth login` and authenticate with stored credentials (not environment variable)

### "Copilot coding agent not found"
Enable GitHub Copilot for your repository in repository settings

### "Rate limit exceeded"
The system automatically handles rate limits, but you can:
- Reduce polling frequency
- Increase delays between cycles
- Use a token with higher rate limits

### PRs keep failing checks
- Review the PR details to understand why checks fail
- Adjust your improvement prompts to be more specific
- Consider manual intervention for complex issues

## Contributing

Contributions are welcome! The modular architecture makes it easy to:

- Add new features in focused modules
- Extend GitHub API capabilities
- Customize improvement strategies
- Add new metrics and monitoring

## License

This project is open source and available under the MIT License.

## Credits

Built with:
- [GitHub CLI](https://cli.github.com/)
- [GitHub Copilot](https://github.com/features/copilot)
- [GitHub REST API](https://docs.github.com/en/rest)
- [GitHub GraphQL API](https://docs.github.com/en/graphql)
