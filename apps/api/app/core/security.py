"""Shared auth constants used across the API layer.

The access token is never stored server-side or in a cookie: it is returned
once in the JSON response body and kept in memory on the frontend. Only the
refresh token is persisted (as a revocable session row) and cookie-stored.
"""

REFRESH_TOKEN_COOKIE_NAME = "refresh_token"
BEARER_PREFIX = "Bearer "
