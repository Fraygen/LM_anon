import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from redis.asyncio import Redis
from settings import config
import app.keyboards as kb
from tables.crud import add_announcement, get_feed_page, delete_announcement, handle_reaction

router = Router()
r = Redis.from_url(config.REDIS_URL)

MAX_ANNOUNCEMENT_LENGTH = 3000
COOLDOWN_SECONDS = 300  # 5 минут кулдаун
display_tz = ZoneInfo(config.TIMEZONE)

def format_announcement(page, viewer_id: int):
    item = page["item"]
    
    created_at = item.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    local_time = created_at.astimezone(display_tz).strftime("%d.%m.%Y в %H:%M")

    text_content = f"«{html.escape(item.text, quote=False)}»"
    footer = f"🕒 {local_time} · <i>{page['position']} из {page['total']}</i>"

    admin_info = ""
    if viewer_id in config.admin_id_list:
        uname = f"@{item.author_username}" if item.author_username else "нет username"
        admin_info = (
            f"\n\n🔒 <b>[Админ-инфо]</b>\n"
            f"• ID: <code>{item.author_id}</code>\n"
            f"• Имя: {html.escape(item.author_fullname or 'Не указано')}\n"
            f"• Username: {uname}"
        )

    return f"{text_content}\n\n{footer}{admin_info}"

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    await r.delete(f"writing:{user_id}")
    await r.delete(f"current_post:{user_id}")
    
    await message.answer(
        "👋 <b>Анонимные сообщения LM</b>\n\n"
        "Здесь можно читать анонимные сообщения за последние 24 часа и отправлять свои.\n\n"
        "Выбери действие:",
        reply_markup=kb.start_inline,
        parse_mode="HTML"
    )

@router.message(Command("menu"))
async def cmd_menu(message: Message):
    user_id = message.from_user.id
    await r.delete(f"writing:{user_id}")
    await r.delete(f"current_post:{user_id}")
    
    await message.answer(
        "👋 <b>Главное меню</b>\n\n"
        "Выбери действие:",
        reply_markup=kb.start_inline,
        parse_mode="HTML"
    )

@router.message(Command("read"))
async def cmd_read(message: Message):
    await do_read_feed(message, message.from_user.id)

@router.message(Command("write"))
async def cmd_write(message: Message):
    await do_start_writing(message, message.from_user.id)

@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    user_id = message.from_user.id
    was_writing = await r.get(f"writing:{user_id}")
    await r.delete(f"writing:{user_id}")
    await r.delete(f"current_post:{user_id}")
    
    text = "Ок, ничего не публикую.\n\n" if was_writing else ""
    text += "Используй команду /menu для открытия главного меню."
    await message.answer(text, parse_mode="HTML")

async def do_read_feed(target_obj, user_id: int):
    await r.delete(f"writing:{user_id}")
    page = await get_feed_page()
    message_target = target_obj.message if isinstance(target_obj, CallbackQuery) else target_obj
    
    if not page:
        await message_target.answer(
            "📭 <b>Пока сообщений нет (или за последние 24 часа ничего не публиковали)</b>\n\nСтань первым!",
            parse_mode="HTML"
        )
        return

    await r.set(f"current_post:{user_id}", page["item"].id)
    
    is_admin = user_id in config.admin_id_list
    inline_kb = kb.announcement_inline_keyboard(
        page["item"].id, 
        page["item"].likes_count, 
        page["item"].dislikes_count, 
        is_admin
    )
    
    await message_target.answer(
        format_announcement(page, user_id),
        reply_markup=inline_kb,
        parse_mode="HTML"
    )
    await message_target.answer(
        "👇",
        reply_markup=kb.feed_reply_keyboard(page["newer_id"], page["older_id"])
    )

async def do_start_writing(target_obj, user_id: int):
    message_target = target_obj.message if isinstance(target_obj, CallbackQuery) else target_obj
    
    if user_id not in config.admin_id_list:
        cooldown_left = await r.ttl(f"cooldown:{user_id}")
        if cooldown_left > 0:
            minutes = cooldown_left // 60
            seconds = cooldown_left % 60
            time_str = f"{minutes} мин. {seconds} сек." if minutes > 0 else f"{seconds} сек."
            await message_target.answer(
                f"⏳ <b>Слишком часто!</b>\n\nЧтобы избежать спама, можно отправлять сообщения не чаще чем раз в 5 минут.\nПодождите еще <b>{time_str}</b>.",
                parse_mode="HTML"
            )
            return

    await r.set(f"writing:{user_id}", "1", ex=3600)
    
    await message_target.answer(
        f"✍️ <b>Новое анонимное сообщение</b>\n\n"
        f"Отправь текст одним сообщением. Максимум — {MAX_ANNOUNCEMENT_LENGTH} символов.\n\n"
        f"Передумал? Нажми «Отмена» или отправь /cancel.",
        reply_markup=kb.compose_keyboard,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "feed:read")
async def callback_read(callback: CallbackQuery):
    await callback.answer()
    await do_read_feed(callback, callback.from_user.id)

@router.callback_query(F.data == "post:new")
async def callback_new(callback: CallbackQuery):
    await callback.answer()
    await do_start_writing(callback, callback.from_user.id)

@router.callback_query(F.data.startswith("react:"))
async def handle_reaction_callback(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка данных.", show_alert=True)
        return
    
    action = parts[1]
    try:
        announcement_id = int(parts[2])
    except ValueError:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    user_id = callback.from_user.id
    counts = await handle_reaction(announcement_id, user_id, action)

    if counts is not None:
        await callback.answer("Спасибо за голос!")
        is_admin = user_id in config.admin_id_list
        new_inline_kb = kb.announcement_inline_keyboard(
            announcement_id, 
            counts["likes"], 
            counts["dislikes"], 
            is_admin
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=new_inline_kb)
        except Exception:
            pass
    else:
        await callback.answer("Сообщение не найдено.", show_alert=True)

@router.callback_query(F.data.startswith("admin:del:"))
async def admin_delete_prompt(callback: CallbackQuery):
    if callback.from_user.id not in config.admin_id_list:
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return
    
    try:
        announcement_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=kb.admin_confirm_delete_inline(announcement_id)
    )

@router.callback_query(F.data.startswith("admin:confirm_del:"))
async def admin_delete_confirm(callback: CallbackQuery):
    if callback.from_user.id not in config.admin_id_list:
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return
    
    try:
        announcement_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    success = await delete_announcement(announcement_id)
    await callback.answer()
    
    if success:
        await callback.message.edit_text(
            f"🗑 <i>Сообщение №{announcement_id} было удалено администратором.</i>",
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            f"❌ <i>Не удалось удалить сообщение (возможно, оно уже удалено).</i>",
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("admin:cancel_del:"))
async def admin_delete_cancel(callback: CallbackQuery):
    if callback.from_user.id not in config.admin_id_list:
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return
    
    try:
        announcement_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    await callback.answer("Удаление отменено.")
    is_admin = callback.from_user.id in config.admin_id_list
    parts = callback.message.text.split("🕒") if callback.message.text else []
    await callback.message.edit_reply_markup(
        reply_markup=kb.announcement_inline_keyboard(announcement_id, 0, 0, is_admin)
    )

@router.message(F.text == "📖 Читать")
async def text_read_announcements(message: Message):
    await do_read_feed(message, message.from_user.id)

@router.message(F.text == "✍️ Написать")
async def text_start_composing(message: Message):
    await do_start_writing(message, message.from_user.id)

@router.message(F.text == "✖️ Отмена")
async def text_cancel_composing(message: Message):
    user_id = message.from_user.id
    await r.delete(f"writing:{user_id}")
    await message.answer(
        "Ок, ничего не публикую. Воспользуйся командой /menu для возврата в меню.",
        parse_mode="HTML"
    )

@router.message(F.text == "⬅️ Назад")
async def text_show_newer(message: Message):
    user_id = message.from_user.id
    current_id_raw = await r.get(f"current_post:{user_id}")
    
    if not current_id_raw:
        await message.answer("Сначала открой ленту через меню /menu.")
        return

    page = await get_feed_page(int(current_id_raw))
    if not page or page["newer_id"] is None:
        await message.answer("Это самое первое сообщение в ленте.")
        return

    newer_page = await get_feed_page(page["newer_id"])
    if not newer_page:
        await message.answer("Сообщение не найдено.")
        return

    await r.set(f"current_post:{user_id}", newer_page["item"].id)
    
    is_admin = user_id in config.admin_id_list
    inline_kb = kb.announcement_inline_keyboard(
        newer_page["item"].id, 
        newer_page["item"].likes_count, 
        newer_page["item"].dislikes_count, 
        is_admin
    )
    
    await message.answer(
        format_announcement(newer_page, user_id),
        reply_markup=inline_kb,
        parse_mode="HTML"
    )
    await message.answer(
        "👇",
        reply_markup=kb.feed_reply_keyboard(newer_page["newer_id"], newer_page["older_id"])
    )

@router.message(F.text == "Вперед ➡️")
async def text_show_older(message: Message):
    user_id = message.from_user.id
    current_id_raw = await r.get(f"current_post:{user_id}")
    
    if not current_id_raw:
        await message.answer("Сначала открой ленту через меню /menu.")
        return

    page = await get_feed_page(int(current_id_raw))
    if not page or page["older_id"] is None:
        await message.answer("Это самое последнее (старое) сообщение.")
        return

    older_page = await get_feed_page(page["older_id"])
    if not older_page:
        await message.answer("Сообщение не найдено.")
        return

    await r.set(f"current_post:{user_id}", older_page["item"].id)
    
    is_admin = user_id in config.admin_id_list
    inline_kb = kb.announcement_inline_keyboard(
        older_page["item"].id, 
        older_page["item"].likes_count, 
        older_page["item"].dislikes_count, 
        is_admin
    )
    
    await message.answer(
        format_announcement(older_page, user_id),
        reply_markup=inline_kb,
        parse_mode="HTML"
    )
    await message.answer(
        "👇",
        reply_markup=kb.feed_reply_keyboard(older_page["newer_id"], older_page["older_id"])
    )

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_message(message: Message):
    user_id = message.from_user.id
    is_writing = await r.get(f"writing:{user_id}")

    if not is_writing:
        await message.answer(
            "Используй команды /menu или /start для доступа к функциям бота."
        )
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("Текст пустой. Отправь текст сообщения или нажмите «Отмена».")
        return

    if len(text) > MAX_ANNOUNCEMENT_LENGTH:
        await message.answer(
            f"Слишком длинный текст: {len(text)} символов. Максимум — {MAX_ANNOUNCEMENT_LENGTH}. Сократи его и отправь ещё раз."
        )
        return

    announcement = await add_announcement(
        author_id=user_id,
        author_username=message.from_user.username,
        author_fullname=message.from_user.full_name,
        text=text
    )
    
    await r.delete(f"writing:{user_id}")
    
    if user_id not in config.admin_id_list:
        await r.set(f"cooldown:{user_id}", "1", ex=COOLDOWN_SECONDS)

    await message.answer(
        f"✅ Сообщение успешно опубликовано!\n\nОно уже доступно в ленте.",
        reply_markup=kb.published_keyboard,
        parse_mode="HTML"
    )

@router.message()
async def non_text_while_composing(message: Message):
    user_id = message.from_user.id
    is_writing = await r.get(f"writing:{user_id}")
    if is_writing:
        await message.answer("Пока принимаю только текст. Отправь сообщение текстом или нажми «Отмена».")