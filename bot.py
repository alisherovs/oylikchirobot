import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# O'zimiz yaratgan fayllardan importlar
from database import init_db
from admin import admin_router
from user import user_router

# .env faylini o'qish (Tokenlarni xavfsiz saqlash uchun)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN topilmadi! Iltimos, .env faylini tekshiring.")

async def main():
    # Logging sozlamasi (Konsolda bot holatini va xatoliklarni kuzatib borish uchun)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    # Bot va Dispatcher obyektlarini yaratish
    # Barcha xabarlar global darajada HTML formatda o'qilishini belgilaymiz
    bot = Bot(
        token=BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Routerlarni botga ulash (admin va user logikasi)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # Bot ishga tushishidan oldin ma'lumotlar bazasini tayyorlash
    logger.info("Ma'lumotlar bazasi tekshirilmoqda (jadvallar yaratilmoqda)...")
    await init_db()
    logger.info("✅ Ma'lumotlar bazasi tayyor!")

    # Polling (xabarlarni kutish) jarayonini boshlash
    try:
        logger.info("🚀 Bot muvaffaqiyatli ishga tushdi va xabarlarni kutmoqda...")
        # Bot o'chiq paytida kelgan eski xabarlarni o'tkazib yuborish (spamning oldini olish)
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Bot ishlashida xatolik yuz berdi: {e}")
    finally:
        logger.info("🛑 Bot to'xtatildi. Sessiya yopilmoqda...")
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Dastur foydalanuvchi tomonidan to'xtatildi (Ctrl+C).")