"""Development server entry point for Audiobook Studio.

Run with:
    python -m uvicorn src.audiobook_studio.main:app --reload
or simply:
    python server.py
"""

import subprocess
import sys


def main() -> None:
    # Use uvicorn to run the FastAPI app
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.audiobook_studio.main:app",
                "--reload",
            ],
            check=True,
        )
    except FileNotFoundError:
        print("uvicorn is not installed. Install it with 'pip install uvicorn'.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to start server: {e}")


if __name__ == "__main__":
    main()
