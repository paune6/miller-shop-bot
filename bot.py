import json
import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ContextTypes
)

# ===== НАСТРОЙКИ =====
TOKEN = "8733856394:AAG4Sou0QyOigAQNco8GPL2eDQI9asDZOa0"
ADMIN_ID = 5078387190
ORDERS_FILE = "orders.json"
LOG_FILE = "bot.log"

# Состояния диалога пользователя
CHOOSING_CATEGORY, AWAITING_DESCRIPTION = range(2)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ===== РАБОТА С ФАЙЛОМ ЗАКАЗОВ =====
def load_orders():
    if os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_orders(orders):
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, indent=2, ensure_ascii=False)

# Глобальный словарь orders загружается при старте
orders = load_orders()

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def update_order(user_id: int, data: dict):
    """Обновляет запись о заказе и сохраняет в файл."""
    orders[str(user_id)] = data
    save_orders(orders)

def get_order(user_id: int):
    return orders.get(str(user_id))

# ===== ПОЛЬЗОВАТЕЛЬСКАЯ ЧАСТЬ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Главное меню выбора категории."""
    keyboard = [
        [InlineKeyboardButton("🤖 Купить бота", callback_data="buy_bot")],
        [InlineKeyboardButton("🌐 Купить сайт", callback_data="buy_site")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_order")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🏪 *Miller Shop*\nВыберите, что хотите заказать:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return CHOOSING_CATEGORY

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    category = query.data
    if category == "cancel_order":
        await query.edit_message_text("❌ Заказ отменён. Чтобы начать новый, введите /start")
        return ConversationHandler.END

    cat_name = "Бот" if category == "buy_bot" else "Сайт"
    context.user_data["order_category"] = cat_name
    # Кнопка "Отмена" на этапе описания
    keyboard = [[InlineKeyboardButton("❌ Отменить заказ", callback_data="cancel_order")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Вы выбрали: *{cat_name}*\n\nОпишите подробно, что вам нужно (функции, требования):\n\n_Отправьте текстовое сообщение._",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return AWAITING_DESCRIPTION

async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    description = update.message.text
    user = update.effective_user
    category = context.user_data.get("order_category", "Не указана")

    # Сохраняем заказ со статусом "pending"
    order_data = {
        "category": category,
        "description": description,
        "status": "pending",
        "price": None,
        "username": user.username,
        "first_name": user.first_name,
        "created_at": datetime.now().isoformat(),
        "updated_at": None
    }
    update_order(user.id, order_data)

    # Отправляем админу с кнопками
    keyboard = [
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"accept_{user.id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{user.id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    user_link = f"[{user.first_name}](tg://user?id={user.id})"
    user_info = f"@{user.username}" if user.username else f"id{user.id}"
    admin_msg = (
        f"🆕 **Новый заказ в Miller Shop!**\n\n"
        f"📦 Категория: *{category}*\n"
        f"📝 Описание:\n`{description}`\n\n"
        f"👤 Пользователь: {user_link} ({user_info})\n"
        f"🆔 ID: `{user.id}`"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, reply_markup=reply_markup, parse_mode="Markdown")
        await update.message.reply_text(
            "✅ Заказ отправлен администратору. Ожидайте подтверждения и цены.\n"
            "Вы можете проверить статус командой /myorders"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки админу: {e}")
        await update.message.reply_text("⚠️ Не удалось отправить заказ. Попробуйте позже.")
        orders.pop(str(user.id), None)
        save_orders(orders)
        return ConversationHandler.END

    return ConversationHandler.END

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена заказа пользователем через кнопку или команду /cancel."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("❌ Заказ отменён. Чтобы начать новый, введите /start")
    else:
        await update.message.reply_text("❌ Заказ отменён. /start для нового заказа")
    return ConversationHandler.END

async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает пользователю его заказы."""
    user_id = str(update.effective_user.id)
    order = orders.get(user_id)
    if not order:
        await update.message.reply_text("У вас нет заказов. Создайте новый через /start")
        return
    status_emoji = {
        "pending": "⏳ ожидает",
        "accepted": "✅ принят",
        "rejected": "❌ отклонён"
    }.get(order["status"], order["status"])
    price_str = f", цена: {order['price']}" if order.get("price") else ""
    await update.message.reply_text(
        f"📋 *Ваш последний заказ:*\n"
        f"Категория: {order['category']}\n"
        f"Статус: {status_emoji}{price_str}\n"
        f"Описание: {order['description'][:100]}...\n\n"
        f"Для нового заказа введите /start",
        parse_mode="Markdown"
    )

# ===== АДМИНИСТРАТОРСКАЯ ЧАСТЬ =====
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия кнопок админа (принять/отклонить)."""
    query = update.callback_query
    await query.answer()
    data = query.data
    action, user_id_str = data.split("_")
    user_id = int(user_id_str)
    order = get_order(user_id)
    if not order or order["status"] != "pending":
        await query.edit_message_text("❌ Заказ уже обработан или не найден.")
        return

    if action == "accept":
        # Переходим в режим ожидания цены (сохраняем в context.user_data для админа)
        context.user_data["awaiting_price_for"] = user_id
        await query.edit_message_text(
            f"💵 Введите цену для заказа пользователя (ID: {user_id}):\n"
            "Примеры: `5000 руб`, `$200`, `15000`\n\n"
            "Для отмены введите /cancel_price"
        )
        # Ответ админу никуда не отправляем, он уже в диалоге
    elif action == "reject":
        order["status"] = "rejected"
        order["updated_at"] = datetime.now().isoformat()
        update_order(user_id, order)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"😞 Ваш заказ на *{order['category']}* отклонён администратором.\nМожете создать новый через /start",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить отказ пользователю {user_id}: {e}")
        await query.edit_message_text(f"✅ Заказ пользователя {user_id} отклонён. Пользователь уведомлён.")
    await query.answer()

async def admin_price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает цену от админа и завершает заказ."""
    user_id = context.user_data.get("awaiting_price_for")
    if not user_id:
        await update.message.reply_text("Вы не в режиме ввода цены. Ничего не делаю.")
        return

    price_text = update.message.text.strip()
    if not price_text:
        await update.message.reply_text("Цена не может быть пустой. Введите число или сумму.\nОтмена - /cancel_price")
        return

    order = get_order(user_id)
    if not order or order["status"] != "pending":
        await update.message.reply_text("❌ Заказ уже обработан или не существует.")
        context.user_data.pop("awaiting_price_for", None)
        return

    # Сохраняем цену как есть (строка)
    order["status"] = "accepted"
    order["price"] = price_text
    order["updated_at"] = datetime.now().isoformat()
    update_order(user_id, order)

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 *Ваш заказ принят!*\n\n"
                 f"📦 Категория: {order['category']}\n"
                 f"💰 Цена: *{price_text}*\n\n"
                 f"С вами свяжется администратор.\n"
                 f"Спасибо, что выбрали Miller Shop!",
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"✅ Пользователю {user_id} отправлено сообщение с ценой {price_text}.")
    except Exception as e:
        logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
        await update.message.reply_text(f"⚠️ Не удалось отправить сообщение пользователю {user_id}.")

    context.user_data.pop("awaiting_price_for", None)

async def cancel_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена ожидания ввода цены админом."""
    if context.user_data.get("awaiting_price_for"):
        user_id = context.user_data.pop("awaiting_price_for")
        await update.message.reply_text(f"❌ Ввод цены отменён. Заказ пользователя {user_id} остаётся в статусе 'pending'.")
    else:
        await update.message.reply_text("Нет активного ожидания цены.")

async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает администратору список всех заказов (только active/pending)."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Нет прав.")
        return
    pending_list = []
    for uid, order in orders.items():
        if order["status"] == "pending":
            pending_list.append(f"🆔 {uid} | {order['category']} | {order['description'][:50]}...")
    if not pending_list:
        await update.message.reply_text("Активных заказов нет.")
        return
    text = "*Активные заказы (ожидают решения):*\n" + "\n".join(pending_list)
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /reply <user_id> <текст> – ответить пользователю от имени админа."""
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: `/reply 123456789 Текст сообщения`", parse_mode="Markdown")
        return
    try:
        user_id = int(args[0])
        message_text = " ".join(args[1:])
        await context.bot.send_message(chat_id=user_id, text=f"📨 *Сообщение от администратора Miller Shop:*\n{message_text}", parse_mode="Markdown")
        await update.message.reply_text(f"✅ Сообщение отправлено пользователю {user_id}")
    except ValueError:
        await update.message.reply_text("ID пользователя должен быть числом.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика заказов для админа."""
    if update.effective_user.id != ADMIN_ID:
        return
    total = len(orders)
    pending = sum(1 for o in orders.values() if o["status"] == "pending")
    accepted = sum(1 for o in orders.values() if o["status"] == "accepted")
    rejected = sum(1 for o in orders.values() if o["status"] == "rejected")
    await update.message.reply_text(
        f"📊 *Статистика Miller Shop*\n"
        f"Всего заказов: {total}\n"
        f"В ожидании: {pending}\n"
        f"Принято: {accepted}\n"
        f"Отклонено: {rejected}",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Miller Shop Bot*\n\n"
        "*Пользовательские команды:*\n"
        "/start – начать заказ\n"
        "/myorders – статус вашего заказа\n"
        "/cancel – отменить текущий заказ\n"
        "/help – это сообщение\n\n"
        "*Административные команды:*\n"
        "/orders – список ожидающих заказов\n"
        "/reply <id> <текст> – ответить пользователю\n"
        "/stats – статистика заказов\n"
        "/cancel_price – отменить ввод цены"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ===== ЗАПУСК =====
def main():
    application = Application.builder().token(TOKEN).build()

    # Диалог пользователя
    user_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_CATEGORY: [CallbackQueryHandler(category_selected, pattern="^(buy_bot|buy_site|cancel_order)$")],
            AWAITING_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_order)],
        allow_reentry=True,
    )

    application.add_handler(user_conv)
    application.add_handler(CommandHandler("myorders", my_orders))
    application.add_handler(CommandHandler("help", help_command))

    # Админ-обработчики
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^(accept|reject)_"))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=ADMIN_ID), admin_price_handler))
    application.add_handler(CommandHandler("cancel_price", cancel_price, filters.User(user_id=ADMIN_ID)))
    application.add_handler(CommandHandler("orders", admin_orders, filters.User(user_id=ADMIN_ID)))
    application.add_handler(CommandHandler("reply", admin_reply, filters.User(user_id=ADMIN_ID)))
    application.add_handler(CommandHandler("stats", stats, filters.User(user_id=ADMIN_ID)))

    # Команда для получения ID
    async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(f"Ваш ID: `{update.effective_user.id}`", parse_mode="Markdown")
    application.add_handler(CommandHandler("id", get_id))

    logger.info("Бот Miller Shop запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()