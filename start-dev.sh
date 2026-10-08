#!/bin/bash

# Navigate to the project root directory
cd "$(dirname "$0")"

# Create a directory for logs
mkdir -p logs

export API_HOST=0.0.0.0
export HOSTNAME=0.0.0.0
export PORT=${PORT:-3000}
export NEXT_ALLOWED_DEV_ORIGINS="*.cloudspaces.litng.ai,3000-01m4e0qdmp6h6qjx49c3qkqpd3.cloudspaces.litng.ai"

echo "🚀 Starting Database..."
make database > logs/database.log 2>&1

# Wait a moment for SurrealDB to initialize
sleep 2

echo "🔧 Starting API on 0.0.0.0:5055 (logs: logs/api.log)..."
make api > logs/api.log 2>&1 &
API_PID=$!

# Wait a moment for API to initialize and run migrations
sleep 3

echo "⚙️ Starting Worker (logs: logs/worker.log)..."
make worker-start > logs/worker.log 2>&1 &
WORKER_PID=$!

# Ensure the background processes and database are stopped when you press Ctrl+C
trap "echo -e '\n🛑 Stopping background services...'; kill $API_PID $WORKER_PID 2>/dev/null; docker compose stop surrealdb > /dev/null 2>&1; exit 0" SIGINT SIGTERM EXIT

echo "🌐 Starting Development Frontend on 0.0.0.0:${PORT}..."
ln -sf ../.env frontend/.env.local
cd frontend
pnpm exec next dev -H 0.0.0.0 -p ${PORT}
