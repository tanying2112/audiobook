#!/usr/bin/env python3
"""Password hash migration script for SEC-002.

This script provides transparent password hash migration from legacy SHA-256
to bcrypt on user login. It should be called during the authentication flow
when a user with a legacy hash successfully authenticates.

Usage:
    from src.audiobook_studio.scripts.migrate_passwords import migrate_password_on_login

    user = authenticate_user(username, password)  # Uses legacy verification
    if user and not user.password_migrated:
        migrate_password_on_login(user, plain_password, db_session)
"""

import logging
from typing import Optional

import bcrypt

from src.audiobook_studio.config import get_settings
from src.audiobook_studio.database import SessionLocal
from src.audiobook_studio.models.user import User

logger = logging.getLogger(__name__)


def is_legacy_hash(hashed_password: str) -> bool:
    """Check if a password hash uses legacy SHA-256 format.

    Legacy formats:
    - sha256$salt$hash (custom implementation)
    - $5$... (passlib sha256_crypt)

    Returns:
        True if the hash is a legacy format, False if bcrypt.
    """
    return hashed_password.startswith("sha256$") or hashed_password.startswith("$5$")


def is_bcrypt_hash(hashed_password: str) -> bool:
    """Check if a password hash is bcrypt format.

    Returns:
        True if the hash starts with $2b$, $2a$, or $2y$ (bcrypt prefixes).
    """
    return hashed_password.startswith("$2")


def migrate_password_on_login(
    user: User,
    plain_password: str,
    db_session=None,
) -> bool:
    """Migrate a user's password hash from legacy to bcrypt on successful login.

    This function is called after a user successfully authenticates with a
    legacy hash. It re-hashes the plaintext password with bcrypt and updates
    the database.

    Args:
        user: The User ORM instance.
        plain_password: The plaintext password provided by the user at login.
        db_session: Optional database session. If not provided, creates one.

    Returns:
        True if migration was performed, False if already migrated or not needed.
    """
    if not user or not plain_password:
        logger.warning("migrate_password_on_login: missing user or password")
        return False

    if user.password_migrated:
        logger.debug(f"User {user.username} already migrated, skipping")
        return False

    if not is_legacy_hash(user.hashed_password):
        logger.debug(f"User {user.username} already has bcrypt hash, marking migrated")
        user.password_migrated = True
        return False

    # Re-hash with bcrypt
    settings = get_settings()
    password_bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    new_hash = bcrypt.hashpw(password_bytes, salt).decode("utf-8")

    # Update user record
    user.hashed_password = new_hash
    user.password_migrated = True

    # Commit if we own the session
    own_session = db_session is None
    if own_session:
        db_session = SessionLocal()

    try:
        db_session.add(user)
        db_session.commit()
        logger.info(f"Successfully migrated password hash for user {user.username}")
        return True
    except Exception as e:
        db_session.rollback()
        logger.error(f"Failed to migrate password for user {user.username}: {e}")
        raise
    finally:
        if own_session:
            db_session.close()


def migrate_all_passwords(db_session=None) -> tuple[int, int]:
    """Batch migrate all legacy password hashes to bcrypt.

    This is a one-time migration script for existing users. It requires
    plaintext passwords, so it can only be run in controlled scenarios
    (e.g., during a planned migration with user cooperation).

    Note: This function requires access to plaintext passwords, which
    are not stored. In practice, migration happens transparently on
    next login via migrate_password_on_login().

    Returns:
        Tuple of (migrated_count, skipped_count)
    """
    own_session = db_session is None
    if own_session:
        db_session = SessionLocal()

    migrated = 0
    skipped = 0

    try:
        users = db_session.query(User).filter(User.password_migrated == False).all()  # noqa: E712
        for user in users:
            if is_legacy_hash(user.hashed_password):
                # Cannot migrate without plaintext password - skip
                logger.warning(
                    f"Cannot auto-migrate user {user.username}: legacy hash but no plaintext available. "
                    f"Will migrate on next successful login."
                )
                skipped += 1
            else:
                # Already bcrypt but not marked
                user.password_migrated = True
                db_session.add(user)
                migrated += 1

        db_session.commit()
        logger.info(f"Batch migration complete: {migrated} marked migrated, {skipped} skipped (need login)")
        return migrated, skipped
    except Exception as e:
        db_session.rollback()
        logger.error(f"Batch migration failed: {e}")
        raise
    finally:
        if own_session:
            db_session.close()


def verify_and_migrate(username: str, plain_password: str) -> Optional[User]:
    """Verify user password and migrate if legacy hash.

    This is the main entry point for the authentication flow. It:
    1. Looks up user by username
    2. Verifies password (supports both legacy and bcrypt)
    3. Migrates to bcrypt if legacy hash was used
    4. Returns authenticated user or None

    Args:
        username: Username or email
        plain_password: Plaintext password from login form

    Returns:
        User object if authentication successful, None otherwise.
    """
    db = SessionLocal()
    try:
        # Look up user by username or email
        user = db.query(User).filter(
            (User.username == username) | (User.email == username)
        ).first()

        if not user:
            return None

        # Verify password (using jwt_handler which handles both formats during transition)
        from src.audiobook_studio.auth.jwt_handler import verify_password

        if not verify_password(plain_password, user.hashed_password):
            return None

        # Check if migration needed
        if not user.password_migrated and is_legacy_hash(user.hashed_password):
            migrate_password_on_login(user, plain_password, db)

        return user
    finally:
        db.close()


if __name__ == "__main__":
    # CLI for manual batch migration (requires plaintext passwords - not typical)
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        print("Starting batch password migration...")
        migrated, skipped = migrate_all_passwords()
        print(f"Done: {migrated} migrated, {skipped} skipped (require login)")
    else:
        print("Usage: python -m src.audiobook_studio.scripts.migrate_passwords batch")
        print("  (batch mode marks already-bcrypt hashes as migrated)")
        print()
        print("Note: Legacy hashes require user login to migrate (transparent upgrade).")