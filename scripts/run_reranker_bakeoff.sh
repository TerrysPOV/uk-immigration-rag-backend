#!/bin/bash
# Reranker Bakeoff Execution Script
# Runs comparative evaluation of Qwen-8B vs Cohere rerankers
#
# Prerequisites:
# - DEEPINFRA_API_KEY environment variable set
# - COHERE_API_KEY environment variable set
# - Python 3.9+ with numpy, scipy, requests installed
#
# Usage:
#   ./scripts/run_reranker_bakeoff.sh

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root
cd "$PROJECT_ROOT"

log_info "Reranker Bakeoff Execution"
echo "============================================"

# Check API keys
log_info "Checking API keys..."

if [ -z "$DEEPINFRA_API_KEY" ]; then
    log_error "DEEPINFRA_API_KEY not set"
    echo "Set it with: export DEEPINFRA_API_KEY='your_key'"
    exit 1
fi
log_success "DeepInfra API key found"

if [ -z "$COHERE_API_KEY" ]; then
    log_warning "COHERE_API_KEY not set - Cohere benchmark will be skipped"
else
    log_success "Cohere API key found"
fi

# Check Python version
log_info "Checking Python version..."
PYTHON_MAJOR=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1)
PYTHON_MINOR=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f2)
REQUIRED_MAJOR=3
REQUIRED_MINOR=9

if [ "$PYTHON_MAJOR" -gt "$REQUIRED_MAJOR" ] || ([ "$PYTHON_MAJOR" -eq "$REQUIRED_MAJOR" ] && [ "$PYTHON_MINOR" -ge "$REQUIRED_MINOR" ]); then
    log_success "Python $PYTHON_MAJOR.$PYTHON_MINOR detected"
else
    log_error "Python $REQUIRED_MAJOR.$REQUIRED_MINOR+ required (found $PYTHON_MAJOR.$PYTHON_MINOR)"
    exit 1
fi

# Check dependencies
log_info "Checking Python dependencies..."
python3 -c "import numpy, scipy, requests" 2>/dev/null
if [ $? -eq 0 ]; then
    log_success "Required packages installed"
else
    log_error "Missing dependencies. Install with:"
    echo "  pip install numpy scipy requests"
    exit 1
fi

# Verify test data exists
TEST_DATA="test_data/reranker_test_queries.json"
if [ ! -f "$TEST_DATA" ]; then
    log_error "Test data not found: $TEST_DATA"
    exit 1
fi
log_success "Test data found: $TEST_DATA"

# Count test queries
QUERY_COUNT=$(python3 -c "import json; data=json.load(open('$TEST_DATA')); print(len(data))")
log_info "Test dataset: $QUERY_COUNT queries"

# Create results directory
RESULTS_DIR="results"
mkdir -p "$RESULTS_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTPUT_FILE="$RESULTS_DIR/reranker_bakeoff_${TIMESTAMP}.json"

# Test API connectivity
log_info "Testing API connectivity..."

log_info "Testing DeepInfra..."
python3 -c "
from src.rag.components.deepinfra_reranker import DeepInfraReranker
reranker = DeepInfraReranker()
result = reranker.validate_health()
if result['status'] == 'healthy':
    print('✓ DeepInfra: Healthy')
elif result['status'] == 'warning':
    print(f\"⚠ DeepInfra: {result['warning']}\")
else:
    print(f\"✗ DeepInfra: {result['error']}\")
    exit(1)
"
if [ $? -ne 0 ]; then
    log_error "DeepInfra health check failed"
    exit 1
fi

if [ -n "$COHERE_API_KEY" ]; then
    log_info "Testing Cohere..."
    python3 -c "
from src.rag.components.cohere_reranker import CohereReranker
reranker = CohereReranker()
result = reranker.validate_health()
if result['status'] == 'healthy':
    print('✓ Cohere: Healthy')
elif result['status'] == 'warning':
    print(f\"⚠ Cohere: {result['warning']}\")
else:
    print(f\"✗ Cohere: {result['error']}\")
    exit(1)
"
    if [ $? -ne 0 ]; then
        log_warning "Cohere health check failed - will skip benchmark"
    fi
fi

# Run bakeoff
echo ""
log_info "Starting bakeoff evaluation..."
echo "============================================"

python3 src/rag/evaluation/reranker_bakeoff.py \
    --test-cases "$TEST_DATA" \
    --output "$OUTPUT_FILE"

BAKEOFF_EXIT=$?

echo ""
echo "============================================"

if [ $BAKEOFF_EXIT -eq 0 ]; then
    log_success "Bakeoff completed successfully"
    log_info "Results saved to: $OUTPUT_FILE"

    # Print decision recommendation
    echo ""
    log_info "DECISION GUIDANCE"
    echo "============================================"

    # Extract NDCG scores from results
    QWEN_NDCG=$(python3 -c "
import json
data = json.load(open('$OUTPUT_FILE'))
print(f\"{data.get('qwen-8b', {}).get('ndcg_at_10', 0):.3f}\")
" 2>/dev/null || echo "N/A")

    COHERE_NDCG=$(python3 -c "
import json
data = json.load(open('$OUTPUT_FILE'))
print(f\"{data.get('cohere-v3', {}).get('ndcg_at_10', 0):.3f}\")
" 2>/dev/null || echo "N/A")

    echo "Qwen-8B NDCG@10:  $QWEN_NDCG"
    echo "Cohere NDCG@10:   $COHERE_NDCG"
    echo ""

    if [ "$QWEN_NDCG" != "N/A" ] && [ "$COHERE_NDCG" != "N/A" ]; then
        # Calculate percentage difference
        DIFF=$(python3 -c "
qwen = $QWEN_NDCG
cohere = $COHERE_NDCG
diff = ((cohere - qwen) / cohere) * 100
print(f'{diff:.1f}')
")

        echo "Quality difference: ${DIFF}%"
        echo ""

        # Decision logic
        python3 -c "
diff = $DIFF
if diff <= 5:
    print('✅ RECOMMENDATION: Deploy Qwen-8B')
    print('   - Quality within 5% of Cohere')
    print('   - Saves \$150/month vs Cohere')
    print('   - Vendor consolidation with DeepInfra')
else:
    print('✅ RECOMMENDATION: Deploy Cohere')
    print(f'   - {diff:.1f}% better quality than Qwen')
    print('   - Best-in-class performance')
    print('   - Production SLA (99.9%)')
"
    fi

    echo ""
    log_info "Next steps:"
    echo "  1. Review full report above"
    echo "  2. Check for uniform scoring warnings"
    echo "  3. Deploy winning model to production"
    echo "  4. Update haystack_retrieval.py with chosen reranker"
    echo "  5. Proceed with rag-adv-updated implementation"

else
    log_error "Bakeoff failed with exit code $BAKEOFF_EXIT"
    exit $BAKEOFF_EXIT
fi
