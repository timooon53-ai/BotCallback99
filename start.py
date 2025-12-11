from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import os
from datetime import datetime

from cfg import TG_TOKEN

# ----------------- Настройки -----------------
TOKEN = TG_TOKEN
ADMIN_ID = 5625584447
CHANNEL_ID = -1003146319472  # ID канала (проверка подписки)
CHAT_ID = -1002908008015     # ID чата (проверка подписки)

BASE_PATH = r"C:\Users\Administrator\PycharmProjects\Bot99School"

USERS_FILE = f"{BASE_PATH}\\users.txt"
HISTORY_FILE = f"{BASE_PATH}\\history.txt"
CONCURS_FILE = f"{BASE_PATH}\\concurs.txt"
BALANCE_FILE = f"{BASE_PATH}\\balance.txt"

user_states = {}

# ======================== ФУНКЦИИ ДЛЯ БАЛАНСА ========================
def get_balance(user_id: int) -> float:
    if not os.path.exists(BALANCE_FILE):
        return 0.0
    with open(BALANCE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] == str(user_id):
                try:
                    return float(parts[1])
                except:
                    return 0.0
    return 0.0


def set_balance(user_id: int, balance: float):
    # Обеспечим наличие файла
    if not os.path.exists(BALANCE_FILE):
        open(BALANCE_FILE, "w", encoding="utf-8").close()

    # Читаем все строки и перезаписываем нужную
    lines = []
    found = False
    with open(BALANCE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 1 and parts[0] == str(user_id):
                lines.append(f"{user_id} {balance}\n")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{user_id} {balance}\n")
    with open(BALANCE_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


async def credit_user(user_id: int, amount: float, context: ContextTypes.DEFAULT_TYPE) -> float:
    """
    Асинхронно начисляет amount пользователю user_id, сохраняет баланс и пытается отправить уведомление.
    Возвращает новый баланс (float). В случае ошибки отправки уведомления баланс всё равно обновляется.
    """
    prev = get_balance(user_id)
    new = prev + amount
    set_balance(user_id, new)

    # Попробуем уведомить пользователя (если бот может ему писать)
    try:
        await context.bot.send_message(user_id, f"🎉 Вам начислено {amount:.0f} руб. Баланс: {new:.2f} руб.")
    except Exception:
        # Игнорируем ошибку отправки уведомления (пользователь мог заблокировать бота)
        pass

    return new


# ======================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ========================
def save_user(user_id: int) -> bool:
    """
    Сохраняет user_id в USERS_FILE.
    Возвращает True, если пользователь был добавлен впервые (новый).
    """
    if not os.path.exists(USERS_FILE):
        open(USERS_FILE, "w", encoding="utf-8").close()

    with open(USERS_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if str(user_id) in lines:
        return False

    with open(USERS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{user_id}\n")
    return True


def log_history(user, mode: str, text: str):
    username = f"@{user.username}" if user.username else "—"
    time_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{user.id} | {username} | {'Анонимное' if mode == 'anon' else 'Не анонимное'} | {text.strip()} | {time_now}\n"
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(line)


def save_to_concurs(user):
    if not os.path.exists(CONCURS_FILE):
        open(CONCURS_FILE, "w", encoding="utf-8").close()
    username = f"@{user.username}" if user.username else "—"
    line = f"{user.id} | {username} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    with open(CONCURS_FILE, "r+", encoding="utf-8") as f:
        existing = [l.strip() for l in f.readlines() if l.strip()]
        if any(str(user.id) == l.split("|")[0].strip() for l in existing):
            return False
        f.write(line)
    return True


async def check_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    errors = []
    is_subscribed_channel = False
    is_subscribed_chat = False

    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        if getattr(member, "status", None) not in ["left", "kicked"]:
            is_subscribed_channel = True
        else:
            errors.append("Не подписан на канал.")
    except Exception:
        errors.append("Не удалось проверить подписку на канал.")

    try:
        member = await context.bot.get_chat_member(CHAT_ID, user_id)
        if getattr(member, "status", None) not in ["left", "kicked"]:
            is_subscribed_chat = True
        else:
            errors.append("Не подписан(а) на чат.")
    except Exception:
        errors.append("Не удалось проверить подписку на чат.")

    return is_subscribed_channel, is_subscribed_chat, errors


# ======================== ОБРАБОТЧИКИ ========================
# ----------------- ОБРАБОТЧИК /START С ОБЯЗАТЕЛЬНОЙ ПОДПИСКОЙ -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.message.from_user
    user_id = user.id

    # Проверяем подписку на канал
    try:
        member = await context.bot.get_chat_member("@Mind4Not0Found4", user_id)
        if getattr(member, "status", None) in ["left", "kicked"]:
            raise Exception("Не подписан")
    except Exception:
        keyboard = [
            [InlineKeyboardButton("📢 Подписаться на канал", url="https://t.me/Mind4Not0Found4")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ Для использования бота нужно подписаться на канал @Mind4Not0Found4.\n\n"
            "После подписки нажмите /start снова.",
            reply_markup=reply_markup
        )
        return  # Дальше бот не даёт доступ к меню

    # Если новый пользователь — add to users + начислить 1 рубль
    is_new = save_user(user_id)
    if is_new:
        prev = get_balance(user_id)
        set_balance(user_id, prev + 1.0)
        try:
            await update.message.reply_text("🎉 Добро пожаловать! Вам начислено 1 рубль на баланс.")
        except Exception:
            pass

    keyboard = [
        [
            InlineKeyboardButton("🕵️ Отправить анонимно", callback_data="anon"),
            InlineKeyboardButton("👤 Отправить с именем", callback_data="non_anon"),
        ],
        [
            InlineKeyboardButton("🎁 Участвую в конкурсе", callback_data="contest"),
            InlineKeyboardButton("💼 Профиль", callback_data="profile"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Привет! 👋\nВыбери, как хочешь отправить сообщение или поучаствовать в конкурсе:", reply_markup=reply_markup
    )


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    mode = query.data
    user_states[user_id] = {"mode": mode}

    keyboard = [
        [InlineKeyboardButton("📝 Текст", callback_data="text")],
        [InlineKeyboardButton("🖼 Фото", callback_data="photo")],
        [InlineKeyboardButton("🎥 Видео", callback_data="video")],
        [InlineKeyboardButton("🎧 Аудио", callback_data="audio")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text="Что хочешь отправить? 🤔", reply_markup=reply_markup
    )


async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    msg_type = query.data
    # Сохраняем тип в состояние
    state = user_states.get(user_id, {})
    state["type"] = msg_type
    user_states[user_id] = state

    prompts = {
        "text": "✏️ Отправь мне текст, который хочешь переслать админу.",
        "photo": "🖼 Отправь фото для администратора.",
        "video": "🎥 Отправь видео для администраатора.",
        "audio": "🎧 Отправь аудио для администратора.",
    }
    await query.edit_message_text(text=prompts[msg_type])


# ----------------- обработка сообщений -----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # Только личка
    if update.message.chat.type != "private":
        return

    user = update.message.from_user
    user_id = user.id
    state = user_states.get(user_id)
    if not state:
        await update.message.reply_text("⚠️ Сначала используй /start.")
        return

    # Если ждем подпись от пользователя
    if state.get("awaiting_caption") and update.message.text:
        state["pending_caption"] = update.message.text
        state.pop("awaiting_caption", None)
        user_states[user_id] = state
        # Показываем кнопки отправки админу
        keyboard = [
            [
                InlineKeyboardButton("✅ Отправить админу", callback_data="confirm_send"),
                InlineKeyboardButton("❌ Отменить", callback_data="cancel_send"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"💬 Подпись сохранена!\nЕсли готово, отправь сообщение админу:",
            reply_markup=reply_markup
        )
        return

    msg_type = state.get("type")
    # ----------------- Проверка для медиа -----------------
    if msg_type in ["photo", "video", "audio"]:
        if (msg_type == "photo" and not update.message.photo) or \
           (msg_type == "video" and not update.message.video) or \
           (msg_type == "audio" and not update.message.audio):
            await update.message.reply_text("⚠️ Похоже, вы не отправили нужный файл. Попробуйте ещё раз.")
            return
        state["pending_message"] = update.message
        state["pending_caption"] = ""
        user_states[user_id] = state

        # Кнопки: добавить подпись / отправить сразу / отменить
        keyboard = [
            [
                InlineKeyboardButton("📝 Добавить подпись", callback_data="add_caption"),
                InlineKeyboardButton("✅ Отправить без подписи", callback_data="confirm_send"),
                InlineKeyboardButton("❌ Отменить", callback_data="cancel_send"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        hint_text = "✏️ Можете добавить подпись к медиа или сразу отправить админу."
        if msg_type == "photo":
            await update.message.reply_photo(
                photo=update.message.photo[-1].file_id,
                caption=hint_text,
                reply_markup=reply_markup
            )
        elif msg_type == "video":
            await update.message.reply_video(
                video=update.message.video.file_id,
                caption=hint_text,
                reply_markup=reply_markup
            )
        elif msg_type == "audio":
            await update.message.reply_audio(
                audio=update.message.audio.file_id,
                caption=hint_text,
                reply_markup=reply_markup
            )
        return

    # ----------------- Для текста -----------------
    if msg_type == "text" and update.message.text:
        state["pending_message"] = update.message
        user_states[user_id] = state
        keyboard = [
            [
                InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_send"),
                InlineKeyboardButton("❌ Отменить", callback_data="cancel_send"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"📄 Твой текст:\n\n{update.message.text}\n\nОтправить админу?",
            reply_markup=reply_markup
        )


# ----------------- обработчик добавления текста -----------------
async def add_caption_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_states.get(user_id)
    if not state or "pending_message" not in state:
        return await query.answer("⚠️ Нет сообщения для добавления текста.", show_alert=True)
    state["awaiting_caption"] = True
    user_states[user_id] = state
    try:
        await query.edit_message_caption("📝 Напишите текст, который хотите добавить к медиа.")
    except:
        await query.edit_message_text("📝 Напишите текст, который хотите добавить к медиа.")


# ----------------- подтверждение/отмена -----------------
async def confirm_or_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        try:
            await query.message.delete()
        except:
            pass
        return await query.message.reply_text("🚫 Отправка отменена.")

    # При отправке админу — формируем кнопку с payload-ом: post_channel:<sender_id>
    post_cb = f"post_channel:{user.id}"

    caption_text = "📨 Анонимное сообщение" if mode == "anon" else f"👤 От {user.first_name} (ID: {user.id})"
    media_caption = state.get("pending_caption", "")
    if media_caption:
        caption_text += f"\n\n💬 {media_caption}"

    admin_keyboard = [
        [InlineKeyboardButton("📢 Запостить в канал", callback_data=post_cb)]
    ]
    admin_markup = InlineKeyboardMarkup(admin_keyboard)

    try:
        if msg_type == "text":
            text_to_send = pending_message.text
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"{caption_text}\n\n{text_to_send}",
                reply_markup=admin_markup,
            )
            log_history(user, mode, text_to_send)
        else:
            if msg_type == "photo":
                await context.bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=pending_message.photo[-1].file_id,
                    caption=caption_text,
                    reply_markup=admin_markup,
                )
            elif msg_type == "video":
                await context.bot.send_video(
                    chat_id=ADMIN_ID,
                    video=pending_message.video.file_id,
                    caption=caption_text,
                    reply_markup=admin_markup,
                )
            elif msg_type == "audio":
                await context.bot.send_audio(
                    chat_id=ADMIN_ID,
                    audio=pending_message.audio.file_id,
                    caption=caption_text,
                    reply_markup=admin_markup,
                )
            log_history(user, mode, media_caption or "[Медиа отправлено]")
    except Exception as e:
        try:
            await context.bot.send_message(ADMIN_ID, f"Ошибка при пересылке от {user.id}: {e}")
        except:
            pass

    user_states.pop(user_id, None)
    try:
        await query.message.delete()
    except:
        pass
    await query.message.reply_text("✅ Сообщение успешно отправлено админу!")


# ======================== кнопка для публикации в канал ========================
async def post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Только админ может нажимать
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Только админ может постить в канал.")
        return

    # Разбираем callback_data: ожидаем "post_channel:<sender_id>"
    data = query.data or ""
    parts = data.split(":")
    sender_id = None
    if len(parts) >= 2 and parts[0] == "post_channel":
        try:
            sender_id = int(parts[1])
        except:
            sender_id = None

    msg = query.message
    footer = "\n\n✉️ Отправить анонимное сообщение в канал - @School99InfBot\n🎉 Наш веселенький чат - https://t.me/+joXHChzNX542ZjZi"

    def build_caption(text):
        return f"{text}{footer}"

    posted_successfully = False
    try:
        # Если это сообщение с текстом (и без медиа)
        if msg.text and not (msg.photo or msg.video or msg.audio):
            try:
                await context.bot.send_message(chat_id=CHANNEL_ID, text=build_caption(msg.text))
                posted_successfully = True
                await query.edit_message_text(build_caption(msg.text) + "\n✅ Запощено в канал (текст)")
            except Exception as e:
                await query.edit_message_text(f"Ошибка при постинге текста: {e}")
                posted_successfully = False
        elif msg.caption:
            # Если сообщение содержит caption + media
            try:
                if msg.photo:
                    await context.bot.send_photo(chat_id=CHANNEL_ID, photo=msg.photo[-1].file_id, caption=build_caption(msg.caption))
                elif msg.video:
                    await context.bot.send_video(chat_id=CHANNEL_ID, video=msg.video.file_id, caption=build_caption(msg.caption))
                elif msg.audio:
                    await context.bot.send_audio(chat_id=CHANNEL_ID, audio=msg.audio.file_id, caption=build_caption(msg.caption))
                else:
                    await context.bot.send_message(chat_id=CHANNEL_ID, text=build_caption(msg.caption))
                posted_successfully = True
                try:
                    await query.edit_message_caption(build_caption(msg.caption) + "\n✅ Запощено в канал")
                except:
                    await query.edit_message_text(build_caption(msg.caption) + "\n✅ Запощено в канал")
            except Exception as e:
                await query.edit_message_text(f"Ошибка при постинге медиа: {e}")
                posted_successfully = False
        else:
            # fallback: отправляем текст сообщения (если есть)
            try:
                text = msg.text or msg.caption or ""
                await context.bot.send_message(chat_id=CHANNEL_ID, text=build_caption(text))
                posted_successfully = True
                await query.edit_message_text(build_caption(text) + "\n✅ Запощено в канал")
            except Exception as e:
                await query.edit_message_text(f"Ошибка при постинге (fallback): {e}")
                posted_successfully = False
    except Exception as e:
        await query.edit_message_text(f"Ошибка при отправке в канал: {e}")
        posted_successfully = False

    # Если успешно — начисляем 15 руб. автору (если sender_id известен)
    if posted_successfully and sender_id:
        try:
            new_bal = await credit_user(sender_id, 15.0, context)
            # Уведомляем админа о начислении
            try:
                await context.bot.send_message(ADMIN_ID, f"✅ Автору (ID {sender_id}) начислено 15 руб. Новый баланс: {new_bal:.2f} руб.")
            except Exception:
                pass
        except Exception:
            try:
                await context.bot.send_message(ADMIN_ID, f"⚠️ Не удалось начислить средства автору (ID {sender_id}).")
            except:
                pass


# ======================== ЛОГИКА КОНКУРСА ========================
async def contest_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rules = (
        "🎁 Условия конкурса:\n\n"
        "1️⃣ Подписаться на канал - @Sch0ol99\n"
        "2️⃣ Перейти в чат - https://t.me/+joXHChzNX542ZjZi\n"
        "3️⃣ Пригласить минимум одного друга в канал\n\n"
        "Нажмите кнопку «Подтвердить», если вы выполнили все условия. "
        "Бот проверит подписку на канал и чат и добавит вас в список участников."
    )
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="contest_confirm")],
        [InlineKeyboardButton("❌ Отмена", callback_data="contest_cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(rules, reply_markup=reply_markup)
    except:
        await query.message.reply_text(rules, reply_markup=reply_markup)


async def contest_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text("Отменено. Если захотите — снова нажмите кнопку 'Участвую в конкурсе' в /start.")
    except:
        await query.message.reply_text("Отменено. Если захотите — снова нажмите кнопку 'Участвую в конкурсе' в /start.")


async def contest_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id

    is_chan, is_chat, errors = await check_subscription(context, user_id)

    if not is_chan or not is_chat:
        missing = []
        if not is_chan:
            missing.append(f"— Подписаться на канал (id {CHANNEL_ID}) / @Sch0ol99")
        if not is_chat:
            missing.append(f"— Вступить в чат (id {CHAT_ID}) / https://t.me/+joXHChzNX542ZjZi")
        text = "⚠️ Для участия нужно выполнить условия.\n\nПожалуйста, выполните следующее:\n" + "\n".join(missing) + \
               "\n\nПосле подписки нажмите снова «Подтвердить»."
        try:
            await query.edit_message_text(text)
        except:
            await query.message.reply_text(text)
        return

    added = save_to_concurs(user)
    if not added:
        try:
            await query.edit_message_text("✅ Вы уже участвуете в конкурсе — ваш ID уже добавлен.")
        except:
            await query.message.reply_text("✅ Вы уже участвуете в конкурсе — ваш ID уже добавлен.")
        return

    try:
        await query.edit_message_text("🎉 Отлично! Вы успешно зарегистрированы в конкурсе. Удачи!")
    except:
        await query.message.reply_text("🎉 Отлично! Вы успешно зарегистрированы в конкурсе. Удачи!")

    try:
        username = f"@{user.username}" if user.username else "—"
        await context.bot.send_message(ADMIN_ID, f"Новый участник конкурса: {user.id} | {username}")
    except:
        pass


# ======================== ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ========================
async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    username = f"@{user.username}" if user.username else "—"
    balance = get_balance(user.id)

    text = (
        f"👤 Профиль пользователя\n\n"
        f"💬 Username: {username}\n"
        f"🆔 TG ID: {user.id}\n"
        f"💰 Баланс: {balance} руб."
    )

    try:
        await query.edit_message_text(text)
    except:
        await query.message.reply_text(text)


# ======================== MAIN ========================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Command
    app.add_handler(CommandHandler("start", start))

    # Меню
    app.add_handler(CallbackQueryHandler(choose_mode, pattern="^(anon|non_anon)$"))
    app.add_handler(CallbackQueryHandler(choose_type, pattern="^(text|photo|video|audio)$"))
    app.add_handler(CallbackQueryHandler(confirm_or_cancel, pattern="^(confirm_send|cancel_send)$"))
    # Отлавливаем любые callback_data, начинающиеся с post_channel
    app.add_handler(CallbackQueryHandler(post_to_channel, pattern="^post_channel"))
    app.add_handler(CallbackQueryHandler(add_caption_handler, pattern="^add_caption$"))

    # Конкурс
    app.add_handler(CallbackQueryHandler(contest_start, pattern="^contest$"))
    app.add_handler(CallbackQueryHandler(contest_confirm, pattern="^contest_confirm$"))
    app.add_handler(CallbackQueryHandler(contest_cancel, pattern="^contest_cancel$"))

    # Профиль
    app.add_handler(CallbackQueryHandler(profile_handler, pattern="^profile$"))

    # Сообщения (в личке)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("🤖 Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
