#!/usr/bin/env bash
# =============================================================================
# Deployment Script for PointsYeah MCP Middleware Server to Google Cloud Run
# =============================================================================

set -e

SERVICE_NAME="pointsyeah-mcp"
DEFAULT_REGION="us-central1"

echo "============================================================"
echo " Deploying PointsYeah MCP Middleware to Google Cloud Run    "
echo "============================================================"

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "Error: 'gcloud' CLI is not installed or not in PATH."
    echo "Install it via https://cloud.google.com/sdk/docs/install or brew install google-cloud-sdk"
    exit 1
fi

# Detect or prompt for Google Cloud Project ID
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || true)
if [ -n "$CURRENT_PROJECT" ]; then
    read -p "Use current GCP Project [$CURRENT_PROJECT]? (Y/n): " CONFIRM_PROJECT
    CONFIRM_PROJECT=${CONFIRM_PROJECT:-Y}
    if [[ "$CONFIRM_PROJECT" =~ ^[Yy]$ ]]; then
        PROJECT_ID="$CURRENT_PROJECT"
    fi
fi

if [ -z "$PROJECT_ID" ]; then
    read -p "Enter your Google Cloud Project ID: " PROJECT_ID
    if [ -z "$PROJECT_ID" ]; then
        echo "Error: Project ID is required."
        exit 1
    fi
fi

# Prompt for Region
read -p "Enter GCP Region [$DEFAULT_REGION]: " REGION
REGION=${REGION:-$DEFAULT_REGION}

# Check for Server Access Token
if [ -z "$SERVER_API_KEY" ]; then
    echo ""
    echo "Server Access Token protects your MCP endpoint from unauthorized internet access."
    # Generate random 32-character token as suggestion
    SUGGESTED_TOKEN=$(openssl rand -hex 16 2>/dev/null || head -c 16 /dev/urandom | xxd -p)
    read -p "Enter Server Access Token [$SUGGESTED_TOKEN]: " INPUT_TOKEN
    SERVER_API_KEY=${INPUT_TOKEN:-$SUGGESTED_TOKEN}
fi

# Prompt for default PointsYeah API Key
if [ -z "$DEFAULT_POINTSYEAH_API_KEY" ]; then
    echo ""
    echo "PointsYeah Upstream API Key (from https://www.pointsyeah.com/developers/getting-started):"
    read -p "Enter your personal PointsYeah API key [Leave blank to require client keys]: " DEFAULT_POINTSYEAH_API_KEY
fi

echo ""
echo "Deploying to Cloud Run with configuration:"
echo " - Project: $PROJECT_ID"
echo " - Region:  $REGION"
echo " - Service: $SERVICE_NAME"
echo ""

# Enable required Google Cloud APIs
echo "Enabling Cloud Run and Cloud Build APIs if not already enabled..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com --project="$PROJECT_ID"

# Build environment variables list
ENV_VARS="SERVER_API_KEY=$SERVER_API_KEY"
if [ -n "$DEFAULT_POINTSYEAH_API_KEY" ]; then
    ENV_VARS="$ENV_VARS,DEFAULT_POINTSYEAH_API_KEY=$DEFAULT_POINTSYEAH_API_KEY"
fi

# Deploy to Cloud Run
echo "Deploying container from source to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --platform managed \
    --allow-unauthenticated \
    --set-env-vars "$ENV_VARS" \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 5 \
    --port 8080

# Retrieve deployed Service URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" --format="value(status.url)")

echo ""
echo "============================================================"
echo " Deployment Successful! 🎉                                  "
echo "============================================================"
echo "Service URL:       $SERVICE_URL"
echo "Health Check:      $SERVICE_URL/healthz"
echo "MCP SSE Endpoint:  $SERVICE_URL/sse"
echo "Server Token:      $SERVER_API_KEY"
echo ""
echo "------------------------------------------------------------"
echo " Claude Desktop Configuration (~/Library/Application Support/Claude/claude_desktop_config.json):"
echo "------------------------------------------------------------"
cat <<EOF
{
  "mcpServers": {
    "pointsyeah": {
      "url": "$SERVICE_URL/sse",
      "headers": {
        "Authorization": "Bearer $SERVER_API_KEY"
      }
    }
  }
}
EOF
echo ""
echo "------------------------------------------------------------"
echo " For Other Users (Multi-Tenancy with Own PointsYeah Key):    "
echo "------------------------------------------------------------"
cat <<EOF
{
  "mcpServers": {
    "pointsyeah": {
      "url": "$SERVICE_URL/sse",
      "headers": {
        "Authorization": "Bearer $SERVER_API_KEY",
        "X-PointsYeah-API-Key": "<USER_OWN_POINTSYEAH_API_KEY>"
      }
    }
  }
}
EOF
echo "============================================================"
