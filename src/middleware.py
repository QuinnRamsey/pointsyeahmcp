"""Security, Authentication, and Rate Limiting Middlewares for PointsYeah MCP server."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import config

logger = logging.getLogger("pointsyeah-security")

# Unauthenticated public endpoints (e.g. for health checks, load balancers, and OAuth discovery)
PUBLIC_PATHS = {
    "/healthz",
    "/health",
    "/",
    "/oauth/authorize",
    "/oauth/token",
    "/token",
    "/oauth/jwks",
    "/oauth/userinfo",
    "/userinfo",
    "/.well-known/jwks.json",
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
    "/.well-known/oauth-protected-resource",
}


def get_public_base_url(request: Request) -> str:
    """Return the canonical public HTTPS base URL for OAuth and discovery metadata.

    Properly handles Google Cloud Run, load balancers, and reverse proxies
    which terminate SSL and forward traffic over HTTP.
    """
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    # Cloud Run terminates TLS at Google's edge proxy; force https unless strictly localhost
    if not any(h in host for h in ("localhost", "127.0.0.1")):
        proto = "https"
    return f"{proto}://{host}".rstrip("/")


class SecurityHeadersMiddleware:
    """Pure ASGI middleware incorporating web security best practice headers into responses.

    Does not buffer responses or wrap body streams, avoiding Starlette BaseHTTPMiddleware
    streaming assertion errors on persistent SSE connections.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_sse = scope.get("path") == "/sse" and scope.get("method") == "GET"

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and not is_sse:
                headers = list(message.get("headers", []))
                header_names = {h[0].lower() for h in headers}
                if b"x-content-type-options" not in header_names:
                    headers.append((b"x-content-type-options", b"nosniff"))
                if b"x-frame-options" not in header_names:
                    headers.append((b"x-frame-options", b"DENY"))
                if b"strict-transport-security" not in header_names:
                    headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                if b"x-xss-protection" not in header_names:
                    headers.append((b"x-xss-protection", b"1; mode=block"))
                if b"referrer-policy" not in header_names:
                    headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class AuthenticationMiddleware:
    """Pure ASGI middleware enforcing server-level authentication.

    Protects MCP endpoints from unauthorized access by requiring an authorized
    server token configured in the environment. Also normalizes /messages paths to
    prevent Starlette 307 redirects from dropping MCP client connections.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Path normalization: FastMCP mounts message handler at /messages.
        # Starlette's Mount router issues a 307 redirect for /messages -> /messages/,
        # which breaks clients (like Gemini Web) that do not follow redirects on POST.
        path = scope.get("path", "")
        if path == "/messages":
            scope["path"] = "/messages/"
            path = "/messages/"

        request = Request(scope)

        # Allow public health check and OAuth discovery endpoints without authentication
        if (
            path in PUBLIC_PATHS
            or path.startswith("/.well-known/")
            or path.startswith("/oauth/")
        ):
            # If path is "/" but method is POST, that's an MCP request requiring authentication!
            if not (path == "/" and request.method == "POST"):
                await self.app(scope, receive, send)
                return

        # 1. Check Authorization header (Bearer or Basic)
        auth_header = request.headers.get("Authorization", "")
        token: Optional[str] = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif auth_header.startswith("Basic "):
            try:
                import base64

                decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
                if ":" in decoded:
                    # Basic auth format: client_id:client_secret
                    u, p = decoded.split(":", 1)
                    is_p_auth, _ = config.verify_server_token(p)
                    if is_p_auth:
                        token = p
                    else:
                        is_u_auth, _ = config.verify_server_token(u)
                        if is_u_auth:
                            token = u
                else:
                    token = decoded
                if token:
                    token = token.strip()
            except Exception:
                pass

        # 2. Check X-Server-API-Key or X-API-Key
        if not token:
            token = request.headers.get("X-Server-API-Key") or request.headers.get("X-Server-Key")

        # 3. Check query parameters (token, api_key, client_secret, client_id)
        if not token:
            token = (
                request.query_params.get("token")
                or request.query_params.get("api_key")
                or request.query_params.get("client_secret")
                or request.query_params.get("client_id")
            )

        # Check if composite token with user PointsYeah API key is present: <server_key>:<pointsyeah_key>
        server_token = token
        extracted_pointsyeah_key = None
        if token and ":" in token:
            parts = token.split(":", 1)
            is_first_auth, _ = config.verify_server_token(parts[0])
            if is_first_auth:
                server_token = parts[0]
                extracted_pointsyeah_key = parts[1].strip()
            else:
                is_second_auth, _ = config.verify_server_token(parts[1])
                if is_second_auth:
                    server_token = parts[1]
                    extracted_pointsyeah_key = parts[0].strip()

        # Verify server authorization token
        is_authorized, user_label = config.verify_server_token(server_token)

        if not is_authorized:
            client_ip = request.client.host if request.client else "unknown"
            logger.warning(f"Unauthorized request to {path} from {client_ip}")
            base_url = get_public_base_url(request)
            clean_path = path.strip("/")
            if clean_path:
                resource_metadata_url = (
                    f"{base_url}/.well-known/oauth-protected-resource/{clean_path}"
                )
            else:
                resource_metadata_url = (
                    f"{base_url}/.well-known/oauth-protected-resource"
                )

            www_auth = (
                f'Bearer realm="mcp", '
                f'resource_metadata="{resource_metadata_url}", '
                f'authorization_uri="{base_url}/oauth/authorize", '
                f'token_uri="{base_url}/oauth/token"'
            )
            response = JSONResponse(
                {
                    "error": "Unauthorized",
                    "detail": "A valid server API key or OAuth token is required.",
                    "hint": "Pass 'Authorization: Bearer <key>', or authenticate via OAuth 2.0.",
                },
                status_code=401,
                headers={"WWW-Authenticate": www_auth},
            )
            await response(scope, receive, send)
            return

        # Store authenticated identity in scope state
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["authenticated_user"] = user_label or "authenticated"

        # If user PointsYeah API key was supplied in the token, inject into request headers
        if extracted_pointsyeah_key:
            scope["state"]["pointsyeah_api_key"] = extracted_pointsyeah_key
            headers_list = list(scope.get("headers", []))
            headers_list.append(
                (b"x-pointsyeah-api-key", extracted_pointsyeah_key.encode("latin-1"))
            )
            scope["headers"] = headers_list

        await self.app(scope, receive, send)


class InMemoryRateLimiter:
    """Pure ASGI sliding-window in-memory rate limiter per IP / authenticated token.

    Guards against denial-of-service and runaway Cloud Run billing without buffering streams.
    """

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = defaultdict(list)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path
        if path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        # Key by authenticated user if set, or client IP
        state = scope.get("state", {})
        client_key = state.get("authenticated_user") if isinstance(state, dict) else None
        if not client_key and request.client:
            client_key = request.client.host
        client_key = client_key or "anonymous"

        now = time.time()
        cutoff = now - self.window_seconds

        # Prune old timestamps
        timestamps = [t for t in self.requests[client_key] if t > cutoff]
        self.requests[client_key] = timestamps

        if len(timestamps) >= self.max_requests:
            logger.warning(f"Rate limit exceeded for {client_key}")
            response = JSONResponse(
                {
                    "error": "Too Many Requests",
                    "detail": f"Rate limit exceeded. Maximum {self.max_requests} requests per {self.window_seconds}s.",
                },
                status_code=429,
                headers={"Retry-After": str(self.window_seconds)},
            )
            await response(scope, receive, send)
            return

        self.requests[client_key].append(now)
        await self.app(scope, receive, send)
