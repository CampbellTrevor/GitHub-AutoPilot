#!/usr/bin/env python3
"""Tests for the prompt_builder module."""

import os
import tempfile
import unittest
from prompt_builder import (
    build_improvement_prompt,
    get_repository_structure,
    get_recent_commits,
    read_context_file
)


class TestPromptBuilder(unittest.TestCase):
    """Test cases for prompt builder functions."""
    
    def test_build_improvement_prompt_basic(self):
        """Test that build_improvement_prompt generates a valid prompt."""
        prompt = build_improvement_prompt("owner/repo", "main")
        
        # Check essential sections are present
        self.assertIn("REPOSITORY STRUCTURE", prompt)
        self.assertIn("RECENT COMMITS", prompt)
        self.assertIn("PROJECT CONTEXT", prompt)
        self.assertIn("At the START of Each Cycle:", prompt)
        self.assertIn("At the END of Each Cycle", prompt)
        
        # Check it mentions the repository
        self.assertIn("owner/repo", prompt)
        self.assertIn("main", prompt)
        
        # Check critical rules are present
        self.assertIn("DO:", prompt)
        self.assertIn("DO NOT:", prompt)
        self.assertIn("documentation files", prompt.lower())
    
    def test_read_context_file_exists(self):
        """Test reading CONTEXT.md when it exists."""
        # Should read the actual CONTEXT.md in this repo
        context = read_context_file(".")
        
        if context is not None:
            self.assertIsInstance(context, str)
            self.assertGreater(len(context), 0)
    
    def test_read_context_file_missing(self):
        """Test reading CONTEXT.md when it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            context = read_context_file(tmpdir)
            self.assertIsNone(context)
    
    def test_get_repository_structure(self):
        """Test that get_repository_structure returns something."""
        structure = get_repository_structure(".")
        
        self.assertIsInstance(structure, str)
        self.assertGreater(len(structure), 0)
        # Should not error out
    
    def test_get_recent_commits(self):
        """Test that get_recent_commits returns commit history."""
        commits = get_recent_commits(".", limit=5)
        
        self.assertIsInstance(commits, str)
        # Should have some content (even if it's an error message)
        self.assertGreater(len(commits), 0)
    
    def test_prompt_without_context_file(self):
        """Test prompt generation works without CONTEXT.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Change to temp directory where no CONTEXT.md exists
            original_dir = os.getcwd()
            try:
                os.chdir(tmpdir)
                
                prompt = build_improvement_prompt("test/repo", "main")
                
                # Should still generate a prompt
                self.assertGreater(len(prompt), 0)
                self.assertIn("No CONTEXT.md file found", prompt)
                
            finally:
                os.chdir(original_dir)
    
    def test_prompt_with_context_file(self):
        """Test prompt generation includes CONTEXT.md content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test CONTEXT.md
            context_path = os.path.join(tmpdir, "CONTEXT.md")
            test_content = "# Test Project\n\nThis is a test context."
            
            with open(context_path, "w") as f:
                f.write(test_content)
            
            # Change to temp directory
            original_dir = os.getcwd()
            try:
                os.chdir(tmpdir)
                
                prompt = build_improvement_prompt("test/repo", "main")
                
                # Should include the context content
                self.assertIn(test_content, prompt)
                self.assertNotIn("No CONTEXT.md file found", prompt)
                
            finally:
                os.chdir(original_dir)


if __name__ == "__main__":
    unittest.main()
