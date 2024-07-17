import argparse
import multiprocessing

from dotenv import load_dotenv

from anxiousbot.dealer import run as dealer_run
from anxiousbot.notifier import NotifierProcess
from anxiousbot.updater import run as updater_run
from anxiousbot.util import run_uv_loop


def _main():
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(prog="anxiousbot")
    subparsers = parser.add_subparsers(dest="command")
    dealer_parser = subparsers.add_parser("dealer", help="Run the dealer")
    updater_parser = subparsers.add_parser("updater", help="Run the updater")
    args = parser.parse_args()
    if args.command == "dealer":
        return run_uv_loop(dealer_notifier_run)
    elif args.command == "updater":
        return run_uv_loop(updater_run)
    parser.print_help()
    return 1


async def dealer_notifier_run():
    bot_queue = multiprocessing.Queue()
    n = NotifierProcess(bot_queue)
    n.start()

    await dealer_run(bot_queue)
    return n.wait()


if __name__ == "__main__":
    exit(_main())
