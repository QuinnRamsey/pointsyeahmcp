# PointsYeah MCP Middleware Server

A secure, multi-tenant Model Context Protocol (MCP) middleware server designed to be hosted on **Google Cloud Run**. It exposes the complete **PointsYeah Public API** to AI agents (such as Claude Desktop, Cursor, and custom agentic systems) while strictly following web best practices for security, authorization, and rate limiting.

---

## 🌟 Key Architecture & Highlights

```mermaid
flowchart LR
    subgraph Clients["MCP Clients"]
        A["Claude Desktop / Cursor\n(Owner)"]
        B["Team / External User\n(With Own API Key)"]
    end

    subgraph GCP["Google Cloud Run (Serverless)"]
        M1["Security & Headers Middleware"]
        M2["Rate Limiting (60 req/min)"]
        M3["Server Token Auth Gate\n(Bearer / X-Server-API-Key)"]
        APP["PointsYeah MCP Server\n(SSE: /sse, /messages)"]
        Tools["10 Tools (Flights & Hotels)"]
    end

    subgraph Upstream["PointsYeah API"]
        PY["https://ai-api.pointsyeah.com\n(40+ Airline & Hotel Programs)"]
    end

    A -->|Auth: Bearer ServerToken| M1
    B -->|Auth: Bearer ServerToken\nX-PointsYeah-API-Key: UserKey| M1
    M1 --> M2 --> M3 --> APP --> Tools
    Tools -->|Resolves Key & Forwards| PY
```

### 1. Multi-Tenancy & Credential Management
* **Zero Quota Leakage**: PointsYeah enforces a daily quota (1,000 calls/day on premium). Other users can provide their own PointsYeah credentials, consuming *their* quota instead of yours.
* **Three Flexible Ways to Provide Upstream Keys**:
  1. **Client HTTP Header**: `X-PointsYeah-API-Key: <key>` in MCP client configuration.
  2. **Tool Argument**: `pointsyeah_api_key: "<key>"` directly in tool calls or prompts.
  3. **Server Default**: `DEFAULT_POINTSYEAH_API_KEY` configured in Cloud Run for seamless single-user access by the server owner.

### 2. Security & Access Control
* **Authentication Gate**: Only authorized clients with a valid server token can access the MCP endpoints. Requests without authorization are rejected with `HTTP 401 Unauthorized`.
* **Flexible Authentication Methods**:
  * `Authorization: Bearer <SERVER_API_KEY>`
  * `X-Server-API-Key: <SERVER_API_KEY>`
  * Query Parameter: `?token=<SERVER_API_KEY>` (for MCP clients without custom header support)
* **Multi-User Token Attributions**: Supports multiple named tokens (e.g. `SERVER_API_KEYS=owner:token1,alice:token2`) with timing-safe comparison (`hmac.compare_digest`).
* **Abuse Prevention**: Built-in sliding-window rate limiter (default: 60 requests/minute) prevents denial of service and runaway Cloud Run bills.
* **Web Security Standards**: Strict security headers (`nosniff`, `DENY` frames, `HSTS`, `strict-origin`), restricted CORS, non-root Docker user (`appuser`), and public `/healthz` endpoints for Cloud Run probes.

---

## 🛠️ Available MCP Tools

### ✈️ Flights Suite
| Tool | Description |
| :--- | :--- |
| `search_flights` | Search real-time award flights across 40+ loyalty programs with cabin classes, stops, max points, taxes, bank transfer partners, and pagination. |
| `get_flight_route_recommendations` | Retrieve curated high-value award routes based on a departure airport or global availability. |
| `get_flight_search_aggregates` | Group award availability by arrival or departure airport for broad exploration or map displays. |
| `get_total_flight_count` | Check total number of indexed award flights in the PointsYeah database. |
| `get_flight_filter_ranges` | Query min/max ranges for points, tax, and duration for a given route context. |

### 🏨 Hotels Suite
| Tool | Description |
| :--- | :--- |
| `search_hotels` | Search hotel award availability across Hyatt, Marriott, IHG, Hilton, etc., with automatic city coordinate resolution (e.g. "Tokyo", "London", "New York"). |
| `get_hotel_details` | Retrieve complete property details (photos, amenities, address, phone, policies) by `property_id`. |
| `get_hotel_calendar` | 30-day award points and cash price calendar for a specific hotel property. |
| `get_hotel_recommendations` | Curated hotel recommendations with high redemption values. |
| `get_hotel_map_distribution` | Geographic distribution of hotels grouped by country. |

---

## 🚀 Quick Start (Local Development)

### 1. Setup Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env`:
```ini
# Upstream PointsYeah Key (from https://www.pointsyeah.com/developers/getting-started)
DEFAULT_POINTSYEAH_API_KEY=your_pointsyeah_api_key

# Secret token required to connect to this server
SERVER_API_KEY=my_secure_server_token_12345
```

### 3. Run Test Suite
```bash
pytest -v
```

### 4. Start Local Server
```bash
python3 -m src.server
```
The server will start at `http://localhost:8080`:
* Health check: `http://localhost:8080/healthz`
* MCP SSE endpoint: `http://localhost:8080/sse`

---

## ☁️ Deploying to Google Cloud Run

### Option 1: Automated Script (`deploy.sh`)

Ensure you have the `gcloud` CLI installed and authenticated (`gcloud auth login`). Then run:

```bash
./deploy.sh
```

The script will:
1. Verify Google Cloud SDK and project.
2. Enable Cloud Run and Cloud Build APIs.
3. Prompt for or generate a secure `SERVER_API_KEY`.
4. Deploy the container to Cloud Run with automatic scaling (0 to 5 instances).
5. Output the live Cloud Run URL and ready-to-copy client configuration blocks.

### Option 2: Direct `gcloud` CLI

```bash
# 1. Enable services
gcloud services enable run.googleapis.com cloudbuild.googleapis.com

# 2. Deploy from source
gcloud run deploy pointsyeah-mcp \
  --source . \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars SERVER_API_KEY="your-secret-server-token" \
  --set-env-vars DEFAULT_POINTSYEAH_API_KEY="your-pointsyeah-key" \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 5 \
  --port 8080
```

> **Note on `--allow-unauthenticated`:** Cloud Run's native IAM requires Google OAuth/OIDC tokens which standard desktop MCP clients do not support. Our application-level authentication middleware validates high-entropy Bearer tokens/API keys on every request.

---

## 💻 Client Configuration

### Claude Desktop
Edit your `claude_desktop_config.json`:
* **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

#### Server Owner Configuration:
```json
{
  "mcpServers": {
    "pointsyeah": {
      "url": "https://pointsyeah-mcp-xxxxxx-uc.a.run.app/sse",
      "headers": {
        "Authorization": "Bearer your-secret-server-token"
      }
    }
  }
}
```

#### Shared User Configuration (Providing Their Own PointsYeah Key):
```json
{
  "mcpServers": {
    "pointsyeah": {
      "url": "https://pointsyeah-mcp-xxxxxx-uc.a.run.app/sse",
      "headers": {
        "Authorization": "Bearer your-secret-server-token",
        "X-PointsYeah-API-Key": "USER_OWN_POINTSYEAH_API_KEY"
      }
    }
  }
}
```

### Cursor IDE
Add to `.cursor/mcp.json` or Global Settings:
```json
{
  "mcpServers": {
    "pointsyeah": {
      "url": "https://pointsyeah-mcp-xxxxxx-uc.a.run.app/sse",
      "headers": {
        "Authorization": "Bearer your-secret-server-token"
      }
    }
  }
}
```

### Clients with URL-only Auth (e.g., query param)
If your MCP client does not support custom HTTP headers on SSE connections:
```
https://pointsyeah-mcp-xxxxxx-uc.a.run.app/sse?token=your-secret-server-token
```

---

## 🔒 Security Best Practices Checklist

- [x] **Timing-Safe Token Comparison**: Protected against timing attacks via `hmac.compare_digest`.
- [x] **Zero Credential Leakage**: PointsYeah API keys and server tokens are never echoed in logs or error messages.
- [x] **Least Privilege Container**: Dockerfile executes as unprivileged user `appuser` (UID 10001).
- [x] **DDoS & Cost Protection**: In-memory rate limiting and Cloud Run max-instance capping (`--max-instances 5`).
- [x] **Scale to Zero**: Scales to 0 instances when not in use, incurring \$0 base hosting costs.
- [x] **Public Health Probes**: `/healthz` endpoint accessible by Cloud Run without exposing secrets.
