#!/usr/bin/env python3
"""
Generate cryptographically secure secrets for Audiobook Studio.

Usage:
    python scripts/generate_secrets.py
    python scripts/generate_secrets.py --jwt-secret
    python scripts/generate_secrets.py --all
    python scripts/generate_secrets.py --format env  # Output as KEY=value pairs
"""
import argparse
import base64
import secrets
import sys
from pathlib import Path


def generate_jwt_secret(bits: int = 256) -> str:
    """Generate a URL-safe base64 encoded secret with specified entropy."""
    bytes_needed = bits // 8
    raw = secrets.token_bytes(bytes_needed)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_secret_key(bits: int = 256) -> str:
    """Alias for JWT secret (same entropy requirement)."""
    return generate_jwt_secret(bits)


def generate_fernet_key() -> str:
    """Generate a Fernet-compatible key (32 bytes URL-safe base64)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def calculate_entropy(b64_string: str) -> float:
    """Calculate Shannon entropy of a base64 string."""
    import math
    from collections import Counter

    counter = Counter(b64_string)
    length = len(b64_string)
    entropy = 0.0
    for count in counter.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy * length


def main():
    parser = argparse.ArgumentParser(description="Generate secure secrets for Audiobook Studio")
    parser.add_argument("--jwt-secret", action="store_true", help="Generate JWT_SECRET_KEY only")
    parser.add_argument("--secret-key", action="store_true", help="Generate SECRET_KEY only (alias)")
    parser.add_argument("--fernet-key", action="store_true", help="Generate Fernet key for encryption")
    parser.add_argument("--all", action="store_true", help="Generate all secrets")
    parser.add_argument("--format", choices=["env", "json", "plain"], default="plain", help="Output format")
    parser.add_argument("--bits", type=int, default=256, help="Entropy bits (default: 256)")
    parser.add_argument("--verify", type=str, help="Verify entropy of existing secret")

    args = parser.parse_args()

    if args.verify:
        entropy = calculate_entropy(args.verify)
        print(f"Entropy: {entropy:.2f} bits")
        print(f"Status: {'✅ PASS (≥256 bits)' if entropy >= 256 else '❌ FAIL (<256 bits)'}")
        sys.exit(0 if entropy >= 256 else 1)

    results = {}

    if args.all or args.jwt_secret or not any([args.jwt_secret, args.secret_key, args.fernet_key, args.all]):
        # Default: generate JWT secret
        jwt_secret = generate_jwt_secret(args.bits)
        results["JWT_SECRET_KEY"] = jwt_secret
        results["SECRET_KEY"] = jwt_secret  # Alias for compatibility
        generation_entropy = args.bits
        measured_entropy = calculate_entropy(jwt_secret)
        if args.format == "plain":
            print(f"JWT_SECRET_KEY: {jwt_secret}")
            print(f"  Generation entropy: {generation_entropy} bits (✅ PASS by construction)")
            print(f"  Measured Shannon entropy: {measured_entropy:.1f} bits (sample: {len(jwt_secret)} chars)")

    if args.all or args.fernet_key:
        fernet_key = generate_fernet_key()
        results["FERNET_KEY"] = fernet_key
        if args.format == "plain":
            print(f"FERNET_KEY: {fernet_key}")

    if args.format == "env":
        for key, value in results.items():
            print(f"{key}={value}")
    elif args.format == "json":
        import json

        print(json.dumps(results, indent=2))

    # Also show .env snippet (plain format only)
    if args.format == "plain":
        print("\n# Add to .env file:")
        for key, value in results.items():
            print(f"{key}={value}")


if __name__ == "__main__":
    main()
