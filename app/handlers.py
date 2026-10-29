import html
import asyncio
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from redis.asyncio import Redis
from settings import config
import app.keyboards as kb
from tables.crud import (
    add_announcement, 
    get_feed_page, 
    delete_announcement, 
    handle_reaction, 
    save_user_to_db, 
    get_all_users, 
    increment_view,
    get_unread_count_since
)

router = Router()
r = Redis.from_url(config.REDIS_URL)

MAX_ANNOUNCEMENT_LENGTH = 3000
COOLDOWN_SECONDS = 300
display_tz = ZoneInfo(config.TIMEZONE)

def get_relative_time_str(created_at: datetime) -> str:
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    
    diff_seconds = int((now - created_at).total_seconds())
    if diff_seconds < 60:
        return "~только что"
    
    minutes = diff_seconds // 60
    if minutes < 60:
        return f"~{minutes} мин назад"
    
    hours = diff_seconds // 3600
    if hours < 24:
        remainder_minutes = (diff_seconds % 3600) // 60
        if remainder_minutes >= 30:
            return f"~{hours}.5 ч назад"
        elif hours == 1:
            return "~1 час назад"
        return f"~{hours} ч назад"
    
    days = diff_seconds // 86400
    if days == 1:
        return "~1 день назад"
    return f"~{days} дн назад"

async def format_announcement(page, viewer_id: int):
    item = page["item"]
    
    view_key = f"view:{viewer_id}:{item.id}"
    if not await r.get(view_key):
        await r.set(view_key, "1", ex=259200)
        new_views = await increment_view(item.id)
        item.views_count = new_views

    time_str = get_relative_time_str(item.created_at)

    text_content = f"«{html.escape(item.text, quote=False)}»" if item.text else ""

    footer = f"🕒 {time_str} | 👁 {item.views_count} \n\n <i>{page['position']} из {page['total']}</i>"

    admin_info = ""
    if viewer_id in config.admin_id_list:
        uname = f"@{item.author_username}" if item.author_username else "нет username"
        admin_info = ("\n\n"
            f"• ID: <code>{item.author_id}</code>\n"
            f"• Имя: {html.escape(item.author_fullname or 'Не указано')}\n"
            f"• Username: {uname}"
        )

    if text_content:
        return f"{text_content}\n\n{footer}{admin_info}"
    return f"{footer}{admin_info}"

async def notify_smart_push(bot: Bot, author_id: int):
    users = await get_all_users()
    current_time = int(time.time())
    
    for uid in users:
        if uid == author_id:
            continue
            
        last_seen_id = int(await r.get(f"last_read_id:{uid}") or 0)
        unread_count = await get_unread_count_since(last_seen_id)
        
        if unread_count == 0:
            continue
            
        last_notified_ts = int(await r.get(f"last_notify_ts:{uid}") or 0)
        hours_passed = (current_time - last_notified_ts) / 3600.0 if last_notified_ts else 999
        
        should_notify = (
            unread_count == 1 or 
            unread_count >= 3 or 
            hours_passed >= 12
        )
        
        if should_notify:
            try:
                msg_text = "🔥 <b>У нас для тебя новое сообщение!</b>" if unread_count == 1 else f"🔥 <b>У нас появилось уже {unread_count} новых сообщений!</b>"
                await bot.send_message(
                    chat_id=uid,
                    text=f"{msg_text}\nЗагляни почитать 👉 /read",
                    parse_mode="HTML"
                )
                await r.set(f"last_notify_ts:{uid}", str(current_time))
                await asyncio.sleep(0.05)
            except Exception:
                pass

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    await save_user_to_db(user_id)
    await r.delete(f"writing:{user_id}")
    await r.delete(f"current_post:{user_id}")
    
    await message.answer(
        "👋 <b>Анонимные сообщения LM</b>\n\n"
        "Здесь можно читать анонимные сообщения за последние 3 дня и отправлять свои.\n\n"
        "Выбери действие:",
        reply_markup=kb.start_inline,
        parse_mode="HTML"
    )

@router.message(Command("menu"))
async def cmd_menu(message: Message):
    user_id = message.from_user.id
    await save_user_to_db(user_id)
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
    await save_user_to_db(message.from_user.id)
    await do_read_feed(message, message.from_user.id)

@router.message(Command("write"))
async def cmd_write(message: Message):
    await save_user_to_db(message.from_user.id)
    await do_start_writing(message, message.from_user.id)

@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    user_id = message.from_user.id
    was_writing = await r.get(f"writing:{user_id}")
    await r.delete(f"writing:{user_id}")
    await r.delete(f"current_post:{user_id}")
    
    text = "Хорошо, ничего не публикую.\n\n" if was_writing else ""
    text += "Используй команду /menu для открытия главного меню."
    await message.answer(text, parse_mode="HTML")

async def send_announcement_message(target_target, page, user_id: int):
    item = page["item"]
    await r.set(f"current_post:{user_id}", item.id)
    await r.set(f"last_read_id:{user_id}", item.id)
    
    is_admin = user_id in config.admin_id_list
    inline_kb = kb.announcement_inline_keyboard(
        item.id, 
        item.likes_count, 
        item.dislikes_count, 
        is_admin
    )
    
    formatted_text = await format_announcement(page, user_id)
    
    if item.photo_file_id:
        await target_target.answer_photo(
            photo=item.photo_file_id,
            caption=formatted_text,
            reply_markup=inline_kb,
            parse_mode="HTML"
        )
    else:
        await target_target.answer(
            formatted_text,
            reply_markup=inline_kb,
            parse_mode="HTML"
        )
        
    await target_target.answer(
        "👇",
        reply_markup=kb.feed_reply_keyboard(page["newer_id"], page["older_id"])
    )

async def do_read_feed(target_obj, user_id: int):
    await r.delete(f"writing:{user_id}")
    page = await get_feed_page()
    message_target = target_obj.message if isinstance(target_obj, CallbackQuery) else target_obj
    
    if not page:
        await message_target.answer(
            "📭 <b>Пока сообщений нет (или за последние 3 дня ничего не публиковали)</b>\n\nСтань первым! /write",
            parse_mode="HTML"
        )
        return

    await send_announcement_message(message_target, page, user_id)

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
        f"Отправь текст или картинку (можно с подписью). Максимум — {MAX_ANNOUNCEMENT_LENGTH} символов.\n\n"
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
        try:
            await callback.message.edit_caption(
                caption=f"🗑 <i>Сообщение №{announcement_id} было удалено администратором.</i>",
                parse_mode="HTML",
                reply_markup=None
            )
        except Exception:
            await callback.message.edit_text(
                f"🗑 <i>Сообщение №{announcement_id} было удалено администратором.</i>",
                parse_mode="HTML"
            )
    else:
        await callback.answer("Не удалось удалить сообщение.", show_alert=True)

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
    
    try:
        await callback.message.edit_reply_markup(
            reply_markup=kb.announcement_inline_keyboard(announcement_id, 0, 0, is_admin)
        )
    except Exception:
        pass

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
        "Хорошо, ничего не публикую. Воспользуйся командой /menu для возврата в меню.",
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

    await send_announcement_message(message, newer_page, user_id)

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

    await send_announcement_message(message, older_page, user_id)

@router.message(F.photo)
async def handle_photo_message(message: Message):
    user_id = message.from_user.id
    is_writing = await r.get(f"writing:{user_id}")

    if not is_writing:
        await message.answer(
            "Используй команды /menu или /start для доступа к функциям бота."
        )
        return

    photo_file_id = message.photo[-1].file_id
    caption = (message.caption or "").strip()

    if len(caption) > MAX_ANNOUNCEMENT_LENGTH:
        await message.answer(
            f"Слишком длинная подпись: {len(caption)} символов. Максимум — {MAX_ANNOUNCEMENT_LENGTH}. Сократи её и отправь ещё раз."
        )
        return

    await add_announcement(
        author_id=user_id,
        author_username=message.from_user.username,
        author_fullname=message.from_user.full_name,
        text=caption if caption else None,
        photo_file_id=photo_file_id
    )
    
    await r.delete(f"writing:{user_id}")
    
    if user_id not in config.admin_id_list:
        await r.set(f"cooldown:{user_id}", "1", ex=COOLDOWN_SECONDS)

    await message.answer(
        f"✅ Сообщение с фото успешно опубликовано!\n\nОно уже доступно в ленте.",
        reply_markup=kb.published_keyboard,
        parse_mode="HTML"
    )

    asyncio.create_task(notify_smart_push(message.bot, user_id))

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

    await add_announcement(
        author_id=user_id,
        author_username=message.from_user.username,
        author_fullname=message.from_user.full_name,
        text=text,
        photo_file_id=None
    )
    
    await r.delete(f"writing:{user_id}")
    
    if user_id not in config.admin_id_list:
        await r.set(f"cooldown:{user_id}", "1", ex=COOLDOWN_SECONDS)

    await message.answer(
        f"✅ Сообщение успешно опубликовано!\n\nОно уже доступно в ленте.",
        reply_markup=kb.published_keyboard,
        parse_mode="HTML"
    )

    asyncio.create_task(notify_smart_push(message.bot, user_id))

@router.message()
async def non_text_while_composing(message: Message):
    user_id = message.from_user.id
    is_writing = await r.get(f"writing:{user_id}")
    if is_writing:
        await message.answer("Пока принимаю только текст или фото. Отправь сообщение или нажми «Отмена».")