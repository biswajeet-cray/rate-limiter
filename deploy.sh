#!/usr/bin/env bash
# deploy.sh — Pull latest image from ECR and restart the API container.
# Usage: ./deploy.sh
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────
AWS_REGION="ap-south-1"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="rate-limiter"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR_IMAGE="${ECR_REGISTRY}/${ECR_REPO}:latest"

echo "==> Authenticating with ECR..."
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "==> Pulling latest image..."
docker pull "$ECR_IMAGE"

echo "==> Restarting services..."
ECR_IMAGE="$ECR_IMAGE" docker compose -f docker-compose.prod.yml up -d

echo "==> Done. API is running at http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):8000"
