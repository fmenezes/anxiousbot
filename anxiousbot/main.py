import asyncio
import os

from dotenv import load_dotenv

from anxiousbot.runner import Runner


def _main():
    load_dotenv(override=True)
    CONFIG_PATH = os.getenv("CONFIG_PATH", "./config/local.json")
    CACHE_ENDPOINT = os.getenv("CACHE_ENDPOINT", "localhost")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    BOT_CHAT_ID = os.getenv("BOT_CHAT_ID")
    r = Runner(
        config_path=CONFIG_PATH,
        cache_endpoint=CACHE_ENDPOINT,
        bot_token=BOT_TOKEN,
        bot_chat_id=BOT_CHAT_ID,
    )
    return asyncio.run(r.run())


if __name__ == "__main__":
    exit(_main())
