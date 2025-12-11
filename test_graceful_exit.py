#!/usr/bin/env python3
"""Tests for graceful exit handling in pr_manager and main modules."""

import unittest
from unittest.mock import Mock, patch, MagicMock
import time
from pr_manager import _should_stop_waiting, _interruptible_sleep


class TestGracefulExit(unittest.TestCase):
    """Test cases for graceful exit handling."""
    
    def test_should_stop_waiting_no_callback(self):
        """Test _should_stop_waiting with no shutdown check."""
        result = _should_stop_waiting(None)
        self.assertFalse(result)
    
    def test_should_stop_waiting_returns_false(self):
        """Test _should_stop_waiting when shutdown not requested."""
        shutdown_check = Mock(return_value=False)
        result = _should_stop_waiting(shutdown_check)
        self.assertFalse(result)
        shutdown_check.assert_called_once()
    
    def test_should_stop_waiting_returns_true(self):
        """Test _should_stop_waiting when shutdown is requested."""
        shutdown_check = Mock(return_value=True)
        result = _should_stop_waiting(shutdown_check)
        self.assertTrue(result)
        shutdown_check.assert_called_once()
    
    def test_interruptible_sleep_no_shutdown(self):
        """Test _interruptible_sleep completes normally."""
        start = time.time()
        result = _interruptible_sleep(2, None)
        elapsed = time.time() - start
        
        self.assertFalse(result)
        self.assertGreaterEqual(elapsed, 2.0)
        self.assertLess(elapsed, 2.5)
    
    def test_interruptible_sleep_with_shutdown(self):
        """Test _interruptible_sleep stops early on shutdown."""
        # Return False twice, then True, then continue returning True
        shutdown_check = Mock(side_effect=[False, False, True] + [True] * 10)
        
        start = time.time()
        result = _interruptible_sleep(10, shutdown_check)
        elapsed = time.time() - start
        
        self.assertTrue(result)
        # Should stop after ~3 seconds instead of 10
        self.assertLess(elapsed, 5.0)
    
    @patch('pr_manager.session')
    def test_wait_for_pr_ready_detects_closed_pr(self, mock_session):
        """Test wait_for_pr_ready stops when PR is closed."""
        # Mock PR response showing closed state
        mock_response = Mock()
        mock_response.json.return_value = {
            "state": "closed",
            "title": "Test PR"
        }
        mock_response.raise_for_status = Mock()
        mock_session.get.return_value = mock_response
        
        from pr_manager import wait_for_pr_ready
        
        result = wait_for_pr_ready("owner/repo", 123, timeout=60)
        
        self.assertFalse(result)
    
    @patch('pr_manager.session')
    def test_wait_for_pr_ready_with_shutdown_check(self, mock_session):
        """Test wait_for_pr_ready respects shutdown check."""
        # Mock PR response showing WIP state
        mock_response = Mock()
        mock_response.json.return_value = {
            "state": "open",
            "title": "[WIP] Test PR"
        }
        mock_response.raise_for_status = Mock()
        
        mock_reviewers_response = Mock()
        mock_reviewers_response.json.return_value = {"users": []}
        mock_reviewers_response.raise_for_status = Mock()
        
        mock_session.get.side_effect = [mock_response, mock_reviewers_response]
        
        # Shutdown immediately
        shutdown_check = Mock(return_value=True)
        
        from pr_manager import wait_for_pr_ready
        
        result = wait_for_pr_ready("owner/repo", 123, timeout=60, shutdown_check=shutdown_check)
        
        self.assertFalse(result)
        shutdown_check.assert_called()
    
    @patch('pr_manager.session')
    def test_wait_for_pr_checks_detects_closed_pr(self, mock_session):
        """Test wait_for_pr_checks stops when PR is closed."""
        # Mock PR response showing closed state
        mock_response = Mock()
        mock_response.json.return_value = {
            "state": "closed",
            "mergeable_state": "unknown"
        }
        mock_response.raise_for_status = Mock()
        mock_session.get.return_value = mock_response
        
        from pr_manager import wait_for_pr_checks
        
        result = wait_for_pr_checks("owner/repo", 123, timeout=60)
        
        self.assertFalse(result)
    
    @patch('pr_manager.session')
    def test_wait_for_pr_checks_with_shutdown_check(self, mock_session):
        """Test wait_for_pr_checks respects shutdown check."""
        # Mock PR response showing blocked state
        mock_response = Mock()
        mock_response.json.return_value = {
            "state": "open",
            "mergeable_state": "blocked"
        }
        mock_response.raise_for_status = Mock()
        mock_session.get.return_value = mock_response
        
        # Shutdown immediately
        shutdown_check = Mock(return_value=True)
        
        from pr_manager import wait_for_pr_checks
        
        result = wait_for_pr_checks("owner/repo", 123, timeout=60, shutdown_check=shutdown_check)
        
        self.assertFalse(result)
        shutdown_check.assert_called()
    
    @patch('pr_manager.session')
    def test_wait_for_pr_ready_detects_404(self, mock_session):
        """Test wait_for_pr_ready stops when PR returns 404 (deleted)."""
        # Mock 404 error
        import requests
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
        mock_session.get.return_value = mock_response
        
        from pr_manager import wait_for_pr_ready
        
        result = wait_for_pr_ready("owner/repo", 123, timeout=60)
        
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
