"""Main server module for PointsYeah MCP Middleware.

Assembles MCPServer, registers tools, integrates authentication,
rate limiting, CORS, and health endpoints.
"""

from __future__ import annotations

import logging
import sys
import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from src.config import config
from src.middleware import (
    AuthenticationMiddleware,
    InMemoryRateLimiter,
    SecurityHeadersMiddleware,
    get_public_base_url,
)
from src.tools.flights import register_flight_tools
from src.tools.hotels import register_hotel_tools

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("pointsyeah-server")


def create_mcp_server() -> MCPServer:
    """Create and configure the core MCPServer instance."""
    server = MCPServer(
        name="pointsyeah-mcp",
        instructions=(
            "PointsYeah MCP Middleware: Search and analyze award flights and hotels "
            "across 40+ loyalty programs using the PointsYeah API."
        ),
        version="1.0.0",
    )

    # Register tool suites
    register_flight_tools(server)
    register_hotel_tools(server)

    logger.info("Registered PointsYeah flight and hotel tools.")
    return server


# Global MCPServer instance
mcp_server = create_mcp_server()


async def health_check(request: Request) -> JSONResponse:
    """Public health check endpoint for Cloud Run, load balancers, and uptime probes."""
    tool_count = len(mcp_server._tool_manager.list_tools())
    return JSONResponse(
        {
            "status": "healthy",
            "service": "pointsyeah-mcp",
            "version": "1.0.0",
            "tools_registered": tool_count,
            "transport": "SSE (/sse, /messages)",
            "auth_configured": bool(config.get_authorized_tokens()),
            "default_upstream_key_configured": bool(config.DEFAULT_POINTSYEAH_API_KEY),
        }
    )


async def root_index(request: Request) -> JSONResponse:
    """Root info endpoint."""
    return JSONResponse(
        {
            "name": "PointsYeah MCP Middleware Server",
            "description": "Remote Model Context Protocol (MCP) server for PointsYeah award search.",
            "endpoints": {
                "health": "/healthz",
                "mcp_sse": "/sse",
                "mcp_messages": "/messages",
            },
            "docs": "https://www.pointsyeah.com/developers/getting-started",
        }
    )


async def oauth_authorize_endpoint(request: Request) -> Response:
    """OAuth 2.0 Authorization Endpoint supporting Authorization Code flow.

    Redirects back with code for standard browser and automated OAuth handshakes.
    """
    redirect_uri = request.query_params.get("redirect_uri")
    state = request.query_params.get("state", "")

    if not redirect_uri:
        return JSONResponse(
            {
                "status": "ready",
                "service": "pointsyeah-mcp",
                "message": "PointsYeah OAuth 2.0 Authorization Endpoint",
            }
        )

    tokens = config.get_authorized_tokens()
    primary_token = next(iter(tokens.keys())) if tokens else "authorized"

    separator = "&" if "?" in redirect_uri else "?"
    redirect_url = f"{redirect_uri}{separator}code={primary_token}&state={state}"
    return RedirectResponse(url=redirect_url, status_code=302)


async def oauth_token_endpoint(request: Request) -> JSONResponse:
    """OAuth 2.0 / 2.1 token endpoint supporting client_credentials and authorization_code grants.

    Allows Gemini Web and other OAuth MCP clients to exchange Client ID and
    Client Secret for a valid Bearer access token.
    """
    client_id = None
    client_secret = None
    code = None
    refresh_token = None

    # 1. Check HTTP Basic Auth header: Authorization: Basic base64(client_id:client_secret)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            import base64
            decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            if ":" in decoded:
                client_id, client_secret = decoded.split(":", 1)
            else:
                client_id = decoded
        except Exception:
            pass

    # 2. Check JSON or form body
    content_type = request.headers.get("Content-Type", "")
    try:
        if "application/json" in content_type:
            data = await request.json()
            client_id = client_id or data.get("client_id")
            client_secret = client_secret or data.get("client_secret")
            code = code or data.get("code")
            refresh_token = refresh_token or data.get("refresh_token")
        else:
            form_data = await request.form()
            client_id = client_id or form_data.get("client_id")
            client_secret = client_secret or form_data.get("client_secret")
            code = code or form_data.get("code")
            refresh_token = refresh_token or form_data.get("refresh_token")
    except Exception:
        pass

    # 3. Check query parameters fallback
    client_id = client_id or request.query_params.get("client_id")
    client_secret = client_secret or request.query_params.get("client_secret")
    code = code or request.query_params.get("code")
    refresh_token = refresh_token or request.query_params.get("refresh_token")

    # Determine server key and optional user PointsYeah API key
    server_key = None
    pointsyeah_key = None

    for candidate in [client_secret, code, refresh_token, client_id]:
        if candidate:
            cand_server = candidate.split(":", 1)[0] if ":" in candidate else candidate
            is_auth, _ = config.verify_server_token(cand_server)
            if is_auth:
                server_key = cand_server
                if ":" in candidate:
                    pointsyeah_key = candidate.split(":", 1)[1]
                break

    # If server has no auth configured (open mode)
    if not config.get_authorized_tokens():
        server_key = client_secret or client_id or "authorized"

    # Identify user's PointsYeah API key from the other field if not already extracted
    if not pointsyeah_key:
        if client_id and client_id.strip() not in (server_key, "pointsyeah", "gemini", "client", "default", "none"):
            pointsyeah_key = client_id.strip()
        elif client_secret and client_secret.strip() not in (server_key, "pointsyeah", "gemini", "client", "default", "none"):
            pointsyeah_key = client_secret.strip()

    if not server_key:
        logger.warning(f"OAuth token exchange failed for client_id='{client_id}'")
        return JSONResponse(
            {
                "error": "invalid_client",
                "error_description": "Invalid Client ID, Secret, or Authorization Code.",
            },
            status_code=401,
            headers={
                "WWW-Authenticate": 'Basic realm="mcp"',
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )

    # Issue composite access token if PointsYeah key was provided
    token_to_return = f"{server_key}:{pointsyeah_key}" if pointsyeah_key else server_key

    return JSONResponse(
        {
            "access_token": token_to_return,
            "token_type": "Bearer",
            "expires_in": 86400,
            "refresh_token": token_to_return,
            "scope": "mcp",
        },
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


async def oauth_metadata_endpoint(request: Request) -> JSONResponse:
    """RFC 8414 OAuth 2.0 Authorization Server Metadata."""
    base = get_public_base_url(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "jwks_uri": f"{base}/oauth/jwks",
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic",
                "client_secret_post",
                "none",
            ],
            "grant_types_supported": [
                "client_credentials",
                "authorization_code",
                "refresh_token",
            ],
            "response_types_supported": ["code", "token"],
            "response_modes_supported": ["query", "fragment"],
            "scopes_supported": ["mcp", "offline_access"],
            "code_challenge_methods_supported": ["S256", "plain"],
            "service_documentation": "https://www.pointsyeah.com/developers/getting-started",
        },
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Type": "application/json",
        },
    )


async def oauth_protected_resource_metadata(request: Request) -> JSONResponse:
    """RFC 9728 OAuth 2.0 Protected Resource Metadata for Gemini and MCP."""
    base = get_public_base_url(request)
    subpath = request.path_params.get("path", "").strip("/")
    resource_id = f"{base}/{subpath}" if subpath else base

    return JSONResponse(
        {
            "resource": resource_id,
            "authorization_servers": [base],
            "scopes_supported": ["mcp"],
            "bearer_methods_supported": ["header"],
            "resource_signing_alg_values_supported": [],
        },
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Type": "application/json",
        },
    )


async def oauth_jwks_endpoint(request: Request) -> JSONResponse:
    """OAuth 2.0 JWKS endpoint."""
    return JSONResponse(
        {"keys": []},
        headers={"Cache-Control": "public, max-age=86400"},
    )


async def oauth_userinfo_endpoint(request: Request) -> JSONResponse:
    """OAuth 2.0 / OpenID Connect UserInfo endpoint."""
    return JSONResponse(
        {
            "sub": "pointsyeah-user",
            "name": "PointsYeah User",
            "preferred_username": "pointsyeah",
        }
    )


def create_app() -> Starlette:
    """Create the full ASGI application supporting both StreamableHTTP (Gemini) and SSE (Claude/Cursor)."""
    # Cloud Run host validation settings
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

    # 1. Base StreamableHTTP app (the modern standard required by Gemini Web / Enterprise)
    app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=security_settings,
    )

    # 2. Add SSE transport routes (for Claude Desktop, Cursor, and legacy MCP clients)
    base_sse_app = mcp_server.sse_app(
        sse_path="/sse",
        message_path="/messages",
        transport_security=security_settings,
    )
    app.router.routes.extend(base_sse_app.router.routes)

    # 3. Allow StreamableHTTP on root '/' and '/sse' for POST requests as well as '/mcp'
    streamable_handler = app.router.routes[0].endpoint
    app.router.routes.append(Route("/", streamable_handler, methods=["POST"]))
    app.router.routes.append(Route("/sse", streamable_handler, methods=["POST"]))

    # 4. Custom non-MCP routes (Health, OAuth, and Root Info)
    custom_routes = [
        Route("/healthz", health_check, methods=["GET"]),
        Route("/health", health_check, methods=["GET"]),
        Route("/oauth/authorize", oauth_authorize_endpoint, methods=["GET", "POST"]),
        Route("/oauth/token", oauth_token_endpoint, methods=["POST"]),
        Route("/token", oauth_token_endpoint, methods=["POST"]),
        Route("/oauth/jwks", oauth_jwks_endpoint, methods=["GET"]),
        Route("/.well-known/jwks.json", oauth_jwks_endpoint, methods=["GET"]),
        Route("/oauth/userinfo", oauth_userinfo_endpoint, methods=["GET", "POST"]),
        Route("/userinfo", oauth_userinfo_endpoint, methods=["GET", "POST"]),
        Route(
            "/.well-known/oauth-protected-resource",
            oauth_protected_resource_metadata,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-protected-resource/{path:path}",
            oauth_protected_resource_metadata,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            oauth_metadata_endpoint,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server/{path:path}",
            oauth_metadata_endpoint,
            methods=["GET"],
        ),
        Route(
            "/.well-known/openid-configuration",
            oauth_metadata_endpoint,
            methods=["GET"],
        ),
        Route("/", root_index, methods=["GET"]),
    ]
    app.router.routes.extend(custom_routes)

    # Add middlewares in proper execution order:
    # 1. CORS
    # 2. Security Headers
    # 3. Rate Limiting
    # 4. Authentication (blocks unauthorized traffic before hitting MCP handlers)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        InMemoryRateLimiter,
        max_requests=config.RATE_LIMIT_PER_MINUTE,
        window_seconds=60,
    )
    app.add_middleware(AuthenticationMiddleware)

    return app


app = create_app()


def main() -> None:
    """Run server with uvicorn CLI/process entry point."""
    logger.info(
        f"Starting PointsYeah MCP server on {config.HOST}:{config.PORT} "
        f"(debug={config.DEBUG})"
    )
    uvicorn.run(
        "src.server:app",
        host=config.HOST,
        port=config.PORT,
        log_level="debug" if config.DEBUG else "info",
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
