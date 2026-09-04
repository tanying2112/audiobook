#!/usr/bin/env bash
# scripts/decrypt_env.sh — Decrypt .env.encrypted to .env using sops + age
#
# Usage: scripts/decrypt_env.sh [--output .env] [--age-key-file PATH] [--encrypted-file PATH]
#
# Environment variables:
#   SOPS_AGE_KEY_FILE    Path to age private key file (default: .agekey)
#   ENCRYPTED_FILE       Path to encrypted file (default: .env.encrypted)
#   OUTPUT_FILE          Output file path (default: .env)
#
# Requires: sops, age
#
# CI usage (GitHub Actions):
#   - Store age private key as repository secret AGE_KEY
#   - In workflow: echo "${{ secrets.AGE_KEY }}" > .agekey && scripts/decrypt_env.sh
#
# Local usage:
#   - Place age private key at .agekey (gitignored)
#   - Run: scripts/decrypt_env.sh

set -euo pipefail

# Default paths
AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-.agekey}"
ENCRYPTED_FILE="${ENCRYPTED_FILE:-.env.encrypted}"
OUTPUT_FILE="${OUTPUT_FILE:-.env}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --age-key-file)
            AGE_KEY_FILE="$2"
            shift 2
            ;;
        --encrypted-file)
            ENCRYPTED_FILE="$2"
            shift 2
            ;;
        --output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--age-key-file PATH] [--encrypted-file PATH] [--output PATH]"
            echo ""
            echo "Decrypt .env.encrypted to .env using sops + age"
            echo ""
            echo "Options:"
            echo "  --age-key-file PATH     Path to age private key (default: .agekey)"
            echo "  --encrypted-file PATH   Path to encrypted file (default: .env.encrypted)"
            echo "  --output PATH           Output file path (default: .env)"
            echo "  --help, -h              Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# Check prerequisites
for cmd in sops age; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: '$cmd' not found in PATH. Install with: brew install sops age" >&2
        exit 1
    fi
done

# Check age key file
if [[ ! -f "$AGE_KEY_FILE" ]]; then
    echo "Error: Age key file not found: $AGE_KEY_FILE" >&2
    echo "Set SOPS_AGE_KEY_FILE or place key at .agekey" >&2
    exit 1
fi

# Check encrypted file
if [[ ! -f "$ENCRYPTED_FILE" ]]; then
    echo "Error: Encrypted file not found: $ENCRYPTED_FILE" >&2
    exit 1
fi

# Decrypt
echo "Decrypting $ENCRYPTED_FILE -> $OUTPUT_FILE"
if ! SOPS_AGE_KEY_FILE="$AGE_KEY_FILE" sops --input-type dotenv --output-type dotenv --decrypt "$ENCRYPTED_FILE" > "$OUTPUT_FILE"; then
    echo "Error: Decryption failed" >&2
    exit 1
fi

# Secure permissions
chmod 600 "$OUTPUT_FILE"
echo "Decrypted to $OUTPUT_FILE (mode 600)"