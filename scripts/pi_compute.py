#!/usr/bin/env python3
"""
Wrapper script for pi that fetches models from the compute pool endpoint.

This script replaces the shell aliases and provides proper model discovery
from the VPS (fcc.guwj609.ccwu.cc) or local (127.0.0.1:8082) endpoints.

Usage:
    python pi_compute.py [vps|local] [model_name] [pi_args...]

    # List models from VPS
    python pi_compute.py vps --list

    # Use specific model from VPS
    python pi_compute.py vps claude-3-5-sonnet-20241022 "your prompt"

    # List models from local
    python pi_compute.py local --list

    # Use default model from local
    python pi_compute.py local "your prompt"

Environment variables:
    PI_VPS_URL: VPS endpoint (default: https://fcc.guwj609.ccwu.cc/v1)
    PI_LOCAL_URL: Local endpoint (default: http://127.0.0.1:8082/v1)
    PI_API_KEY: API key for both endpoints (default: freecc)
"""

import argparse
import os
import sys
import subprocess
import requests
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

# Default endpoints
DEFAULT_VPS_URL = "https://fcc.guwj609.ccwu.cc/v1"
DEFAULT_LOCAL_URL = "http://127.0.0.1:8082/v1"
DEFAULT_API_KEY = "freecc"

# Allow overriding via env
VPS_URL = os.environ.get("PI_VPS_URL", DEFAULT_VPS_URL)
LOCAL_URL = os.environ.get("PI_LOCAL_URL", DEFAULT_LOCAL_URL)
API_KEY = os.environ.get("PI_API_KEY", DEFAULT_API_KEY)


def fetch_models(url: str) -> List[Dict[str, Any]]:
    """Fetch available models from the endpoint."""
    try:
        response = requests.get(
            f"{url}/models",
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching models from {url}: {e}", file=sys.stderr)
        return []


def print_models(models: List[Dict[str, Any]], label: str):
    """Print models in a nice table format."""
    if not models:
        print(f"No models available at {label}")
        return

    print(f"\nAvailable models from {label}:")
    print("-" * 80)
    print(f"{'ID':<50} {'Display Name':<30}")
    print("-" * 80)
    for m in models:
        model_id = m.get('id', 'N/A')
        display_name = m.get('display_name', model_id)
        print(f"{model_id:<50} {display_name:<30}")
    print("-" * 80)


def select_model(models: List[Dict[str, Any]], preferred: Optional[str] = None) -> Optional[str]:
    """Select a model, either from preferred or first available."""
    if not models:
        return None

    if preferred:
        for m in models:
            if m['id'] == preferred:
                return preferred
        print(f"Warning: Model '{preferred}' not found, using first available", file=sys.stderr)

    return models[0]['id']


def run_pi(provider: str, model: str, base_url: str, api_key: str, args: List[str]) -> int:
    """Run pi with the specified configuration."""
    env = os.environ.copy()

    # Set provider-specific env vars for pi
    if provider == "anthropic":
        env["ANTHROPIC_API_KEY"] = api_key
        env["ANTHROPIC_BASE_URL"] = base_url
    else:  # openai
        env["OPENAI_API_KEY"] = api_key
        env["OPENAI_BASE_URL"] = base_url

    # Build command: pi --provider PROVIDER --model MODEL [args...]
    cmd = ["pi", "--provider", provider, "--model", model] + args

    try:
        result = subprocess.run(cmd, env=env)
        return result.returncode
    except FileNotFoundError:
        print("Error: 'pi' command not found. Please install pi first.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def main():
    # Parse args manually to handle --list before positional
    orig_argv = sys.argv[1:]

    list_mode = False
    endpoint = None
    model = None
    provider = None  # Will be auto-detected based on endpoint
    pi_args = []

    i = 0
    while i < len(orig_argv):
        arg = orig_argv[i]
        if arg in ("--list", "-l"):
            list_mode = True
        elif arg == "--provider" and i + 1 < len(orig_argv):
            provider = orig_argv[i + 1]
            i += 1
        elif not arg.startswith("-"):
            if endpoint is None:
                endpoint = arg
            elif model is None:
                model = arg
            else:
                pi_args = orig_argv[i:]
                break
        i += 1

    if endpoint not in ("vps", "local"):
        print("Error: First argument must be 'vps' or 'local'", file=sys.stderr)
        print("Usage: pi_compute.py [vps|local] [model] [--provider NAME] [--list] [pi args...]", file=sys.stderr)
        return 1

    # Determine URL and provider based on endpoint
    if endpoint == "vps":
        url = VPS_URL
        label = "VPS (fcc.guwj609.ccwu.cc)"
        # VPS uses Anthropic format
        provider = provider or "anthropic"
    else:
        url = LOCAL_URL
        label = "Local (127.0.0.1:8082)"
        # Local servers also use Anthropic format (Free Claude Code server)
        provider = provider or "anthropic"

    # Fetch models
    print(f"Fetching models from {label}...", file=sys.stderr)
    models = fetch_models(url)

    if list_mode:
        print_models(models, label)
        return 0

    if not models:
        print(f"Error: No models available from {label}", file=sys.stderr)
        if endpoint == "local":
            print("Hint: Is your local inference server running at 127.0.0.1:8082?", file=sys.stderr)
        return 1

    # Select model
    model_id = select_model(models, model)
    if not model_id:
        return 1

    print(f"Using model: {model_id} (provider: {provider})", file=sys.stderr)

    # Run pi
    return run_pi(provider, model_id, url, API_KEY, pi_args)


if __name__ == "__main__":
    sys.exit(main())
