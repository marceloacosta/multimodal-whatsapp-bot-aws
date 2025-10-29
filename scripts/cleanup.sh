#!/bin/bash
# Cleanup script - removes temporary files and prepares repo for Git

echo "🧹 Cleaning up repository..."

# Remove virtual environment
if [ -d "venv" ]; then
    echo "  ✓ Removing venv/"
    rm -rf venv
fi

# Remove Python cache
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
find . -type f -name "*.pyo" -delete 2>/dev/null
echo "  ✓ Removed Python cache files"

# Remove .DS_Store files (macOS)
find . -name ".DS_Store" -delete 2>/dev/null
echo "  ✓ Removed .DS_Store files"

# Remove zip files from deployments (only in project directory)
find lambdas -name "*.zip" -delete 2>/dev/null
echo "  ✓ Removed deployment zip files"

# Remove log files
find . -name "*.log" -delete 2>/dev/null
echo "  ✓ Removed log files"

# Check for .env file (shouldn't exist for AWS deployment)
if [ -f ".env" ]; then
    echo "  ⚠️  INFO: .env file found"
    echo "     Note: .env is not used for AWS deployment"
    echo "     Environment variables are set per-Lambda in AWS Console/CLI"
    echo "     Make sure .env is in .gitignore if you keep it for local testing"
fi

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "Next steps:"
echo "1. Review .gitignore to ensure all sensitive files are excluded"
echo "2. Review env.example to understand required environment variables"
echo "3. Initialize git: git init"
echo "4. Add files: git add ."
echo "5. Commit: git commit -m 'Initial commit'"
echo "6. Push to GitHub"

