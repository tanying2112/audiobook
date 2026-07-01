import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from jose import JWTError, jwt
from pydantic import BaseModel

from src.audiobook_studio.config import get_settings

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    bcrypt = None


class TokenPayload(BaseModel):
    """JWT token payload structure."""

    sub: str  # user id
    username: str
    roles: List[str] = []
    permissions: List[str] = []
    exp: int
    iat: int
    type: str = "access"


class JWTHandler:
    """Handles JWT token creation, validation, and decoding."""

    def __init__(self):
        self.settings = get_settings()
        self.secret_key = self.settings.JWT_SECRET_KEY
        self.algorithm = self.settings.JWT_ALGORITHM
        self.access_token_expire_minutes = self.settings.ACCESS_TOKEN_EXPIRE_MINUTES
        self.refresh_token_expire_days = self.settings.REFRESH_TOKEN_EXPIRE_DAYS

        # Password hashing — bcrypt preferred; fall back to SHA-256 if unavailable
        # Install bcrypt for production: pip install bcrypt
        if not BCRYPT_AVAILABLE:
            import warnings

            warnings.warn(
                "bcrypt is not installed; falling back to SHA-256 hashing. "
                "Install bcrypt for secure password hashing: pip install bcrypt",
                UserWarning,
                stacklevel=2,
            )

    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt (or SHA-256 fallback)."""
        password_bytes = password.encode('utf-8')
        if BCRYPT_AVAILABLE:
            salt = bcrypt.gensalt(rounds=12)
            hashed = bcrypt.hashpw(password_bytes, salt)
            return hashed.decode('utf-8')
        # Fallback: SHA-256 + salt (not as secure as bcrypt)
        salt = os.urandom(32)
        hashed = hashlib.sha256(salt + password_bytes).digest()
        return f"sha256${salt.hex()}${hashed.hex()}"

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        password_bytes = plain_password.encode('utf-8')
        if BCRYPT_AVAILABLE and not hashed_password.startswith("sha256$"):
            hashed_bytes = hashed_password.encode('utf-8')
            return bcrypt.checkpw(password_bytes, hashed_bytes)
        if hashed_password.startswith("sha256$"):
            parts = hashed_password.split("$")
            if len(parts) != 3:
                return False
            salt = bytes.fromhex(parts[1])
            expected = hashlib.sha256(salt + password_bytes).digest()
            return expected.hex() == parts[2]
        return False

    def create_access_token(
        self,
        user_id: int,
        username: str,
        roles: List[str] = None,
        permissions: List[str] = None,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """Create a new access token."""
        roles = roles or []
        permissions = permissions or []

        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                minutes=self.access_token_expire_minutes
            )

        to_encode = {
            "sub": str(user_id),
            "username": username,
            "roles": roles,
            "permissions": permissions,
            "exp": int(expire.timestamp()),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "type": "access",
        }

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def create_refresh_token(
        self,
        user_id: int,
        username: str,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """Create a new refresh token."""
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                days=self.refresh_token_expire_days
            )

        to_encode = {
            "sub": str(user_id),
            "username": username,
            "exp": int(expire.timestamp()),
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "type": "refresh",
        }

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def create_token_pair(
        self,
        user_id: int,
        username: str,
        roles: List[str] = None,
        permissions: List[str] = None,
    ) -> Dict[str, str]:
        """Create both access and refresh tokens."""
        access_token = self.create_access_token(user_id, username, roles, permissions)
        refresh_token = self.create_refresh_token(user_id, username)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.access_token_expire_minutes * 60,
        }

    def decode_token(self, token: str) -> Dict[str, Any]:
        """Decode and validate a JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except JWTError as e:
            raise ValueError(f"Invalid token: {e}")

    def verify_token(self, token: str) -> bool:
        """Verify a token is valid."""
        try:
            self.decode_token(token)
            return True
        except ValueError:
            return False

    def get_token_payload(self, token: str) -> Optional[TokenPayload]:
        """Get typed token payload."""
        try:
            payload = self.decode_token(token)
            return TokenPayload(**payload)
        except (ValueError, JWTError):
            return None

    def is_token_expired(self, token: str) -> bool:
        """Check if token is expired."""
        payload = self.get_token_payload(token)
        if not payload:
            return True
        return datetime.now(timezone.utc).timestamp() > payload.exp

    def is_refresh_token(self, token: str) -> bool:
        """Check if token is a refresh token."""
        payload = self.get_token_payload(token)
        if not payload:
            return False
        return payload.type == "refresh"

    def hash_password(self, password: str) -> str:
        """Hash a password."""
        return self._hash_password(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        return self._verify_password(plain_password, hashed_password)

    def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        """Create a new access token from a valid refresh token."""
        if not self.is_refresh_token(refresh_token):
            return None

        payload = self.get_token_payload(refresh_token)
        if not payload:
            return None

        return self.create_access_token(
            user_id=int(payload.sub),
            username=payload.username,
            roles=payload.roles,
            permissions=payload.permissions,
        )


# Global JWT handler instance
jwt_handler = JWTHandler()


# Convenience functions
def create_access_token(
    user_id: int,
    username: str,
    roles: List[str] = None,
    permissions: List[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create an access token."""
    return jwt_handler.create_access_token(
        user_id, username, roles, permissions, expires_delta
    )


def create_refresh_token(
    user_id: int,
    username: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a refresh token."""
    return jwt_handler.create_refresh_token(user_id, username, expires_delta)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode a token."""
    return jwt_handler.decode_token(token)


def verify_token(token: str) -> bool:
    """Verify a token."""
    return jwt_handler.verify_token(token)


def hash_password(password: str) -> str:
    """Hash a password."""
    return jwt_handler.hash_password(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password."""
    return jwt_handler.verify_password(plain_password, hashed_password)
