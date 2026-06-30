#!/usr/bin/env bash
# scripts/setup.sh — Development environment setup script
# Run: bash scripts/setup.sh

set -euo pipefail

echo "╔══════════════════════════════════════════════════════╗"
echo "║         CandidateFusion AI — Dev Setup               ║"
echo "╚══════════════════════════════════════════════════════╝"

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
REQUIRED_VERSION="3.12"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "❌ Python $REQUIRED_VERSION+ required. Found: $PYTHON_VERSION"
    exit 1
fi
echo "✅ Python $PYTHON_VERSION found"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate
echo "✅ Virtual environment activated"

# Upgrade pip
pip install --upgrade pip --quiet

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt --quiet
echo "✅ Dependencies installed"

# Copy .env if missing
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✅ .env created from .env.example (edit to add GITHUB_TOKEN)"
else
    echo "✅ .env already exists"
fi

# Create required directories
mkdir -p inputs outputs logs
echo "✅ Directories created (inputs/, outputs/, logs/)"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                Setup Complete!                        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Quick start:"
echo "  source .venv/bin/activate"
echo "  python main.py --ats inputs/ats.json --csv inputs/recruiter.csv"
echo ""
echo "Run tests:"
echo "  pytest tests/ -v"
echo ""
echo "Start API server:"
echo "  uvicorn api.app:app --reload"
