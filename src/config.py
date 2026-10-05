"""Configuration module for PointsYeah MCP Middleware Server.

Loads settings from environment variables with safe defaults.
"""

from __future__ import annotations

import hmac
import os
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

# Load .env if present
load_dotenv()


class ServerConfig:
    """Server configuration settings."""

    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        """Reload configuration from environment variables."""
        # Server binding
        self.PORT: int = int(os.getenv("PORT", "8080"))
        self.HOST: str = os.getenv("HOST", "0.0.0.0")
        self.DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

        # PointsYeah upstream settings
        self.POINTSYEAH_BASE_URL: str = os.getenv(
            "POINTSYEAH_BASE_URL", "https://ai-api.pointsyeah.com"
        ).rstrip("/")
        # Default upstream API key for the server owner/admin
        self.DEFAULT_POINTSYEAH_API_KEY: Optional[str] = os.getenv(
            "DEFAULT_POINTSYEAH_API_KEY"
        )

        # Server authentication tokens
        self.SERVER_API_KEY: Optional[str] = os.getenv("SERVER_API_KEY")
        self.SERVER_API_KEYS_RAW: Optional[str] = os.getenv("SERVER_API_KEYS")

        # Rate limiting
        self.RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
        self.RATE_LIMIT_BURST: int = int(os.getenv("RATE_LIMIT_BURST", "20"))

        # CORS settings
        self.ALLOWED_ORIGINS_RAW: str = os.getenv("ALLOWED_ORIGINS", "*")

    def get_allowed_origins(self) -> List[str]:
        """Return list of allowed CORS origins."""
        raw = getattr(self, "ALLOWED_ORIGINS_RAW", "*")
        if not raw or raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    def get_authorized_tokens(self) -> Dict[str, str]:
        """Return mapping of token -> user_label for all authorized keys."""
        tokens: Dict[str, str] = {}

        # 1. Check single SERVER_API_KEY
        single_key = getattr(self, "SERVER_API_KEY", None)
        if single_key and single_key.strip():
            tokens[single_key.strip()] = "owner"

        # 2. Check comma-separated SERVER_API_KEYS
        raw_keys = getattr(self, "SERVER_API_KEYS_RAW", None)
        if raw_keys and raw_keys.strip():
            items = raw_keys.split(",")
            for item in items:
                item = item.strip()
                if not item:
                    continue
                if ":" in item:
                    label, token = item.split(":", 1)
                    token = token.strip()
                    label = label.strip()
                    if token:
                        tokens[token] = label
                else:
                    tokens[item] = f"user_{item[:6]}"

        return tokens

    def verify_server_token(self, provided_token: Optional[str]) -> Tuple[bool, Optional[str]]:
        """Perform timing-safe verification of server access token.

        Returns (is_authorized, user_label).
        """
        if not provided_token:
            return False, None

        provided_token = provided_token.strip()
        authorized_tokens = self.get_authorized_tokens()

        # If no tokens are configured, reject all requests in production mode
        if not authorized_tokens:
            if getattr(self, "DEBUG", False):
                return True, "debug_user"
            return False, None

        for authorized_token, label in authorized_tokens.items():
            if hmac.compare_digest(provided_token, authorized_token):
                return True, label

        return False, None


config = ServerConfig()
