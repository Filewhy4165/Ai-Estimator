#!/usr/bin/env bash
set -euo pipefail

# ── AI-Estimator Deploy Script ─────────────────────────────────────────
# Usage: ./deploy.sh [fly|railway|docker]
# Defaults to "docker" (local compose)

MODE="${1:-docker}"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

check_env() {
    if [ ! -f .env ]; then
        warn "No .env file found. Copying from .env.example..."
        cp .env.example .env
        error "Edit .env with your values, then re-run this script."
    fi
    info "Environment file found."
}

check_deps() {
    case "$MODE" in
        fly)
            command -v fly >/dev/null 2>&1 || error "fly CLI not installed. Run: curl -L https://fly.io/install.sh | sh"
            ;;
        railway)
            command -v railway >/dev/null 2>&1 || error "railway CLI not installed. Run: npm i -g @railway/cli"
            ;;
        docker)
            command -v docker >/dev/null 2>&1 || error "docker not installed."
            command -v docker-compose >/dev/null 2>&1 || command -v docker >/dev/null 2>&1 || error "docker-compose not installed."
            ;;
        *)
            error "Unknown mode: $MODE. Use: fly, railway, or docker"
            ;;
    esac
}

generate_jwt_secret() {
    if grep -q "CHANGE_ME_JWT_SECRET" .env 2>/dev/null; then
        SECRET=$(openssl rand -hex 32)
        sed -i "s/CHANGE_ME_JWT_SECRET/$SECRET/" .env
        info "Generated JWT secret."
    fi
}

deploy_docker() {
    info "Building and starting with docker-compose..."
    docker compose up -d --build
    info "Waiting for services..."
    sleep 10
    info "Running health check..."
    curl -sf http://localhost:8000/health | python3 -m json.tool || warn "Health check failed — services may still be starting."
    echo ""
    info "========================================="
    info "  AI-Estimator is running!"
    info "  API:  http://localhost:8000"
    info "  Web:  http://localhost:3000"
    info "  Docs: http://localhost:8000/docs"
    info "========================================="
}

deploy_fly() {
    check_env
    generate_jwt_secret
    info "Deploying to Fly.io..."
    
    # Create the app if it doesn't exist
    fly apps create ai-estimator 2>/dev/null || true
    
    # Attach Postgres if not already
    if ! fly postgres list 2>/dev/null | grep -q "ai-estimator-db"; then
        info "Creating PostgreSQL database..."
        fly postgres create --name ai-estimator-db --region sjc || true
    fi
    fly postgres attach ai-estimator-db 2>/dev/null || true
    
    # Deploy
    fly deploy
    
    # Set secrets from .env
    info "Setting secrets..."
    grep -v '^#' .env | grep -v '^$' | while read -r line; do
        KEY=$(echo "$line" | cut -d= -f1)
        VAL=$(echo "$line" | cut -d= -f2-)
        if [ -n "$VAL" ] && [ "$VAL" != "changeme" ]; then
            fly secrets set "$KEY=$VAL" 2>/dev/null || true
        fi
    done
    
    info "Deployed! Opening app..."
    fly open
}

deploy_railway() {
    check_env
    generate_jwt_secret
    info "Deploying to Railway..."
    railway up
    info "Setting environment variables..."
    railway variables --set "$(grep -v '^#' .env | grep -v '^$' | xargs)"
    info "Deployed!"
}

# ── Main ───────────────────────────────────────────────────────────────

info "AI-Estimator Deployment — mode: $MODE"
check_deps

case "$MODE" in
    docker)   deploy_docker ;;
    fly)      deploy_fly ;;
    railway)  deploy_railway ;;
esac
