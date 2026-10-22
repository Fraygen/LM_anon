import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand
from settings import config
from tables.database import engine, Base
from app.handlers import router
from redis.asyncio import Redis
from sqlalchemy import text

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

redis_client = Redis.from_url(config.REDIS_URL)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Добавляем новые колонки и таблицы, если база уже существовала
        await conn.execute(text("ALTER TABLE announcements ADD COLUMN IF NOT EXISTS author_username VARCHAR(100);"))
        await conn.execute(text("ALTER TABLE announcements ADD COLUMN IF NOT EXISTS author_fullname VARCHAR(200);"))
        await conn.execute(text("ALTER TABLE announcements ADD COLUMN IF NOT EXISTS likes_count INTEGER DEFAULT 0;"))
        await conn.execute(text("ALTER TABLE announcements ADD COLUMN IF NOT EXISTS dislikes_count INTEGER DEFAULT 0;"))
        print("✅ Таблицы базы данных проверены и созданы")

async def main():
    commands = [
        BotCommand(command="start", description="🚀 Запуск бота"),
        BotCommand(command="menu", description="🏠 Главное меню"),
        BotCommand(command="read", description="📖 Читать сообщения"),
        BotCommand(command="write", description="✍️ Написать сообщение"),
        BotCommand(command="cancel", description="❌ Отмена действия"),
    ]
    
    dp.include_router(router)
    await init_db()
    await bot.set_my_commands(commands)
    print("✅ Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🚫 Бот остановлен")