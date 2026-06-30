#!/usr/bin/env bash
# scripts/run_pipeline.sh — Example pipeline execution script

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

echo "Running CandidateFusion AI pipeline with sample inputs..."
echo ""

python main.py \
    --ats inputs/ats.json \
    --csv inputs/recruiter.csv \
    --notes inputs/notes.txt \
    --config config/default.json \
    --output outputs/sample_output.json \
    --verbose

echo ""
echo "Output written to outputs/sample_output.json"
