"""Command line interface for adaptivestego.

    python -m adaptivestego gui
    python -m adaptivestego embed   -c cover.png -o stego.png -t "secret" --key pw
    python -m adaptivestego extract -i stego.png --key pw
    python -m adaptivestego capacity -i cover.png --method adaptive
    python -m adaptivestego analyze  -i stego.png
    python -m adaptivestego metrics  -c cover.png -s stego.png
    python -m adaptivestego attack   -i stego.png -o attacked.png --attack jpeg:quality=90
    python -m adaptivestego selftest
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from . import __version__, analysis, attacks, metrics
from .api import capacity, embed, extract
from .codecs import codec_names
from .cost_models import cost_model_names
from .exceptions import StegoError
from .image_io import read_image, write_image
from .maps import MAP_KINDS


def _force_utf8_output() -> None:
    """Make stdout and stderr accept any Unicode.

    The Windows console defaults to a legacy code page, and printing a
    recovered Cyrillic or CJK message would raise UnicodeEncodeError.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - exotic streams
                pass


# ---------------------------------------------------------------------------
# argument helpers
# ---------------------------------------------------------------------------
def _add_embed_params(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--method", default="adaptive", choices=codec_names(),
                        help="embedding method (default: adaptive)")
    parser.add_argument("--key", default=None,
                        help="key that scatters the positions (it does not encrypt)")
    parser.add_argument("--bits", type=int, default=1, dest="bits_per_sample",
                        choices=(1, 2, 3, 4), help="bits per sample (default: 1)")
    parser.add_argument("--map", default="combined", dest="map_kind",
                        choices=list(MAP_KINDS),
                        help="complexity map used by the adaptive methods")
    parser.add_argument("--band-bits", type=int, default=6, dest="band_bits",
                        help="quantisation of the complexity map in bits (default: 6)")
    parser.add_argument("--map-mask-bits", type=int, default=None,
                        dest="map_mask_bits",
                        help="build the map from bits above this position (ablation)")
    parser.add_argument("--mode", default=None, choices=("replace", "match"),
                        help="override how a bit is written")
    parser.add_argument("--stc-height", type=int, default=8, dest="stc_height",
                        help="trellis height for syndrome coding (default: 8)")
    parser.add_argument("--cost-gamma", type=float, default=1.0, dest="cost_gamma",
                        help="how sharply syndrome coding prefers texture")
    parser.add_argument("--cost-model", default=None, dest="cost_model",
                        choices=cost_model_names(),
                        help="override the cost model of a syndrome-coded method")
    parser.add_argument("--channels", default=None,
                        help="comma separated channels, e.g. 2 or 0,2 (default: all)")
    parser.add_argument("--grayscale", action="store_true",
                        help="work on a single grayscale channel")
    parser.add_argument("--password", nargs="?", const="", default=None,
                        help="encrypt with AES-256-GCM; without a value it is prompted")
    parser.add_argument("--password-env", default=None,
                        help="read the password from an environment variable")


def _params_from_args(args) -> dict:
    kwargs = {
        "method": args.method,
        "key": args.key,
        "bits_per_sample": args.bits_per_sample,
        "map_kind": args.map_kind,
        "band_bits": args.band_bits,
    }
    if args.mode:
        kwargs["mode"] = args.mode
    if args.map_mask_bits is not None:
        kwargs["map_mask_bits"] = args.map_mask_bits
    kwargs["stc_height"] = args.stc_height
    kwargs["cost_gamma"] = args.cost_gamma
    if args.cost_model:
        kwargs["cost_model"] = args.cost_model
    if args.channels:
        kwargs["channels"] = tuple(int(c) for c in args.channels.split(","))
    return kwargs


def _password(args) -> str | None:
    if args.password_env:
        value = os.environ.get(args.password_env)
        if value is None:
            raise StegoError(f"environment variable {args.password_env} is not set")
        return value
    if args.password is None:
        return None
    return args.password or getpass.getpass("Password: ")


def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=float))


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_embed(args) -> int:
    if args.text is not None:
        message = args.text
    elif args.message_file:
        with open(args.message_file, encoding="utf-8") as f:
            message = f.read()
    else:
        message = sys.stdin.read()

    img = read_image(args.cover, grayscale=args.grayscale)
    result = embed(img, message, password=_password(args),
                   compress=not args.no_compress, ecc_nsym=args.ecc,
                   **_params_from_args(args))
    write_image(args.out, result.stego)
    info = result.summary()
    info["output"] = args.out
    _dump(info)
    return 0


def cmd_extract(args) -> int:
    img = read_image(args.image, grayscale=args.grayscale)
    text = extract(img, password=_password(args), **_params_from_args(args))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"message written to {args.out} ({len(text)} characters)",
              file=sys.stderr)
    else:
        sys.stdout.write(text)
        if text and not text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def cmd_capacity(args) -> int:
    img = read_image(args.image, grayscale=args.grayscale)
    _dump(capacity(img, password=_password(args), ecc_nsym=args.ecc,
                   **_params_from_args(args)))
    return 0


def cmd_analyze(args) -> int:
    img = read_image(args.image, grayscale=args.grayscale)
    _dump({"image": args.image, **analysis.quick_report(img)})
    return 0


def cmd_metrics(args) -> int:
    cover = read_image(args.cover, grayscale=args.grayscale)
    stego = read_image(args.stego, grayscale=args.grayscale)
    _dump(metrics.quality_report(cover, stego))
    return 0


def cmd_attack(args) -> int:
    img = read_image(args.image, grayscale=args.grayscale)
    out = attacks.apply_attack(img, args.attack)
    write_image(args.out, out, allow_lossy=True)
    _dump({"attack": args.attack, "output": args.out,
           **metrics.quality_report(img, out)})
    return 0


def cmd_methods(_args) -> int:
    _dump({"methods": codec_names(), "maps": list(MAP_KINDS),
           "cost_models": cost_model_names(),
           "attacks": attacks.attack_names()})
    return 0


def cmd_selftest(args) -> int:
    from .selftest import run_selftest

    report = run_selftest(verbose=not args.json)
    if args.json:
        _dump(report)
    return 0 if report["digest_matches"] and not report["problems"] else 1


def cmd_gui(_args) -> int:
    from .gui import main as gui_main

    return gui_main()


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adaptivestego",
        description="Adaptive image steganography and steganalysis")
    parser.add_argument("--version", action="version",
                        version=f"adaptivestego {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("gui", help="open the desktop interface")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("embed", help="hide a message inside an image")
    p.add_argument("-c", "--cover", required=True, help="cover image")
    p.add_argument("-o", "--out", required=True,
                   help="where to write the stego image (PNG or BMP)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("-t", "--text", help="message text")
    group.add_argument("-f", "--message-file", help="UTF-8 file holding the message")
    p.add_argument("--ecc", type=int, default=0,
                   help="Reed-Solomon parity bytes per block (0 disables ECC)")
    p.add_argument("--no-compress", action="store_true", help="do not zlib the payload")
    _add_embed_params(p)
    p.set_defaults(func=cmd_embed)

    p = sub.add_parser("extract", help="recover a message")
    p.add_argument("-i", "--image", required=True)
    p.add_argument("-o", "--out", help="file for the message (stdout otherwise)")
    _add_embed_params(p)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("capacity", help="how much data an image can hide")
    p.add_argument("-i", "--image", required=True)
    p.add_argument("--ecc", type=int, default=0)
    _add_embed_params(p)
    p.set_defaults(func=cmd_capacity)

    p = sub.add_parser("analyze", help="classical steganalysis (chi2, SPA)")
    p.add_argument("-i", "--image", required=True)
    p.add_argument("--grayscale", action="store_true")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("metrics", help="PSNR and SSIM between cover and stego")
    p.add_argument("-c", "--cover", required=True)
    p.add_argument("-s", "--stego", required=True)
    p.add_argument("--grayscale", action="store_true")
    p.set_defaults(func=cmd_metrics)

    p = sub.add_parser("attack", help="apply a distortion to an image")
    p.add_argument("-i", "--image", required=True)
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--attack", required=True,
                   help="for example jpeg:quality=90 or noise:sigma=2")
    p.add_argument("--grayscale", action="store_true")
    p.set_defaults(func=cmd_attack)

    p = sub.add_parser("methods", help="list methods, maps and attacks")
    p.set_defaults(func=cmd_methods)

    p = sub.add_parser("selftest", help="verify cross-platform determinism")
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    p.set_defaults(func=cmd_selftest)

    return parser


def main(argv=None) -> int:
    _force_utf8_output()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except StegoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
