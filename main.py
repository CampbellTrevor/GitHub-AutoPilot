#!/usr/bin/env python3
"""GitHub AutoPilot - Continuous Improvement Automation.

This is the main entry point for the GitHub AutoPilot system.
It orchestrates continuous improvement cycles using GitHub Copilot.
"""

import sys
import time
import signal
import logging

from config import (
    REPOSITORY, BASE_BRANCH, AUTO_MERGE_PRS, MAX_CYCLES,
    DELAY_BETWEEN_CYCLES_SECONDS, MAX_CONSECUTIVE_FAILURES
)
from copilot_trigger import trigger_copilot_via_gh_cli
from pr_manager import (
    ensure_pr_base_branch, mark_pr_ready_for_review, wait_for_pr_ready,
    wait_for_pr_checks, merge_pull_request, close_pull_request,
    get_issue_number_from_pr, get_open_copilot_prs
)
from issue_manager import close_issue, get_issue
from prompt_builder import build_improvement_prompt
from metrics import metrics
from github_api import split_owner_repo

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


def wait_for_existing_prs_to_complete(repository: str, timeout: int) -> bool:
    """Check for existing open Copilot PRs and wait for them to be ready.
    
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


def run_single_improvement_cycle(cycle_index: int) -> None:
    """Run one improvement cycle.
    
    Steps:
      1. Check for existing open Copilot PRs and wait for them to complete.
      2. Trigger Copilot via gh CLI with base branch specified.
      3. Wait for Copilot to finish working on the PR.
      4. Merge if checks pass.
    """
    from config import PR_READY_TIMEOUT_SECONDS
    
    print(f"\n========== Starting improvement cycle #{cycle_index} ==========")
    
    # Check for existing open PRs before starting new cycle
    existing_prs_ready = wait_for_existing_prs_to_complete(REPOSITORY, PR_READY_TIMEOUT_SECONDS)
    
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
    metrics.record_pr_created(pr_number)

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
                    metrics.record_pr_merged()
                else:
                    print(f"[PR #{pr_number}] ⚠️  Failed to merge PR - continuing anyway")
                    metrics.record_pr_failed()
            else:
                print(f"[PR #{pr_number}] ✗ Checks failed - closing PR")
                metrics.record_checks_failed()
                metrics.record_pr_failed()
                
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


def continuous_improvement_loop() -> None:
    """Run the continuous improvement loop.
    
    The loop:
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
    
    metrics.start_cycle()
    
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
        summary = metrics.get_summary()
        
        logger.info("="*60)
        logger.info("Continuous Improvement Loop Finished")
        logger.info("="*60)
        logger.info(f"Total Runtime: {summary['total_runtime_seconds']}s ({summary['total_runtime_minutes']}m)")
        logger.info(f"Total Cycles Attempted: {cycle_index - 1}")
        logger.info(f"Successful Cycles: {successful_cycles}")
        logger.info(f"Failed Cycles: {(cycle_index - 1) - successful_cycles}")
        logger.info(f"PRs Created: {summary['prs_created']}")
        logger.info(f"PRs Merged: {summary['prs_merged']}")
        logger.info(f"PRs Failed: {summary['prs_failed']}")
        if summary['pr_numbers']:
            logger.info(f"PR Numbers: {', '.join(f'#{n}' for n in summary['pr_numbers'])}")
        logger.info("="*60)


def main():
    """Main entry point."""
    continuous_improvement_loop()


if __name__ == "__main__":
    main()
