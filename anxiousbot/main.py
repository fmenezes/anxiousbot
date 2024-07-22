import argparse
import asyncio

from dotenv import load_dotenv

from anxiousbot.dealer import run as dealer_run
from anxiousbot.notifier import run as notifier_run
from anxiousbot.updater import run as updater_run


def _main():
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(prog="anxiousbot")
    subparsers = parser.add_subparsers(dest="command")
    dealer_parser = subparsers.add_parser("dealer", help="Run the dealer")
    updater_parser = subparsers.add_parser("updater", help="Run the updater")
    args = parser.parse_args()
    if args.command == "dealer":
        return asyncio.run(dealer_notifier_run)
    elif args.command == "updater":
        return asyncio.run(updater_run)
    parser.print_help()
    return 1


async def dealer_notifier_run():
    bot_queue = asyncio.Queue()

    tasks = []
    tasks += [dealer_run(bot_queue), notifier_run(bot_queue)]

    return await asyncio.gather(*tasks)


if __name__ == "__main__":
    exit(_main())
