"""Tests for authentication, authorization, and security middlewares."""

import pytest
from starlette.testclient import TestClient

from src.config import config
from src.server import create_app


def test_public_health_endpoints():
    """Verify that health check endpoints do not require authentication."""
    app = create_app()
    client = TestClient(app)

    r1 = client.get("/healthz")
    assert r1.status_code == 200
    assert r1.json()["status"] == "healthy"

    r2 = client.get("/health")
    assert r2.status_code == 200

    r3 = client.get("/")
    assert r3.status_code == 200


def test_unauthorized_access_rejected(monkeypatch):
    """Verify that requests without an authorized token are rejected with 401."""
    monkeypatch.setattr(config, "SERVER_API_KEY", "secret-test-token-12345")
    monkeypatch.setattr(config, "SERVER_API_KEYS_RAW", None)
    monkeypatch.setattr(config, "DEBUG", False)

    app = create_app()
    client = TestClient(app)

    # Missing auth
    r = client.get("/messages")
    assert r.status_code == 401
    assert r.json()["error"] == "Unauthorized"

    # Invalid token
    r_bad = client.get("/messages", headers={"Authorization": "Bearer wrong-token"})
    assert r_bad.status_code == 401


def test_bearer_token_authentication(monkeypatch):
    """Verify that Authorization: Bearer <token> allows access."""
    token = "quinn-secret-test-token"
    monkeypatch.setattr(config, "SERVER_API_KEY", token)
    monkeypatch.setattr(config, "SERVER_API_KEYS_RAW", None)
    monkeypatch.setattr(config, "DEBUG", False)

    app = create_app()
    client = TestClient(app)

    r = client.get("/messages", headers={"Authorization": f"Bearer {token}"})
    # Method not allowed or not 401 means auth middleware passed!
    assert r.status_code != 401


def test_header_api_key_authentication(monkeypatch):
    """Verify X-Server-API-Key header works."""
    token = "another-secret-token"
    monkeypatch.setattr(config, "SERVER_API_KEY", token)
    monkeypatch.setattr(config, "SERVER_API_KEYS_RAW", None)
    monkeypatch.setattr(config, "DEBUG", False)

    app = create_app()
    client = TestClient(app)

    r = client.get("/messages", headers={"X-Server-API-Key": token})
    assert r.status_code != 401


def test_query_param_token_authentication(monkeypatch):
    """Verify ?token=... query parameter authentication works."""
    token = "query-param-token"
    monkeypatch.setattr(config, "SERVER_API_KEY", token)
    monkeypatch.setattr(config, "SERVER_API_KEYS_RAW", None)
    monkeypatch.setattr(config, "DEBUG", False)

    app = create_app()
    client = TestClient(app)

    r = client.get(f"/messages?token={token}")
    assert r.status_code != 401


def test_multi_user_tokens(monkeypatch):
    """Verify multi-user comma-separated SERVER_API_KEYS configuration."""
    monkeypatch.setattr(config, "SERVER_API_KEY", None)
    monkeypatch.setattr(
        config, "SERVER_API_KEYS_RAW", "quinn:token-quinn-999,alice:token-alice-888"
    )
    monkeypatch.setattr(config, "DEBUG", False)

    tokens = config.get_authorized_tokens()
    assert tokens["token-quinn-999"] == "quinn"
    assert tokens["token-alice-888"] == "alice"

    auth1, label1 = config.verify_server_token("token-quinn-999")
    assert auth1 is True
    assert label1 == "quinn"

    auth2, label2 = config.verify_server_token("token-alice-888")
    assert auth2 is True
    assert label2 == "alice"

    auth_bad, _ = config.verify_server_token("invalid-token")
    assert auth_bad is False


def test_security_headers():
    """Verify security headers are applied to responses."""
    app = create_app()
    client = TestClient(app)

    r = client.get("/healthz")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" in r.headers
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_rate_limiting(monkeypatch):
    """Verify that excessive requests trigger rate limiting (429)."""
    monkeypatch.setattr(config, "SERVER_API_KEY", "token-for-ratelimit")
    monkeypatch.setattr(config, "SERVER_API_KEYS_RAW", None)
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 5)

    app = create_app()
    client = TestClient(app)

    headers = {"Authorization": "Bearer token-for-ratelimit"}
    # Send 5 requests
    for _ in range(5):
        client.get("/messages", headers=headers)

    # 6th request should hit rate limit
    r_limit = client.get("/messages", headers=headers)
    assert r_limit.status_code == 429
    assert r_limit.json()["error"] == "Too Many Requests"


def test_oauth_token_exchange(monkeypatch):
    """Verify OAuth 2.0 /token endpoint accepts Client ID and Secret."""
    token = "secret-client-token-999"
    monkeypatch.setattr(config, "SERVER_API_KEY", token)
    monkeypatch.setattr(config, "SERVER_API_KEYS_RAW", None)
    monkeypatch.setattr(config, "DEBUG", False)

    app = create_app()
    client = TestClient(app)

    # 1. Invalid secret rejected
    r_bad = client.post(
        "/oauth/token",
        json={"client_id": "gemini", "client_secret": "wrong-secret"},
    )
    assert r_bad.status_code == 401

    # 2. Valid secret accepted via JSON
    r_good = client.post(
        "/oauth/token",
        json={"client_id": "gemini", "client_secret": token},
    )
    assert r_good.status_code == 200
    data = r_good.json()
    assert data["access_token"] == token
    assert data["token_type"] == "Bearer"

    # 3. Valid secret accepted via HTTP Basic Auth
    r_basic = client.post(
        "/token",
        auth=("gemini", token),
    )
    assert r_basic.status_code == 200
    assert r_basic.json()["access_token"] == token


def test_oauth_metadata():
    """Verify RFC 8414 OAuth authorization server metadata."""
    app = create_app()
    client = TestClient(app)

    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    data = r.json()
    assert "token_endpoint" in data
    assert "client_credentials" in data["grant_types_supported"]


def test_rfc9728_protected_resource_metadata():
    """Verify RFC 9728 OAuth protected resource metadata."""
    app = create_app()
    client = TestClient(app)

    headers = {
        "x-forwarded-proto": "https",
        "x-forwarded-host": "mcp.example.com",
    }

    r1 = client.get("/.well-known/oauth-protected-resource", headers=headers)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["resource"] == "https://mcp.example.com"
    assert d1["authorization_servers"] == ["https://mcp.example.com"]

    r2 = client.get("/.well-known/oauth-protected-resource/sse", headers=headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["resource"] == "https://mcp.example.com/sse"
    assert d2["authorization_servers"] == ["https://mcp.example.com"]


def test_401_challenge_contains_resource_metadata():
    """Verify 401 response contains RFC 9728 resource_metadata in WWW-Authenticate header."""
    app = create_app()
    client = TestClient(app)

    headers = {
        "x-forwarded-proto": "https",
        "x-forwarded-host": "mcp.example.com",
    }

    r = client.head("/sse", headers=headers)
    assert r.status_code == 401
    www_auth = r.headers.get("WWW-Authenticate", "")
    assert 'resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/sse"' in www_auth
    assert 'authorization_uri="https://mcp.example.com/oauth/authorize"' in www_auth
    assert 'token_uri="https://mcp.example.com/oauth/token"' in www_auth


def test_pointsyeah_key_binding_via_client_id(monkeypatch):
    """Verify that passing PointsYeah API key as client_id binds it to the access token."""
    server_key = "server-pass-token-999"
    user_py_key = "user-personal-pointsyeah-key-12345"
    monkeypatch.setattr(config, "SERVER_API_KEY", server_key)
    monkeypatch.setattr(config, "SERVER_API_KEYS_RAW", None)
    monkeypatch.setattr(config, "DEBUG", False)

    app = create_app()
    client = TestClient(app)

    # 1. Exchange client_id (PointsYeah key) + client_secret (Server key)
    r = client.post(
        "/oauth/token",
        json={"client_id": user_py_key, "client_secret": server_key},
    )
    assert r.status_code == 200
    token_data = r.json()
    assert token_data["access_token"] == f"{server_key}:{user_py_key}"

    # 2. Use issued access token to hit protected endpoint
    r2 = client.get(
        "/messages",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )
    assert r2.status_code != 401




