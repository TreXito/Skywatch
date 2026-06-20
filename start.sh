#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3.11+ is required. Install it first."
    exit 1
fi

# Auto-setup on first run
if [ ! -d ".venv" ]; then
    echo "📦 First run – setting up virtual environment..."
    python3 -m venv .venv
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install -q --upgrade pip
    pip install -q -r requirements.txt
    echo "✅ Dependencies installed."
else
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

# Create config from example if missing
if [ ! -f "config.yaml" ]; then
    cp config.example.yaml config.yaml
    echo ""
    echo "📝 Created config.yaml – edit it to set your location"
    echo "   (and optionally your Discord webhook). Then run this script again."
    echo ""
    if command -v xdg-open &> /dev/null; then
        xdg-open config.yaml 2>/dev/null || true
    elif command -v open &> /dev/null; then
        open config.yaml 2>/dev/null || true
    fi
    exit 0
fi

# Friendly check: location must be set
if grep -qE '^\s*latitude:\s*0(\.0+)?\s*$' config.yaml && \
   grep -qE '^\s*longitude:\s*0(\.0+)?\s*$' config.yaml; then
    echo "⚠️  Please set your latitude and longitude in config.yaml before starting."
    exit 1
fi

mkdir -p data logs
echo "🛫 Starting Sky Watch on http://localhost:8080"
python -m backend.main
