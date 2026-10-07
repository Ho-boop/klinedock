"""Local CLI. The default demo never calls an exchange."""
import argparse

def main():
    parser = argparse.ArgumentParser(description="KlineDock trading and backtest workbench")
    parser.add_argument("--live-market", action="store_true", help="Open the original online market workbench")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.live_market:
        from src.web.app import main as run
        if args.port != 8888 or args.no_browser:
            parser.error("Live-market workbench currently uses port 8888 and opens the browser")
        run()
    else:
        from src.web.demo_app import main as run
        run(port=args.port, show=not args.no_browser)

if __name__ == "__main__":
    main()
