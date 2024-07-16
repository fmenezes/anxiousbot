import asyncio
import os

from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.error import Forbidden, NetworkError


async def _test(bot: Bot, chat_id: str):
    while True:
        await bot.send_message(chat_id, "test")
        await asyncio.sleep(60)


async def _echo(bot: Bot, update_id: int) -> int:
    updates = await bot.get_updates(
        offset=update_id, timeout=10, allowed_updates=Update.ALL_TYPES
    )
    for update in updates:
        next_update_id = update.update_id + 1
        if update.message and update.message.text:
            print(
                f"({update.effective_message.chat_id}) {update.effective_message.from_user.username}: {update.effective_message.text}"
            )
        return next_update_id
    return update_id


async def _listen(bot):
    try:
        update_id = (await bot.get_updates())[0].update_id
    except IndexError:
        update_id = None

    while True:
        try:
            update_id = await _echo(bot, update_id)
        except NetworkError:
            await asyncio.sleep(1)
        except Forbidden:
            update_id += 1


async def _run():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    BOT_CHAT_ID = os.getenv("BOT_CHAT_ID")
    async with Bot(BOT_TOKEN) as bot:
        # get the first pending update_id, this is so we can skip over it in case
        # we get a "Forbidden" exception.
        tasks = [
            asyncio.create_task(_listen(bot)),
            asyncio.create_task(_test(bot, BOT_CHAT_ID)),
        ]
        await asyncio.gather(*tasks)


def _main() -> None:
    load_dotenv(override=True)
    asyncio.run(_run())


if __name__ == "__main__":
    _main()
