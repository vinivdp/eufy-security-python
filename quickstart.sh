#!/bin/bash

# Eufy Security Python - Quick Start Script
# This script helps you get started quickly

set -e

echo "======================================"
echo "Eufy Security Python - Quick Start"
echo "======================================"
echo ""

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo "❌ Error: Please run this script from the project root directory"
    exit 1
fi

# Check for required tools
echo "Checking requirements..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
if (( $(echo "$PYTHON_VERSION < 3.11" | bc -l) )); then
    echo "❌ Python 3.11+ is required (found $PYTHON_VERSION)"
    exit 1
fi

echo "✅ Python $PYTHON_VERSION"

if ! command -v poetry &> /dev/null; then
    echo "⚠️  Poetry not found. Installing..."
    curl -sSL https://install.python-poetry.org | python3 -
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "✅ Poetry"

if ! command -v docker &> /dev/null; then
    echo "⚠️  Docker not found (optional for local development)"
else
    echo "✅ Docker"
fi

echo ""
echo "======================================"
echo "Setup"
echo "======================================"
echo ""

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo "⚠️  Please edit .env with your credentials:"
    echo "   - EUFY_USERNAME"
    echo "   - EUFY_PASSWORD"
    echo "   - WORKATO_WEBHOOK_URL"
    echo ""
    read -p "Press Enter to edit .env now, or Ctrl+C to exit and edit later..."
    ${EDITOR:-nano} .env
fi

# Create directories
echo "Creating directories..."
mkdir -p recordings logs
echo "✅ Directories created"

# Install dependencies
echo ""
echo "Installing dependencies (this may take a few minutes)..."
poetry install

echo ""
echo "======================================"
echo "✅ Setup Complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Local development:"
echo "   make run"
echo ""
echo "2. Docker (recommended for testing):"
echo "   make docker-run"
echo "   make docker-logs"
echo ""
echo "3. Test the API:"
echo "   curl http://localhost:10000/health"
echo "   open http://localhost:10000/docs"
echo ""
echo "4. Deploy to Render:"
echo "   See DEPLOYMENT.md for instructions"
echo ""
echo "Documentation:"
echo "  - README.md - Full documentation"
echo "  - DEPLOYMENT.md - Deployment guide"
echo "  - SUMMARY.md - Project overview"
echo ""
echo "======================================"