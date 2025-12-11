from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from cfg import *

# ----------------- Настройки -----------------
# Токен бота, который берётся из внешнего файла конфигурации.
TOKEN = TG_TOKEN
# Основной администратор с правом открытия панели.
PRIMARY_ADMIN_ID = MAIN_ADMIN
# Дополнительный администратор, получающий копии обращений.
SECONDARY_ADMIN_ID = SECOND_ADMIN
# Список всех администраторов, которым пересылаются заявки.
ADMIN_IDS = sorted({PRIMARY_ADMIN_ID, SECONDARY_ADMIN_ID})
# Идентификатор канала для публикации одобренных постов.
CHANNEL_ID = CHANNEL_FOR_PODPISKA

# Корневая директория проекта.
BASE_DIR = Path(__file__).resolve().parent
# Каталог для хранения данных пользователей.
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Каталог для сохранения всех входящих медиафайлов.
MEDIA_DIR = BASE_DIR / "media_daun"
MEDIA_DIR.mkdir(exist_ok=True)

# Пути к файлам с пользователями, историей и балансами.
USERS_FILE = DATA_DIR / "users.txt"
HISTORY_FILE = DATA_DIR / "history.txt"
BALANCE_FILE = DATA_DIR / "balance.txt"
# Путь к резервному видео, если пост без медиа.
VIDEO_FALLBACK_PATH = BASE_DIR / "youra.mp4"
# Путь к базе данных SQLite, где дублируются данные из текстовых файлов.
DB_PATH = DATA_DIR / "bot.db"

# Состояния пользователей во время диалога с ботом.
user_states: Dict[int, Dict] = {}


# ======================== УТИЛИТЫ ========================
def _get_db_connection() -> sqlite3.Connection:
    """Создать подключение к SQLite с включённой поддержкой внешних ключей."""

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _init_db() -> None:
    """Инициализировать таблицы базы данных при старте приложения."""

    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS balances (
            user_id INTEGER PRIMARY KEY,
            balance REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            mode TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        """
    )
    conn.commit()
    conn.close()


def _utc_now_iso() -> str:
    """Вернуть ISO-строку с текущим временем в UTC."""

    return datetime.now(UTC).isoformat()


def _read_lines(path: Path) -> list[str]:
    """Безопасно прочитать строки из файла (если его нет, вернуть пустой список)."""

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _write_lines(path: Path, lines: list[str]) -> None:
    """Записать список строк в файл, разделяя их переводом строки."""

    with path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


async def _save_media_file(message, context: ContextTypes.DEFAULT_TYPE, media_type: str) -> Optional[str]:
    """Сохранить присланный файл в директорию media_daun и вернуть путь до него."""

    try:
        if media_type == "photo" and message.photo:
            file_id = message.photo[-1].file_id
            default_suffix = ".jpg"
        elif media_type == "video" and message.video:
            file_id = message.video.file_id
            default_suffix = ".mp4"
        elif media_type == "audio" and message.audio:
            file_id = message.audio.file_id
            default_suffix = ".mp3"
        else:
            return None

        file = await context.bot.get_file(file_id)
        suffix = Path(getattr(file, "file_path", "")).suffix or default_suffix
        filename = f"{media_type}_{message.from_user.id}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{suffix}"
        dest = MEDIA_DIR / filename
        await file.download_to_drive(custom_path=str(dest))
        print(f"💾 Медиа сохранено: {dest}")
        return str(dest)
    except Exception as exc:
        print(f"⚠️ Не удалось сохранить медиа: {exc}")
    return None


async def send_or_edit(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    *,
    allow_edit: bool = True,
) -> None:
    """Отправить новое сообщение или отредактировать последнее от бота."""

    state = user_states.setdefault(user_id, {})
    message_id = state.get("last_bot_message_id")
    if allow_edit and message_id:
        try:
            message = await context.bot.edit_message_text(
                chat_id=user_id, message_id=message_id, text=text, reply_markup=reply_markup
            )
        except Exception:
            message = await context.bot.send_message(user_id, text, reply_markup=reply_markup)
    else:
        message = await context.bot.send_message(user_id, text, reply_markup=reply_markup)
    state["last_bot_message_id"] = message.message_id
    user_states[user_id] = state


def build_main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Собрать клавиатуру главного меню с учётом роли пользователя."""

    keyboard = [
        [
            InlineKeyboardButton("🕵️ Отправить анонимно", callback_data="anon"),
            InlineKeyboardButton("👤 Отправить с именем", callback_data="non_anon"),
        ],
        [
            InlineKeyboardButton("💼 Профиль", callback_data="profile"),
            InlineKeyboardButton("💸 Вывод средств", callback_data="withdraw"),
        ],
        [InlineKeyboardButton("🔗 Ссылки", callback_data="links")],
        [InlineKeyboardButton("🗑️ Удалить пост", callback_data="delete_post")],
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton("🛠️ Админ панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)


def sync_db_from_files() -> Dict[str, int]:
    """Перезалить данные из текстовых файлов в SQLite, обновить копии и вернуть статистику."""

    conn = _get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM history;")
    cur.execute("DELETE FROM balances;")
    cur.execute("DELETE FROM users;")

    for line in _read_lines(USERS_FILE):
        try:
            user_id = int(line)
        except ValueError:
            continue
        cur.execute(
            "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?);",
            (user_id, _utc_now_iso()),
        )

    for line in _read_lines(BALANCE_FILE):
        parts = line.split()
        if len(parts) >= 2:
            try:
                user_id = int(parts[0])
                balance = float(parts[1])
            except ValueError:
                continue
            cur.execute(
                "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?);",
                (user_id, _utc_now_iso()),
            )
            cur.execute(
                "INSERT OR REPLACE INTO balances(user_id, balance, updated_at) VALUES (?, ?, ?);",
                (user_id, balance, _utc_now_iso()),
            )

    for line in _read_lines(HISTORY_FILE):
        parts = line.split("|")
        if len(parts) >= 5:
            try:
                user_id = int(parts[0].strip())
            except ValueError:
                continue
            username = parts[1].strip()
            mode = parts[2].strip()
            content = parts[3].strip()
            created_at = parts[4].strip()
            cur.execute(
                "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?);",
                (user_id, _utc_now_iso()),
            )
            cur.execute(
                """
                INSERT INTO history(user_id, username, mode, content, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (user_id, username, mode, content, created_at),
            )

    conn.commit()

    users_for_file = [str(row[0]) for row in cur.execute("SELECT user_id FROM users ORDER BY user_id;")]
    balances_for_file = [
        f"{row[0]} {row[1]}" for row in cur.execute("SELECT user_id, balance FROM balances ORDER BY user_id;")
    ]
    history_for_file = [
        f"{row[0]} | {row[1] or '—'} | {row[2]} | {row[3]} | {row[4]}"
        for row in cur.execute(
            "SELECT user_id, username, mode, content, created_at FROM history ORDER BY id;"
        )
    ]
    counts = {
        "users": len(users_for_file),
        "balances": len(balances_for_file),
        "history": len(history_for_file),
    }
    conn.close()

    _write_lines(USERS_FILE, users_for_file)
    _write_lines(BALANCE_FILE, balances_for_file)
    _write_lines(HISTORY_FILE, history_for_file)

    return counts


def _get_fallback_video() -> Optional[InputFile]:
    """Вернуть видео-заглушку, если файл доступен."""

    if VIDEO_FALLBACK_PATH.exists():
        return InputFile(VIDEO_FALLBACK_PATH)
    return None


def get_balance(user_id: int) -> float:
    """Получить баланс пользователя из базы или, если записи нет, из файла."""

    conn = _get_db_connection()
    cur = conn.cursor()
    row = cur.execute("SELECT balance FROM balances WHERE user_id = ?;", (user_id,)).fetchone()
    conn.close()
    if row is not None:
        return float(row[0])
    lines = _read_lines(BALANCE_FILE)
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[0] == str(user_id):
            try:
                return float(parts[1])
            except Exception:
                return 0.0
    return 0.0


def set_balance(user_id: int, balance: float) -> None:
    """Обновить баланс пользователя в обоих хранилищах."""

    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?);",
        (user_id, _utc_now_iso()),
    )
    cur.execute(
        "INSERT OR REPLACE INTO balances(user_id, balance, updated_at) VALUES (?, ?, ?);",
        (user_id, balance, _utc_now_iso()),
    )
    conn.commit()
    conn.close()

    lines = _read_lines(BALANCE_FILE)
    updated = False
    new_lines = []
    for line in lines:
        parts = line.split()
        if parts and parts[0] == str(user_id):
            new_lines.append(f"{user_id} {balance}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{user_id} {balance}")
    _write_lines(BALANCE_FILE, new_lines)


async def credit_user(user_id: int, amount: float, context: ContextTypes.DEFAULT_TYPE) -> float:
    """Начислить средства пользователю и вернуть его новый баланс."""

    new = get_balance(user_id) + amount
    set_balance(user_id, new)
    try:
        await context.bot.send_message(user_id, f"🎉 Вам начислено {amount:.0f} руб. Баланс: {new:.2f} руб.")
    except Exception:
        pass
    return new


# ======================== РЕГИСТРАЦИЯ И ИСТОРИЯ ========================
def save_user(user_id: int) -> bool:
    """Сохранить пользователя в файл и базу, вернуть True если он новый."""

    lines = _read_lines(USERS_FILE)
    already_exists = str(user_id) in lines
    if not already_exists:
        lines.append(str(user_id))
        _write_lines(USERS_FILE, lines)

    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?);",
        (user_id, _utc_now_iso()),
    )
    conn.commit()
    conn.close()
    return not already_exists


def log_history(user, mode: str, text: str, media_path: Optional[str] = None) -> None:
    """Добавить запись истории в файл и SQLite с ссылкой на медиа."""

    username = f"@{user.username}" if user.username else "—"
    timestamp = datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')

    content_parts = [text.strip()] if text.strip() else []
    if media_path:
        content_parts.append(f"Медиа: {media_path}")
    content_for_store = "\n".join(content_parts) if content_parts else "[Медиа отправлено]"

    line = (
        f"{user.id} | {username} | {'Анонимное' if mode == 'anon' else 'Не анонимное'} | "
        f"{content_for_store} | {timestamp}"
    )
    lines = _read_lines(HISTORY_FILE)
    lines.append(line)
    _write_lines(HISTORY_FILE, lines)

    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO history(user_id, username, mode, content, created_at) VALUES (?, ?, ?, ?, ?);",
        (user.id, username, mode, content_for_store, timestamp),
    )
    conn.commit()
    conn.close()


def count_user_posts(user_id: int) -> int:
    """Посчитать количество записей пользователя в истории."""

    conn = _get_db_connection()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT COUNT(*) FROM history WHERE user_id = ?;",
        (user_id,),
    ).fetchone()
    conn.close()
    if row is not None:
        return int(row[0])
    lines = _read_lines(HISTORY_FILE)
    return sum(1 for line in lines if line.split("|")[0].strip() == str(user_id))


# ======================== ГЛАВНОЕ МЕНЮ ========================
async def show_main_menu(
    user_id: int, context: ContextTypes.DEFAULT_TYPE, text: str, *, allow_edit: bool = True
) -> None:
    """Показать главное меню, отмечая, имеет ли пользователь права админа."""

    is_admin = user_id == PRIMARY_ADMIN_ID
    await send_or_edit(context, user_id, text, build_main_menu(is_admin), allow_edit=allow_edit)


def _send_to_admins_sync(context: ContextTypes.DEFAULT_TYPE, send_func) -> None:
    """Отправить уведомление всем администраторам синхронно (используется в except)."""

    for admin_id in ADMIN_IDS:
        try:
            print(f"📨 Отправляю сообщение администратору {admin_id} (sync)")
            send_func(admin_id)
        except Exception:
            continue


async def _send_to_admins_async(context: ContextTypes.DEFAULT_TYPE, coro_builder) -> None:
    """Асинхронно отправить сообщение всем администраторам."""

    for admin_id in ADMIN_IDS:
        try:
            print(f"📨 Отправляю сообщение администратору {admin_id} (async)")
            await coro_builder(admin_id)
        except Exception:
            print(f"⚠️ Не удалось отправить администратору {admin_id}")
            continue


# ======================== ОБРАБОТЧИКИ ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик /start: проверка подписки, регистрация и показ меню."""

    if not update.message:
        return
    user = update.message.from_user
    user_id = user.id

    try:
        member = await context.bot.get_chat_member("@Mind4Not0Found4", user_id)
        if getattr(member, "status", None) in ["left", "kicked"]:
            raise Exception("Не подписан")
    except Exception:
        keyboard = [[InlineKeyboardButton("📢 Подписаться на канал", url="https://t.me/Mind4Not0Found4")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_or_edit(
            context,
            user_id,
            "⚠️ Для использования бота нужно подписаться на канал @Mind4Not0Found4.\n\nПосле подписки нажмите /start снова.",
            reply_markup,
            allow_edit=False,
        )
        return

    if save_user(user_id):
        prev = get_balance(user_id)
        set_balance(user_id, prev + 1.0)

    user_states.setdefault(user_id, {})
    await show_main_menu(user_id, context, "Привет! 👋 Выбери действие:", allow_edit=False)


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сохранить выбор пользователя: анонимно или с именем."""

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_states[user_id] = {"mode": query.data}
    keyboard = [
        [InlineKeyboardButton("📝 Текст", callback_data="text")],
        [InlineKeyboardButton("🖼 Фото", callback_data="photo")],
        [InlineKeyboardButton("🎥 Видео", callback_data="video")],
        [InlineKeyboardButton("🎧 Аудио", callback_data="audio")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")],
    ]
    await send_or_edit(context, user_id, "Что хочешь отправить? 🤔", InlineKeyboardMarkup(keyboard))


async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Записать тип выбранного контента и попросить прислать его."""

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_states.get(user_id, {})
    state["type"] = query.data
    user_states[user_id] = state
    prompts = {
        "text": "✏️ Отправь текст для администратора.",
        "photo": "🖼 Отправь фото для администратора.",
        "video": "🎥 Отправь видео для администратора.",
        "audio": "🎧 Отправь аудио для администратора.",
    }
    await send_or_edit(context, user_id, prompts[query.data])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывать присланные файлы или текст в зависимости от состояния."""

    if not update.message or update.message.chat.type != "private":
        return

    user = update.message.from_user
    user_id = user.id
    state = user_states.get(user_id, {})

    if state.get("awaiting_withdraw") and update.message.text:
        card = update.message.text
        state["withdraw_card"] = card
        state["awaiting_withdraw"] = False
        state["awaiting_withdraw_confirm"] = True
        user_states[user_id] = state
        balance = get_balance(user_id)
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить вывод", callback_data="withdraw_confirm")],
            [InlineKeyboardButton("❌ Отменить", callback_data="withdraw_cancel")],
        ]
        await send_or_edit(
            context,
            user_id,
            f"💸 Реквизиты: {card}\nСумма к выводу: {balance:.2f} руб.\nПодтвердить вывод?",
            InlineKeyboardMarkup(keyboard),
            allow_edit=False,
        )
        print(f"💸 Пользователь {user_id} указал реквизиты для вывода: {card}")
        return

    if state.get("awaiting_broadcast") and user_id == PRIMARY_ADMIN_ID:
        text = update.message.text or ""
        user_ids = _read_lines(USERS_FILE)
        sent, failed = 0, 0
        for uid in user_ids:
            try:
                await context.bot.send_message(int(uid), text)
                sent += 1
            except Exception:
                failed += 1
        user_states[user_id] = {}
        await show_main_menu(
            user_id, context, f"✅ Рассылка завершена. Успешно: {sent}, ошибок: {failed}.", allow_edit=False
        )
        return

    if state.get("awaiting_delete_link") and update.message.text:
        state["delete_link"] = update.message.text
        state["awaiting_delete_link"] = False
        state["awaiting_delete_reason"] = True
        user_states[user_id] = state
        await send_or_edit(context, user_id, "✏️ Введите причину удаления поста:", allow_edit=False)
        return

    if state.get("awaiting_delete_reason") and update.message.text:
        reason = update.message.text
        link = state.get("delete_link", "—")
        state["delete_reason"] = reason
        state["awaiting_delete_reason"] = False
        state["awaiting_delete_confirm"] = True
        user_states[user_id] = state
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить удаление", callback_data="delete_confirm")],
            [InlineKeyboardButton("❌ Отменить", callback_data="delete_cancel")],
        ]
        await send_or_edit(
            context,
            user_id,
            f"🔗 Ссылка: {link}\n✏️ Причина: {reason}\nОтправить запрос администратору?",
            InlineKeyboardMarkup(keyboard),
            allow_edit=False,
        )
        print(
            f"🗑 Пользователь {user.id} указал ссылку {link} и причину '{reason}', ожидает подтверждения"
        )
        return

    if state.get("awaiting_caption") and update.message.text:
        state["pending_caption"] = update.message.text
        state.pop("awaiting_caption", None)
        user_states[user_id] = state
        keyboard = [
            [
                InlineKeyboardButton("✅ Отправить", callback_data="confirm_send"),
                InlineKeyboardButton("❌ Отменить", callback_data="cancel_send"),
            ]
        ]
        await send_or_edit(
            context,
            user_id,
            "✅ Подпись сохранена! Отправить сообщение админу?",
            InlineKeyboardMarkup(keyboard),
            allow_edit=False,
        )
        return

    if not state:
        await show_main_menu(user_id, context, "⚠️ Сначала нажмите /start для выбора действия.", allow_edit=False)
        return

    msg_type = state.get("type")
    if msg_type in ["photo", "video", "audio"]:
        if (msg_type == "photo" and not update.message.photo) or (
            msg_type == "video" and not update.message.video
        ) or (msg_type == "audio" and not update.message.audio):
            await send_or_edit(
                context, user_id, "⚠️ Похоже, вы не отправили нужный файл. Попробуйте ещё раз.", allow_edit=False
            )
            return
        media_path = await _save_media_file(update.message, context, msg_type)
        state["pending_message"] = update.message
        state["pending_caption"] = ""
        state["pending_media_path"] = media_path
        user_states[user_id] = state
        keyboard = [
            [
                InlineKeyboardButton("📝 Добавить подпись", callback_data="add_caption"),
                InlineKeyboardButton("✅ Отправить", callback_data="confirm_send"),
                InlineKeyboardButton("❌ Отменить", callback_data="cancel_send"),
            ]
        ]
        await send_or_edit(
            context,
            user_id,
            "Медиа получено. Добавить подпись или отправить?",
            InlineKeyboardMarkup(keyboard),
            allow_edit=False,
        )
        return

    if msg_type == "text" and update.message.text:
        state["pending_message"] = update.message
        user_states[user_id] = state
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_send"), InlineKeyboardButton("❌ Отменить", callback_data="cancel_send")]
        ]
        await send_or_edit(
            context,
            user_id,
            f"📄 Твой текст:\n\n{update.message.text}\n\nОтправить админу?",
            InlineKeyboardMarkup(keyboard),
            allow_edit=False,
        )


async def add_caption_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запросить у пользователя подпись к медиафайлу."""

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_states.get(user_id)
    if not state or "pending_message" not in state:
        return await query.answer("⚠️ Нет сообщения для добавления текста.", show_alert=True)
    state["awaiting_caption"] = True
    user_states[user_id] = state
    await send_or_edit(context, user_id, "📝 Напишите текст, который хотите добавить к медиа.")


async def confirm_or_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтвердить или отменить отправку поста администраторам."""

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_states.get(user_id)
    if not state or "pending_message" not in state:
        return await query.answer("⚠️ Нет сообщения для подтверждения.", show_alert=True)

    pending_message = state["pending_message"]
    mode = state.get("mode", "anon")
    msg_type = state.get("type", "text")
    user = query.from_user

    if query.data == "cancel_send":
        user_states.pop(user_id, None)
        await show_main_menu(user_id, context, "🚫 Отправка отменена.")
        return

    post_cb = f"post_channel:{user.id}"
    caption_text = "📨 Анонимное сообщение" if mode == "anon" else f"👤 От {user.first_name} (ID: {user.id})"
    media_caption = state.get("pending_caption", "")
    original_caption = pending_message.caption or "" if hasattr(pending_message, "caption") else ""
    media_path = state.get("pending_media_path")
    if media_caption:
        caption_text += f"\n\n💬 {media_caption}"
    elif original_caption:
        caption_text += f"\n\n💬 {original_caption}"

    admin_keyboard = [[InlineKeyboardButton("📢 Запостить в канал", callback_data=post_cb)]]
    admin_markup = InlineKeyboardMarkup(admin_keyboard)

    async def send_to_admin(admin_id: int) -> None:
        print(f"📨 Готовлю отправку сообщения пользователю {user_id} админу {admin_id}")
        if msg_type == "text":
            text_to_send = pending_message.text
            await context.bot.send_message(
                chat_id=admin_id, text=f"{caption_text}\n\n{text_to_send}", reply_markup=admin_markup
            )
        else:
            await context.bot.copy_message(
                chat_id=admin_id,
                from_chat_id=user_id,
                message_id=pending_message.message_id,
                caption=caption_text,
                reply_markup=admin_markup,
            )
        print(f"✅ Сообщение пользователя {user_id} доставлено админу {admin_id}")

    try:
        await _send_to_admins_async(context, send_to_admin)
        if msg_type == "text":
            log_history(user, mode, pending_message.text)
        else:
            log_history(user, mode, media_caption or pending_message.caption or "", media_path)
    except Exception as e:
        _send_to_admins_sync(
            context, lambda admin_id: context.bot.send_message(admin_id, f"Ошибка при пересылке от {user.id}: {e}")
        )

    user_states.pop(user_id, None)
    await show_main_menu(user_id, context, "✅ Сообщение успешно отправлено админам!")


async def post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Опубликовать сообщение в канал после подтверждения администратора."""

    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("❌ Только админ может постить в канал.")
        return

    data = query.data or ""
    parts = data.split(":")
    sender_id = int(parts[1]) if len(parts) >= 2 and parts[0] == "post_channel" else None
    msg = query.message
    footer = "\n\n✉️ Отправить анонимное сообщение в канал - @School99InfBot\n🎉 Наш веселенький чат - https://t.me/+joXHChzNX542ZjZi"

    def build_caption(text: str) -> str:
        return f"{text}{footer}"

    posted_successfully = False
    try:
        if msg.photo:
            await context.bot.send_photo(
                chat_id=CHANNEL_ID, photo=msg.photo[-1].file_id, caption=build_caption(msg.caption or "")
            )
            posted_successfully = True
            print(f"📢 В канал отправлено фото от {sender_id}")
        elif msg.video:
            await context.bot.send_video(
                chat_id=CHANNEL_ID, video=msg.video.file_id, caption=build_caption(msg.caption or "")
            )
            posted_successfully = True
            print(f"📢 В канал отправлено видео от {sender_id}")
        elif msg.audio:
            await context.bot.send_audio(
                chat_id=CHANNEL_ID, audio=msg.audio.file_id, caption=build_caption(msg.caption or "")
            )
            posted_successfully = True
            print(f"📢 В канал отправлено аудио от {sender_id}")
        else:
            text = msg.text or msg.caption or ""
            fallback_video = _get_fallback_video()
            try:
                if fallback_video:
                    await context.bot.send_video(
                        chat_id=CHANNEL_ID, video=fallback_video, caption=build_caption(text)
                    )
                    posted_successfully = True
                    await query.edit_message_text(build_caption(text) + "\n✅ Запощено в канал с видео.")
                    print(f"📢 В канал отправлен текст {sender_id} с видео-заглушкой")
                else:
                    await context.bot.send_message(chat_id=CHANNEL_ID, text=build_caption(text))
                    posted_successfully = True
                    await query.edit_message_text(build_caption(text) + "\n⚠️ Видео-заглушка отсутствует.")
                    await _send_to_admins_async(
                        context,
                        lambda admin_id: context.bot.send_message(
                            admin_id,
                            "Видео youra.mp4 не найдено, отправлен только текстовый пост.",
                        ),
                    )
                    print(f"📢 В канал отправлен текст {sender_id} без медиа")
            except Exception as e:
                await query.edit_message_text(f"Ошибка при добавлении видео: {e}")
                posted_successfully = False
    except Exception as e:
        await query.edit_message_text(f"Ошибка при отправке в канал: {e}")
        posted_successfully = False

    if posted_successfully and sender_id:
        try:
            new_bal = await credit_user(sender_id, 15.0, context)
            await _send_to_admins_async(
                context,
                lambda admin_id: context.bot.send_message(
                    admin_id, f"✅ Автору (ID {sender_id}) начислено 15 руб. Новый баланс: {new_bal:.2f} руб."
                ),
            )
        except Exception:
            await _send_to_admins_async(
                context,
                lambda admin_id: context.bot.send_message(
                    admin_id, f"⚠️ Не удалось начислить средства автору (ID {sender_id})."
                ),
            )


async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать профиль пользователя со статистикой."""

    query = update.callback_query
    await query.answer()
    user = query.from_user
    username = f"@{user.username}" if user.username else "—"
    balance = get_balance(user.id)
    posts_count = count_user_posts(user.id)
    text = (
        f"👤 Профиль пользователя\n\n"
        f"💬 Username: {username}\n"
        f"🆔 TG ID: {user.id}\n"
        f"💰 Баланс: {balance:.2f} руб.\n"
        f"📝 Опубликованных постов: {posts_count}"
    )
    await send_or_edit(context, user.id, text, build_main_menu(user.id == PRIMARY_ADMIN_ID))


async def back_to_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Очистить состояние и вернуть пользователя в меню."""

    query = update.callback_query
    await query.answer()
    user_states.pop(query.from_user.id, None)
    await show_main_menu(query.from_user.id, context, "🏠 Главное меню")


async def withdraw_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверить возможность вывода и запросить реквизиты."""

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    balance = get_balance(user_id)
    print(f"💸 Пользователь {user_id} запросил вывод, баланс {balance:.2f}")
    if balance < 200:
        user_states[user_id] = {}
        await show_main_menu(user_id, context, "⚠️ Нельзя вывести меньше 200 руб. Возврат в меню.")
        return
    state = user_states.get(user_id, {})
    state["awaiting_withdraw"] = True
    state.pop("awaiting_withdraw_confirm", None)
    state.pop("withdraw_card", None)
    user_states[user_id] = state
    await send_or_edit(context, user_id, f"💸 На балансе {balance:.2f} руб. Укажите карту или номер СБП для вывода:")


async def links_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Вывести полезные ссылки на чат и канал."""

    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("💬 Чат", url="https://t.me/+joXHChzNX542ZjZi")],
        [InlineKeyboardButton("📢 Канал", url="https://t.me/+MRaBuj3Cx8gzZjEy")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")],
    ]
    await send_or_edit(context, query.from_user.id, "🔗 Полезные ссылки:", InlineKeyboardMarkup(keyboard))


async def delete_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запросить у пользователя ссылку и причину для удаления поста."""

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    print(f"🗑 Пользователь {user_id} нажал 'Удалить пост'")
    state = user_states.get(user_id, {})
    state["awaiting_delete_link"] = True
    state["awaiting_delete_reason"] = False
    state.pop("awaiting_delete_confirm", None)
    state.pop("delete_link", None)
    state.pop("delete_reason", None)
    user_states[user_id] = state
    await send_or_edit(context, user_id, "🔗 Введите ссылку на пост из канала:")


async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открыть админ-панель (доступно только основному администратору)."""

    query = update.callback_query
    await query.answer()
    if query.from_user.id != PRIMARY_ADMIN_ID:
        await query.answer("⛔ Недостаточно прав", show_alert=True)
        return
    keyboard = [
        [InlineKeyboardButton("📨 Сделать рассылку", callback_data="broadcast_start")],
        [InlineKeyboardButton("🔄 Синхронизация", callback_data="sync_db")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")],
    ]
    await send_or_edit(context, query.from_user.id, "🛠️ Админ панель", InlineKeyboardMarkup(keyboard))


async def broadcast_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запустить режим ввода текста для рассылки всем пользователям."""

    query = update.callback_query
    await query.answer()
    if query.from_user.id != PRIMARY_ADMIN_ID:
        await query.answer("⛔ Недостаточно прав", show_alert=True)
        return
    state = user_states.get(query.from_user.id, {})
    state["awaiting_broadcast"] = True
    user_states[query.from_user.id] = state
    await send_or_edit(context, query.from_user.id, "✉️ Отправьте текст для рассылки всем пользователям:")


async def sync_db_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Синхронизировать базу с текстовыми файлами по запросу администратора."""

    query = update.callback_query
    await query.answer()
    if query.from_user.id != PRIMARY_ADMIN_ID:
        await query.answer("⛔ Недостаточно прав", show_alert=True)
        return
    counts = sync_db_from_files()
    await send_or_edit(
        context,
        query.from_user.id,
        (
            "🔄 Синхронизация завершена успешно.\n"
            f"👥 Пользователи: {counts['users']}\n"
            f"💰 Балансы: {counts['balances']}\n"
            f"📝 История: {counts['history']}"
        ),
    )


async def withdraw_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработать подтверждение или отмену вывода средств."""

    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    state = user_states.get(user_id, {})
    action = query.data

    if action == "withdraw_confirm" and state.get("awaiting_withdraw_confirm"):
        card = state.get("withdraw_card", "—")
        balance = get_balance(user_id)
        set_balance(user_id, 0.0)
        await _send_to_admins_async(
            context,
            lambda admin_id: context.bot.send_message(
                admin_id,
                (
                    "Запрос на вывод средств\n"
                    f"Пользователь: @{user.username or '—'}\n"
                    f"ID: {user.id}\n"
                    f"Сумма: {balance:.2f} руб.\n"
                    f"Реквизиты: {card}"
                ),
            ),
        )
        print(
            f"💸 Подтверждён вывод: пользователь {user.id} ({user.username or '—'}), сумма {balance:.2f}, реквизиты {card}"
        )
        user_states[user_id] = {}
        await show_main_menu(user_id, context, "✅ Запрос на вывод отправлен. Баланс обнулён.", allow_edit=False)
    elif action == "withdraw_cancel":
        user_states[user_id] = {}
        print(f"💸 Пользователь {user_id} отменил вывод средств")
        await show_main_menu(user_id, context, "❌ Вывод отменён.", allow_edit=False)
    else:
        await query.answer("⚠️ Нет активного запроса на вывод", show_alert=True)


async def delete_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработать подтверждение или отмену удаления поста."""

    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    state = user_states.get(user_id, {})
    action = query.data

    if action == "delete_confirm" and state.get("awaiting_delete_confirm"):
        link = state.get("delete_link", "—")
        reason = state.get("delete_reason", "—")
        await _send_to_admins_async(
            context,
            lambda admin_id: context.bot.send_message(
                admin_id,
                (
                    "Удаление поста\n"
                    f"Ссылка: {link}\n"
                    f"Причина: {reason}\n"
                    f"ID: {user.id}\n"
                    f"Пользователь: @{user.username or '—'}"
                ),
            ),
        )
        print(
            f"🗑 Подтверждён запрос удаления: пользователь {user.id} ({user.username or '—'}), ссылка {link}, причина: {reason}"
        )
        user_states[user_id] = {}
        await show_main_menu(user_id, context, "✅ Запрос на удаление отправлен администратору.", allow_edit=False)
    elif action == "delete_cancel":
        user_states[user_id] = {}
        print(f"🗑 Пользователь {user_id} отменил запрос на удаление поста")
        await show_main_menu(user_id, context, "❌ Запрос на удаление отменён.", allow_edit=False)
    else:
        await query.answer("⚠️ Нет активного запроса на удаление", show_alert=True)


def main() -> None:
    """Точка входа: инициализация БД, хэндлеров и запуск бота."""

    _init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(back_to_menu_handler, pattern="^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(choose_mode, pattern="^(anon|non_anon)$"))
    app.add_handler(CallbackQueryHandler(choose_type, pattern="^(text|photo|video|audio)$"))
    app.add_handler(CallbackQueryHandler(confirm_or_cancel, pattern="^(confirm_send|cancel_send)$"))
    app.add_handler(CallbackQueryHandler(post_to_channel, pattern="^post_channel"))
    app.add_handler(CallbackQueryHandler(add_caption_handler, pattern="^add_caption$"))
    app.add_handler(CallbackQueryHandler(profile_handler, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(withdraw_handler, pattern="^withdraw$"))
    app.add_handler(CallbackQueryHandler(withdraw_confirm_handler, pattern="^withdraw_(confirm|cancel)$"))
    app.add_handler(CallbackQueryHandler(links_handler, pattern="^links$"))
    app.add_handler(CallbackQueryHandler(delete_post_handler, pattern="^delete_post$"))
    app.add_handler(CallbackQueryHandler(delete_confirm_handler, pattern="^delete_(confirm|cancel)$"))
    app.add_handler(CallbackQueryHandler(admin_panel_handler, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(broadcast_start_handler, pattern="^broadcast_start$"))
    app.add_handler(CallbackQueryHandler(sync_db_handler, pattern="^sync_db$"))

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("🤖 Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()

