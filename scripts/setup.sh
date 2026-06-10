#!/bin/bash
set -e

echo "🚀 Setting up finjuice development environment..."

# Check prerequisites
if ! command -v uv &> /dev/null; then
    echo "❌ uv not found. Install from: https://github.com/astral-sh/uv"
    exit 1
fi

if ! command -v gh &> /dev/null; then
    echo "⚠️  gh CLI not found. GitHub integration will be limited."
fi

# Install dependencies
echo "📦 Installing dependencies..."
uv sync
uv pip install -e ".[dev]"

# Create data directory structure
echo "📁 Creating data directories..."
mkdir -p ~/finance/{imports,out/reports,rules}

# Create sample rules.yaml if not exists
if [ ! -f ~/finance/rules/rules.yaml ]; then
    cat > ~/finance/rules/rules.yaml << 'EOF'
version: 1
rules:
  - name: example_rule
    match: "EXAMPLE"
    fields: [merchant_raw]
    tags: ["example"]
    priority: 50
    created_by: manual
EOF
    echo "📝 Created sample rules.yaml at ~/finance/rules/rules.yaml"
fi

# Make scripts executable
chmod +x scripts/*.sh 2>/dev/null || true

echo "✅ Development environment ready!"
echo ""
echo "Next steps:"
echo "  1. Place Banksalad XLSX files in ~/finance/imports/"
echo "  2. Run: /start-phase 1"
echo "  3. Start coding!"
