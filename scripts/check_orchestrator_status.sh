#!/bin/bash
# Quick status check for autonomous orchestrator
# Run: ssh root@161.35.44.166 "bash /opt/gov-ai/scripts/check_orchestrator_status.sh"

echo "╔════════════════════════════════════════════════════════════════════════════╗"
echo "║                 AUTONOMOUS ORCHESTRATOR STATUS CHECK                       ║"
echo "╚════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Check if orchestrator is running
echo "🔍 ORCHESTRATOR PROCESS"
if ps aux | grep -q "[a]utonomous_orchestrator.py"; then
    echo "   ✅ Running (PID: $(ps aux | grep '[a]utonomous_orchestrator.py' | awk '{print $2}'))"
else
    echo "   ❌ NOT RUNNING"
fi
echo ""

# System health
echo "💻 SYSTEM HEALTH"
free -h | grep "Mem:" | awk '{printf "   Memory: %s used / %s total (%s available)\n", $3, $2, $7}'
uptime | awk -F'load average:' '{printf "   Load: %s\n", $2}'
echo ""

# Database stats
echo "📊 DATABASE STATS"
PGPASSWORD=postgres psql -h localhost -U postgres -d gov_ai_db -t -c "
    SELECT
        '   Total Docs: ' || COUNT(*) ||
        ' | With Content: ' || COUNT(*) FILTER (WHERE content IS NOT NULL) ||
        ' | Processed: ' || COUNT(*) FILTER (WHERE processing_success = true)
    FROM documents;
"

echo ""
echo "📋 PROCESSING QUEUE"
PGPASSWORD=postgres psql -h localhost -U postgres -d gov_ai_db -t -c "
    SELECT
        '   Pending: ' || COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) ||
        ' | Processing: ' || COALESCE(SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END), 0) ||
        ' | Completed: ' || COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) ||
        ' | Failed: ' || COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0)
    FROM processing_queue;
"

echo ""
echo "📝 LAST 10 LOG ENTRIES"
tail -10 /opt/gov-ai/logs/autonomous_orchestrator.log | sed 's/^/   /'

echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo "Full logs: /opt/gov-ai/logs/autonomous_orchestrator.log"
echo "Final report: /opt/gov-ai/logs/orchestrator_final_report.txt (when complete)"
echo "═══════════════════════════════════════════════════════════════════════════"
