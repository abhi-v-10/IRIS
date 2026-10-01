"""Start the Invoice & Receipt Intelligence System.

    python run.py            -> http://127.0.0.1:5000
    python run.py --port 8080
    python run.py --lan      -> reachable from other devices on the same Wi-Fi (e.g. a phone for photos)
"""
import argparse
import socket

from iris import create_app
from iris.pipeline import tesseract_version


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "your-computer-ip"
    finally:
        s.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--lan", action="store_true", help="listen on the local network as well")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    app = create_app()
    v = tesseract_version()
    print("=" * 62)
    print(" Invoice & Receipt Intelligence System")
    print(f" Tesseract OCR : {'version ' + v if v else 'NOT FOUND - install it (README step 1)'}")
    print(f" Open          : http://127.0.0.1:{args.port}")
    if args.lan:
        print(f" On your phone : http://{lan_ip()}:{args.port}   (same Wi-Fi)")
    print(" Stop          : Ctrl+C")
    print("=" * 62)
    app.run(host="0.0.0.0" if args.lan else "127.0.0.1", port=args.port, debug=args.debug)
