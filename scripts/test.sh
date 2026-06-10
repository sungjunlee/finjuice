#!/bin/bash
set -e

echo "🧪 Running test suite..."

# Unit tests with coverage
pytest tests/ -v \
    --cov=src/bsalad \
    --cov-report=term-missing \
    --cov-report=html \
    --cov-report=xml \
    --cov-fail-under=80

# Code quality checks
echo ""
echo "🔍 Running linters..."
ruff check src/ tests/
ruff format --check src/ tests/

# Type checking
echo ""
echo "📝 Running type checker..."
mypy src/

echo ""
echo "✅ All checks passed!"
echo "📊 Coverage report: htmlcov/index.html"
