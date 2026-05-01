import json
import os
import logging
import uuid
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ContextTypes
)


TOKEN = "8733856394:AAG4Sou0QyOigAQNco8GPL2eDQI9asDZOa0" 
ADMIN_ID = 5078387190
ORDERS_FILE = "orders.json"


CHOOSING_CATEGORY, AWAITING_DESCRIPTION, CONFIRMING_ORDER = range(3)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def load_orders():
    if os.path.exists(ORDERS_FILE):
        try:
            with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_orders(orders):
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, indent=2, ensure_ascii=False)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("Купить бота", callback_data="cat_Бот")],
        [InlineKeyboardButton("Купить сайт", callback_data="cat_Сайт")],
        [InlineKeyboardButton("Мои заказы", callback_data="list_orders")]
    ]
    text = "👋 *Добро пожаловать в Miller Shop!*\nВыберите нужную категорию:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CHOOSING_CATEGORY

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "list_orders":
        await show_my_orders(query, context)
        return ConversationHandler.END

    category = query.data.split("_")[1]
    context.user_data["tmp_category"] = category
    
    await query.edit_message_text(
        f" Выбрано: *{category}*\n\nТеперь опишите ваше техническое задание (ТЗ) одним сообщением:",
        parse_mode="Markdown"
    )
    return AWAITING_DESCRIPTION

async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["tmp_desc"] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton(" Отправить заказ", callback_data="confirm_send")],
        [InlineKeyboardButton(" Сбросить", callback_data="cancel_order")]
    ]
    await update.message.reply_text(
        f"*Проверьте ваш заказ:*\n\n"
        f"Категория: {context.user_data['tmp_category']}\n"
        f"ТЗ: {context.user_data['tmp_desc']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CONFIRMING_ORDER

async def send_order_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    order_id = str(uuid.uuid4())[:8] 
    
    order_data = {
        "id": order_id,
        "user_id": user.id,
        "category": context.user_data["tmp_category"],
        "description": context.user_data["tmp_desc"],
        "status": "pending",
        "price": None,
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M")
    }

    orders = load_orders()
    orders[order_id] = order_data
    save_orders(orders)


    keyboard = [
        [
            InlineKeyboardButton("Принять", callback_data=f"adm_accept_{order_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"adm_reject_{order_id}")
        ]
    ]
    admin_text = (
        f"*Новый заказ #{order_id}*\n\n"
        f"От: {user.mention_markdown_v2()} (`{user.id}`)\n"
        f"Категория: {order_data['category']}\n"
        f"ТЗ: {order_data['description']}"
    )
    
    await context.bot.send_message(ADMIN_ID, admin_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    await query.edit_message_text("Заказ отправлен! Мы сообщим вам, когда администратор установит цену.")
    return ConversationHandler.END


async def admin_handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    action = data[1]
    order_id = data[2]
    
    orders = load_orders()
    order = orders.get(order_id)

    if not order:
        await query.answer("Заказ не найден!")
        return

    if action == "accept":
        context.user_data["active_order_id"] = order_id
        await query.edit_message_text(f"Введите цену для заказа #{order_id} (или напишите 'Бесплатно'):")
    
    elif action == "reject":
        order["status"] = "rejected"
        save_orders(orders)
        await query.edit_message_text(f"Заказ #{order_id} отклонен.")
        await context.bot.send_message(order["user_id"], f"Ваш заказ *#{order_id}* был отклонен администратором.")

async def admin_receive_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, ждем ли мы цену
    order_id = context.user_data.get("active_order_id")
    if not order_id or update.effective_user.id != ADMIN_ID:
        return

    price = update.message.text
    orders = load_orders()
    order = orders.get(order_id)
    
    if order:
        order["status"] = "accepted"
        order["price"] = price
        save_orders(orders)
        
        await update.message.reply_text(f"Цена для #{order_id} установлена: {price}")
        
        user_text = (
            f"*Ваш заказ принят!*\n\n"
            f"Номер: `{order_id}`\n"
            f"Стоимость: *{price}*\n\n"
            f"Администратор свяжется с вами для уточнения деталей."
        )
        await context.bot.send_message(order["user_id"], user_text, parse_mode="Markdown")
    
    context.user_data.pop("active_order_id", None)


async def show_my_orders(query, context):
    orders = load_orders()
    user_id = query.from_user.id
    user_orders = [o for o in orders.values() if o["user_id"] == user_id]
    
    if not user_orders:
        await query.message.reply_text("У вас пока нет заказов.")
        return

    text = "*Ваша история заказов:*\n\n"
    for o in user_orders[-5:]:
        status = " Ожидает" if o["status"] == "pending" else " Оплачено" if o["status"] == "accepted" else "❌ Отказ"
        price = f" | Цена: {o['price']}" if o['price'] else ""
        text += f"• #{o['id']} [{o['category']}] - {status}{price}\n"
    
    await query.message.reply_text(text, parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(" Действие отменено.")
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_CATEGORY: [CallbackQueryHandler(category_selected, pattern="^(cat_|list_orders)")],
            AWAITING_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description)],
            CONFIRMING_ORDER: [
                CallbackQueryHandler(send_order_to_admin, pattern="confirm_send"),
                CallbackQueryHandler(start, pattern="cancel_order")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
  
    app.add_handler(CallbackQueryHandler(admin_handle_callback, pattern="^adm_"))

    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), admin_receive_price))

    print("Miller Shop Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()