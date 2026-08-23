#!/usr/bin/env python3
"""
Deploy all v0.4 Modal services.

This script deploys the following services to Modal:
1. VoxCPM2 TTS Server (modal_voxcpm2_server.py)
2. XTTS-v2 Clone Server (modal_xtts_v2_server.py)
3. CosyVoice Stream Server (modal_cosyvoice_stream_server.py)
4. Seed-TTS Stream Server (modal_seed_tts_stream_server.py)
5. MeloTTS Stream Server (modal_melotts_stream_server.py)
6. OpenVoice V2 Clone Server (modal_openvoice_v2_server.py)
7. CosyVoice Clone Server (modal_cosyvoice_clone_server.py)

Usage:
    python scripts/deploy_v04_modal.py --all
    python scripts/deploy_v04_modal.py --service voxcpm2
    python scripts/deploy_v04_modal.py --list
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

SERVICES = {
    "voxcpm2": {
        "file": "modal_voxcpm2_server.py",
        "app_name": "voxcpm2-tts-server",
        "description": "VoxCPM2 TTS Server",
    },
    "xtts_v2": {
        "file": "modal_xtts_v2_server.py",
        "app_name": "xtts-v2-clone-server",
        "description": "XTTS-v2 Zero-Shot Clone Server",
    },
    "cosyvoice_stream": {
        "file": "modal_cosyvoice_stream_server.py",
        "app_name": "cosyvoice-stream-server",
        "description": "CosyVoice Streaming TTS Server",
    },
    "seed_tts_stream": {
        "file": "modal_seed_tts_stream_server.py",
        "app_name": "seed-tts-stream-server",
        "description": "Seed-TTS Streaming TTS Server",
    },
    "melotts_stream": {
        "file": "modal_melotts_stream_server.py",
        "app_name": "melotts-stream-server",
        "description": "MeloTTS Streaming TTS Server",
    },
    "openvoice_v2": {
        "file": "modal_openvoice_v2_server.py",
        "app_name": "openvoice-v2-clone-server",
        "description": "OpenVoice V2 Zero-Shot Clone Server",
    },
    "cosyvoice_clone": {
        "file": "modal_cosyvoice_clone_server.py",
        "app_name": "cosyvoice-clone-server",
        "description": "CosyVoice Zero-Shot Clone Server",
    },
}


def check_modal_installed() -> bool:
    """Check if modal CLI is installed."""
    try:
        subprocess.run(["modal", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def check_modal_auth() -> bool:
    """Check if modal is authenticated."""
    try:
        result = subprocess.run(["modal", "token", "show"], capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False


def deploy_service(service_key: str, dry_run: bool = False) -> bool:
    """Deploy a single service to Modal."""
    service = SERVICES[service_key]
    file_path = PROJECT_ROOT / service["file"]
    
    if not file_path.exists():
        print(f"❌ Service file not found: {file_path}")
        return False
    
    print(f"\n🚀 Deploying {service['description']} ({service_key})...")
    print(f"   File: {service['file']}")
    print(f"   App: {service['app_name']}")
    
    if dry_run:
        print("   [DRY RUN] Would run: modal deploy " + service["file"])
        return True
    
    try:
        # Change to project root and deploy
        result = subprocess.run(
            ["modal", "deploy", service["file"]],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout
        )
        
        if result.returncode == 0:
            print(f"   ✅ Deployed successfully!")
            # Extract URL from output
            for line in result.stdout.split('\n'):
                if 'https://' in line and 'modal.run' in line:
                    print(f"   📡 Endpoint: {line.strip()}")
            return True
        else:
            print(f"   ❌ Deployment failed:")
            print(f"   {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"   ❌ Deployment timed out (10 min)")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def deploy_all(dry_run: bool = False, services: list = None) -> dict:
    """Deploy all or selected services."""
    if services is None:
        services = list(SERVICES.keys())
    
    results = {}
    for service_key in services:
        if service_key not in SERVICES:
            print(f"⚠️  Unknown service: {service_key}")
            results[service_key] = False
            continue
        results[service_key] = deploy_service(service_key, dry_run)
    
    return results


def list_services():
    """List all available services."""
    print("\n📋 Available v0.4 Modal Services:")
    print("=" * 60)
    for key, info in SERVICES.items():
        status = "✅" if (PROJECT_ROOT / info["file"]).exists() else "❌"
        print(f"  {status} {key:20} - {info['description']}")
        print(f"      File: {info['file']}")
        print(f"      App: {info['app_name']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Deploy v0.4 Modal services")
    parser.add_argument("--all", action="store_true", help="Deploy all services")
    parser.add_argument("--service", "-s", action="append", help="Deploy specific service(s)")
    parser.add_argument("--list", "-l", action="store_true", help="List available services")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deployed without deploying")
    
    args = parser.parse_args()
    
    if args.list:
        list_services()
        return
    
    # Check prerequisites
    if not check_modal_installed():
        print("❌ Modal CLI not installed. Install with: pip install modal")
        print("   Or: uv add modal (if using uv)")
        sys.exit(1)
    
    if not check_modal_auth():
        print("❌ Modal not authenticated. Run: modal setup")
        sys.exit(1)
    
    print("✅ Modal CLI ready")
    
    if args.all:
        print("\n🚀 Deploying ALL v0.4 services...")
        results = deploy_all(dry_run=args.dry_run)
    elif args.service:
        print(f"\n🚀 Deploying selected services: {', '.join(args.service)}")
        results = deploy_all(dry_run=args.dry_run, services=args.service)
    else:
        parser.print_help()
        return
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Deployment Summary:")
    success = sum(1 for v in results.values() if v)
    total = len(results)
    for key, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {key}")
    print(f"\nTotal: {success}/{total} succeeded")
    
    if success < total and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
