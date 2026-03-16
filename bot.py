import asyncio
import logging
import os

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from database import init_db, migrate_db
from admin import admin_router
from user import user_router

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN topilmadi! .env faylini tekshiring.")

    logger.info("🤖 Bot ishga tushirilmoqda...")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()

    dp.include_router(admin_router)
    dp.include_router(user_router)

    try:
        logger.info("🗄 Ma'lumotlar bazasi tekshirilmoqda...")
        await init_db()
        await migrate_db()
        logger.info("✅ Ma'lumotlar bazasi tayyor.")

        logger.info("🚀 Polling boshlandi...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types()
        )

    except Exception:
        logger.exception("❌ Bot ishlashida kutilmagan xatolik yuz berdi:")
    finally:
        logger.info("🛑 Bot to'xtatildi. Sessiya yopilmoqda...")
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⌨️ Dastur foydalanuvchi tomonidan to'xtatildi.")
