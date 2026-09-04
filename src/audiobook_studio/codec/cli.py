"""Command-line interface for the neural audio codec.

Examples
--------
    # Compress a WAV to a neural-codec token container
    python -m audiobook_studio.codec.cli compress speech.wav speech.nac

    # Decompress back to a WAV
    python -m audiobook_studio.codec.cli decompress speech.nac speech_out.wav

    # Show size-reduction for every available codec
    python -m audiobook_studio.codec.cli benchmark speech.wav
"""

from __future__ import annotations

import argparse
import json
import sys

from .engine import benchmark, compress_audio_file, decompress_audio_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codec", description="Neural audio codec toolkit")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_c = sub.add_parser("compress", help="compress a WAV to a token container")
    p_c.add_argument("input")
    p_c.add_argument("output")
    p_c.add_argument("--method", default="neural", choices=["neural", "opus"])

    p_d = sub.add_parser("decompress", help="restore a WAV from a container")
    p_d.add_argument("input")
    p_d.add_argument("output")
    p_d.add_argument("--method", default="neural", choices=["neural", "opus"])

    p_b = sub.add_parser("benchmark", help="report size reduction per codec")
    p_b.add_argument("input")
    p_b.add_argument("--opus-bitrate", default="16k")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "compress":
            stats = compress_audio_file(args.input, args.output, method=args.method)
            print(json.dumps(stats, indent=2))
        elif args.cmd == "decompress":
            decompress_audio_file(args.output, args.input, method=args.method)
            print(f"wrote {args.output}")
        elif args.cmd == "benchmark":
            print(json.dumps(benchmark(args.input, opus_bitrate=args.opus_bitrate), indent=2))
    except Exception as exc:  # surface a clean message for missing deps
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
