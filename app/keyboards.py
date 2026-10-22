from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

start_inline = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="📖 Читать", callback_data="feed:read"),
            InlineKeyboardButton(text="✍️ Написать", callback_data="post:new"),
        ]
    ]
)

compose_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✖️ Отмена")]
    ],
    resize_keyboard=True
)

def feed_reply_keyboard(newer_id: int | None, older_id: int | None):
    nav_row = []
    if newer_id is not None:
        nav_row.append(KeyboardButton(text="⬅️ Назад"))
    if older_id is not None:
        nav_row.append(KeyboardButton(text="Вперед ➡️"))
        
    return ReplyKeyboardMarkup(keyboard=[nav_row] if nav_row else [], resize_keyboard=True)

def announcement_inline_keyboard(announcement_id: int, likes: int, dislikes: int, is_admin: bool) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text=f"👍 {likes}", callback_data=f"react:like:{announcement_id}"),
            InlineKeyboardButton(text=f"👎 {dislikes}", callback_data=f"react:dislike:{announcement_id}"),
        ]
    ]
    if is_admin:
        keyboard.append([
            InlineKeyboardButton(text="🗑 Удалить сообщение", callback_data=f"admin:del:{announcement_id}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def admin_confirm_delete_inline(announcement_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin:confirm_del:{announcement_id}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"admin:cancel_del:{announcement_id}"),
            ]
        ]
    )

published_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📖 Читать"),
            KeyboardButton(text="🏠 В меню"),
        ]
    ],
    resize_keyboard=True
)