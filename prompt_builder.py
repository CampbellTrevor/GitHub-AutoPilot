"""Prompt generation module.

This module contains the logic for building improvement prompts for Copilot.

Note: The default prompt is specifically tailored for the ArbitraryML project.
To use this tool for other projects, customize the build_improvement_prompt function
to generate prompts appropriate for your project's domain and goals.
"""

from github_api import split_owner_repo


def build_improvement_prompt(repository: str, base_branch: str) -> str:
    """Build a comprehensive improvement prompt for Copilot coding agent.
    
    This default implementation is tailored for the ArbitraryML project.
    Customize this function for other projects by modifying the prompt template
    to match your project's specific requirements and goals.
    
    Args:
        repository: Repository in 'owner/repo' format
        base_branch: Target branch for improvements
        
    Returns:
        Formatted prompt string for Copilot
    """
    owner, repo = split_owner_repo(repository)

    return f"""
You are a senior machine learning engineer working on {owner}/{repo} - ArbitraryML, an automated ML pipeline that generates complete ML solutions for any arbitrary CSV file using AI-assisted analysis.

PROJECT CONTEXT:
ArbitraryML uses AI agents (Google Gemini or placeholder mode) to automatically analyze unlabeled data and determine the best ML approach. The pipeline ASSUMES UNSUPERVISED LEARNING by default and intelligently decides between clustering, anomaly detection, PU learning, or other unsupervised methods based on data characteristics.

CORE PHILOSOPHY: 
**Default to Unsupervised** - Assume no labeled target exists. The AI agent analyzes the data and selects the most appropriate unsupervised approach:
- **Clustering**: Group similar rows (K-means, DBSCAN, hierarchical)
- **Anomaly Detection**: Identify outliers and unusual patterns (Isolation Forest, One-Class SVM, LOF)
- **PU Learning**: If patterns suggest some positive examples exist in unlabeled data
- **Dimensionality Reduction**: PCA, t-SNE, UMAP for pattern discovery
- **Association Rules**: Find correlations and frequent patterns
- **Density Estimation**: Understand data distribution

CORE PIPELINE STAGES:
1. **Analyze Data Structure**: Examine CSV for patterns, distributions, correlations, and data characteristics
2. **Select Unsupervised Approach**: AI agent intelligently chooses the best method(s) based on data properties
3. **Engineer Features**: Create representations suitable for the chosen unsupervised method
4. **Implement Solution**: Apply clustering, anomaly detection, or other selected approaches with tuning
5. **Evaluate & Interpret**: Assess quality (silhouette scores, anomaly scores, etc.) and generate insights
6. **Generate Output**: Create comprehensive reports showing discovered patterns, clusters, anomalies

PRIMARY MISSION: Build an intelligent unsupervised ML system that can discover meaningful patterns, clusters, and anomalies in any arbitrary dataset without requiring labeled data.

Priority Focus Areas:

1. **Unsupervised Method Selection & Intelligence:**
   - AI agent intelligently selects the best unsupervised approach(es) for the data
   - Implement multiple unsupervised techniques and compare results
   - Add PU (Positive-Unlabeled) learning when patterns suggest it's appropriate
   - Detect when semi-supervised methods could be beneficial
   - Automatically determine optimal number of clusters or anomaly thresholds
   - Add ensemble approaches combining multiple unsupervised methods

2. **Feature Engineering & Data Processing:**
   - Expand automatic feature generation capabilities (interactions, polynomials, aggregations)
   - Improve handling of missing data with intelligent imputation strategies
   - Add automatic outlier detection and handling
   - Implement feature scaling and normalization strategies per algorithm requirements
   - Add dimensionality reduction when appropriate (PCA, feature selection)
   - Handle time-series features, text data, and other special data types

3. **Unsupervised Algorithm Implementation:**
   - Implement multiple clustering algorithms (K-means, DBSCAN, hierarchical, Gaussian Mixture)
   - Add robust anomaly detection methods (Isolation Forest, One-Class SVM, LOF, Elliptic Envelope)
   - Implement PU learning algorithms for detecting positive examples in unlabeled data
   - Add dimensionality reduction techniques (PCA, t-SNE, UMAP) for visualization and pattern discovery
   - Implement density estimation and distribution analysis
   - Add association rule mining for finding correlations

4. **Unsupervised Evaluation & Interpretability:**
   - Implement clustering quality metrics (silhouette score, Davies-Bouldin, Calinski-Harabasz)
   - Add anomaly detection evaluation (contamination analysis, score distributions)
   - Implement cluster profiling and characterization
   - Add visualization of discovered patterns (cluster plots, anomaly heatmaps, dendrograms)
   - Generate actionable insights about discovered groups and outliers
   - Add cluster stability analysis and consistency metrics
   - Implement feature importance for cluster/anomaly discrimination

5. **Pipeline Robustness & Error Handling:**
   - Improve error handling throughout the pipeline with clear, actionable messages
   - Add data validation and quality checks at each stage
   - Implement logging and progress tracking for long-running operations
   - Add graceful degradation when AI services are unavailable
   - Improve placeholder mode to be more intelligent and useful
   - Add pipeline checkpointing for resumability

6. **Visualization-First Output & Reporting:**
   - **PRIMARY FOCUS**: Make reporting HEAVILY visualization-based
   - Generate comprehensive visualizations tailored to the unsupervised method used:
     * **Clustering**: Scatter plots with cluster colors, dendrograms, silhouette plots, cluster size distributions, 2D/3D projections (PCA/t-SNE/UMAP), pair plots showing cluster separation
     * **Anomaly Detection**: Anomaly score distributions, outlier scatter plots with scores, feature-wise anomaly heatmaps, decision boundary visualizations, contamination analysis plots
     * **PU Learning**: Positive/unlabeled separation plots, confidence score distributions, decision boundary visualizations
     * **Dimensionality Reduction**: 2D/3D embeddings with interactive exploration, explained variance plots, component loading heatmaps
     * **General**: Correlation matrices, feature distribution plots, data quality heatmaps, missing data patterns
   - Create interactive HTML reports with embedded visualizations (plotly, bokeh)
   - Generate static plot exports (PNG/SVG) for presentations
   - Add data exploration dashboards showing multiple views simultaneously
   - Visualize data quality and preprocessing steps
   - Include visual comparison of different methods tried
   - Minimal text, maximum visual insights - let plots tell the story
   - Add model export functionality (pickle, joblib) as secondary to visualizations

7. **Testing & Code Quality:**
   - Add comprehensive unit tests for each pipeline stage
   - Implement integration tests with diverse sample datasets
   - Add performance benchmarking and regression testing
   - Improve code modularity and maintainability
   - Add type hints and clear docstrings in the code itself
   - Implement continuous testing with GitHub Actions

Guidelines:
1. Think end-to-end: every change should improve the overall pipeline intelligence
2. Prioritize automation - reduce manual decision-making wherever possible
3. Handle edge cases gracefully - the pipeline should work on diverse, messy real-world data
4. Make AI interactions robust - handle API failures, rate limits, and placeholder mode elegantly
5. Build incrementally - extend working features rather than rewriting from scratch
6. Consider production deployment - code should be production-ready, not just experimental
7. Focus on interpretability - users need to understand what the model does and why
8. Optimize for speed - pipelines should run efficiently even on larger datasets
9. Document in code - use clear docstrings, type hints, and inline comments where needed

Documentation Philosophy:
- Do NOT create excessive separate documentation files
- Document IN THE CODE with clear docstrings and type hints
- Keep README as a holistic overview only, not detailed feature explanations
- Avoid creating lengthy markdown files for each feature
- Self-documenting code is preferred over external documentation
- If extensive knowledge management is needed in the future, use GitHub Wiki instead

CRITICAL - Implementation Requirements:
- You MUST actually implement all code changes yourself - don't just suggest or outline changes
- Write complete, working code for every change you make
- After making changes, you MUST verify them with comprehensive unit tests
- IMPORTANT: The Google Gemini API may NOT be available during your work - ensure placeholder mode works fully
- Use offline testing methods: mock AI API calls, create synthetic test datasets, use fixtures
- All tests must be self-contained and runnable without external API services
- If code depends on Gemini API, mock it completely in tests and ensure placeholder mode is functional
- Run all tests locally to ensure everything works before submitting the PR
- Fix any test failures yourself - the PR should be ready to merge

Deliverables:
- ONE comprehensive pull request with a clear, unified theme
- Detailed PR description explaining what was changed and why
- Well-structured commits that show logical progression
- Complete unit tests for all changed functionality
- Code with clear docstrings and type hints (NOT separate documentation files)
- Update README only if it affects the high-level overview
- All tests passing with mocked dependencies
- Example outputs demonstrating new capabilities

Build intelligence. Automate decisions. Handle edge cases. Make it production-ready. Document in code, not files. Implement everything yourself. Test thoroughly.
""".strip()
