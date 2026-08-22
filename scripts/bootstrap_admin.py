#!/usr/bin/env python3
"""Bootstrap script to create the initial superuser admin account.

Usage:
    python scripts/bootstrap_admin.py --username admin --email admin@example.com --password admin123
    python scripts/bootstrap_admin.py --interactive
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.audiobook_studio.auth.rbac import RBACManager, get_rbac_manager
from src.audiobook_studio.database import SessionLocal


def create_admin(username: str, email: str, password: str, full_name: str = None) -> None:
    """Create or update admin user."""
    db = SessionLocal()
    try:
        rbac = get_rbac_manager(db)

        # Check if user already exists
        existing = rbac.get_user_by_username(username)
        if existing:
            print(f"User '{username}' already exists (id={existing.id})")
            if not existing.is_superuser:
                existing.is_superuser = True
                db.commit()
                print(f"  → Updated to superuser")
            return

        # Create new superuser
        user = rbac.create_user(
            email=email,
            username=username,
            password=password,
            full_name=full_name or username,
        )
        # Promote to superuser
        user.is_superuser = True
        db.commit()
        print(f"✓ Created superuser: {username} (id={user.id})")

    except Exception as e:
        db.rollback()
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Bootstrap initial admin user")
    parser.add_argument("--username", default="admin", help="Admin username (default: admin)")
    parser.add_argument("--email", default="admin@example.com", help="Admin email")
    parser.add_argument("--password", help="Admin password (required unless --interactive)")
    parser.add_argument("--full-name", help="Admin full name")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")

    args = parser.parse_args()

    if args.interactive:
        username = input("Username [admin]: ").strip() or "admin"
        email = input("Email [admin@example.com]: ").strip() or "admin@example.com"
        import getpass
        password = getpass.getpass("Password: ").strip()
        password_confirm = getpass.getpass("Confirm password: ").strip()
        if password != password_confirm:
            print("✗ Passwords do not match", file=sys.stderr)
            sys.exit(1)
        full_name = input("Full name (optional): ").strip() or None
    else:
        username = args.username
        email = args.email
        password = args.password
        full_name = args.full_name

        if not password:
            print("✗ --password is required (or use --interactive)", file=sys.stderr)
            sys.exit(1)

    create_admin(username, email, password, full_name)
    print("\n✓ Bootstrap complete! You can now log in at /login")


if __name__ == "__main__":
    main()