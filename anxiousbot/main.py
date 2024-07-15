import argparse
import asyncio

from anxiousbot.dealer import run as dealer_run
from anxiousbot.updater import run as updater_run


def _main():
    parser = argparse.ArgumentParser(prog="anxiousbot")
    subparsers = parser.add_subparsers(dest="command")
    dealer_parser = subparsers.add_parser("dealer", help="Run the dealer")
    updater_parser = subparsers.add_parser("updater", help="Run the updater")
    args = parser.parse_args()
    if args.command == "dealer":
        return asyncio.run(dealer_run())
    elif args.command == "updater":
        return asyncio.run(updater_run())
    parser.print_help()
    return 1


if __name__ == "__main__":
    exit(_main())
