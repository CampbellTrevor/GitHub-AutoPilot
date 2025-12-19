"""Test repository validation and error handling."""

import os
import sys
import unittest
from unittest.mock import Mock, patch
import requests

# Add the current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from github_api import validate_repository_access
from pr_manager import get_open_copilot_prs


class TestRepositoryValidation(unittest.TestCase):
    """Test repository access validation."""
    
    @patch('github_api.session')
    def test_validate_repository_access_success(self, mock_session):
        """Test successful repository validation."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'full_name': 'owner/repo',
            'private': False,
            'default_branch': 'main'
        }
        mock_session.get.return_value = mock_response
        
        # Should not raise an exception
        validate_repository_access('owner/repo')
    
    @patch('github_api.session')
    def test_validate_repository_access_404(self, mock_session):
        """Test 404 error handling."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_session.get.return_value = mock_response
        
        with self.assertRaises(RuntimeError) as context:
            validate_repository_access('owner/nonexistent-repo')
        
        self.assertIn('not found or not accessible', str(context.exception))
        self.assertIn('repository name is correct', str(context.exception))
    
    @patch('github_api.session')
    def test_validate_repository_access_401(self, mock_session):
        """Test 401 authentication error handling."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_session.get.return_value = mock_response
        
        with self.assertRaises(RuntimeError) as context:
            validate_repository_access('owner/repo')
        
        self.assertIn('Authentication failed', str(context.exception))
        self.assertIn('GH_TOKEN', str(context.exception))
    
    @patch('github_api.session')
    def test_validate_repository_access_403(self, mock_session):
        """Test 403 forbidden error handling."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_session.get.return_value = mock_response
        
        with self.assertRaises(RuntimeError) as context:
            validate_repository_access('owner/repo')
        
        self.assertIn('Access forbidden', str(context.exception))
        self.assertIn('permissions', str(context.exception))


class TestGetOpenCopilotPRs(unittest.TestCase):
    """Test get_open_copilot_prs error handling."""
    
    @patch('pr_manager.session')
    def test_get_open_copilot_prs_404(self, mock_session):
        """Test 404 error handling in get_open_copilot_prs."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_session.get.return_value = mock_response
        
        with self.assertRaises(RuntimeError) as context:
            get_open_copilot_prs('owner/nonexistent-repo')
        
        self.assertIn('not found or not accessible', str(context.exception))
        self.assertIn('repository name is correct', str(context.exception).lower())
    
    @patch('pr_manager.session')
    def test_get_open_copilot_prs_401(self, mock_session):
        """Test 401 error handling in get_open_copilot_prs."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_session.get.return_value = mock_response
        
        with self.assertRaises(RuntimeError) as context:
            get_open_copilot_prs('owner/repo')
        
        self.assertIn('Authentication failed', str(context.exception))
        self.assertIn('GH_TOKEN', str(context.exception))
    
    @patch('pr_manager.session')
    def test_get_open_copilot_prs_success(self, mock_session):
        """Test successful PR retrieval."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'number': 1,
                'title': 'Test PR',
                'user': {'login': 'copilot-swe-agent'},
                'head': {'ref': 'copilot/test-branch'}
            },
            {
                'number': 2,
                'title': 'Non-copilot PR',
                'user': {'login': 'other-user'},
                'head': {'ref': 'feature-branch'}
            }
        ]
        mock_session.get.return_value = mock_response
        
        prs = get_open_copilot_prs('owner/repo')
        
        # Should only return the copilot PR
        self.assertEqual(len(prs), 1)
        self.assertEqual(prs[0]['number'], 1)


if __name__ == '__main__':
    unittest.main()
