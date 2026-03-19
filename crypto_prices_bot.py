import os
import logging
import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SYMBOLS = ["ETHUSDT", "BTCUSDT", "TONUSDT", "APTUSDT", "DOTUSDT"]
ALERT_THRESHOLD = 2.0

last_prices = {}
last_alerts = {}

paper_trade = {
    "enabled": False,
    "symbol": "ETHUSDT",
    "entry": None,
    "stop_loss": None,
    "take_profit": None,
    "usd_amount": None,
    "in_position": False,
    "entry_price": None,
    "coin_amount": None,
    "last_result": None,
}


def get_main_keyboard():
    keyboard = [
        ["📊 Цены сейчас", "📈 Paper статус"],
        ["📋 Paper результат", "⛔ Остановить бота"],
        ["🧪 ETH paper 2200/2180/2220/100", "🛑 Paper OFF"],
        ["ℹ️ Помощь"],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выбери действие 👇",
    )


def get_prices():
    symbols = ",".join([f'"{s}"' for s in SYMBOLS])
    url = f"https://api.mexc.com/api/v3/ticker/24hr?symbols=[{symbols}]"

    response = requests.get(url, timeout=10)
    response.raise_for_status()
    raw_data = response.json()

    data = {}
    for coin in raw_data:
        if coin["symbol"] in SYMBOLS:
            data[coin["symbol"]] = {
                "price": float(coin["lastPrice"]),
                "change": float(coin["priceChangePercent"]),
            }

    return data


def build_prices_message(prices: dict) -> str:
    message = "📊 Актуальные цены:\n\n"
    for symbol, data in prices.items():
        price = data["price"]
        change = data["change"]
        emoji = "🟢" if change >= 0 else "🔴"
        message += f"{symbol}: ${price:.4f} ({emoji} {change:.2f}%)\n"
    return message


def build_help_message() -> str:
    return (
        "🤖 Меню готово\n\n"
        "Кнопки:\n"
        "📊 Цены сейчас — показать цены сразу\n"
        "📈 Paper статус — статус paper trade\n"
        "📋 Paper результат — последняя закрытая сделка\n"
        "🧪 ETH paper 2200/2180/2220/100 — быстрый запуск тест-сделки\n"
        "🛑 Paper OFF — выключить paper trade\n"
        "⛔ Остановить бота — остановить таймеры\n\n"
        "Команды тоже работают:\n"
        "/start\n"
        "/now\n"
        "/stop\n"
        "/paper_on 2200 2180 2220 100\n"
        "/paper_off\n"
        "/paper_status\n"
        "/paper_result"
    )


def enable_paper_trade(entry: float, stop_loss: float, take_profit: float, usd_amount: float):
    global paper_trade

    paper_trade["enabled"] = True
    paper_trade["entry"] = entry
    paper_trade["stop_loss"] = stop_loss
    paper_trade["take_profit"] = take_profit
    paper_trade["usd_amount"] = usd_amount
    paper_trade["in_position"] = False
    paper_trade["entry_price"] = None
    paper_trade["coin_amount"] = None
    paper_trade["last_result"] = None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    keyboard = get_main_keyboard()

    await update.message.reply_text(
        "Готово ✅\n\n"
        "Я буду:\n"
        "• присылать цены каждые 10 минут\n"
        "• отдельно писать, если монета растёт или падает на 2%+\n"
        "• следить за paper trade по ETHUSDT\n\n"
        "Теперь можно пользоваться кнопками 👇",
        reply_markup=keyboard,
    )

    for job in context.job_queue.get_jobs_by_name(f"{chat_id}_prices"):
        job.schedule_removal()

    for job in context.job_queue.get_jobs_by_name(f"{chat_id}_alerts"):
        job.schedule_removal()

    for job in context.job_queue.get_jobs_by_name(f"{chat_id}_paper"):
        job.schedule_removal()

    context.job_queue.run_repeating(
        send_prices,
        interval=600,
        first=1,
        chat_id=chat_id,
        name=f"{chat_id}_prices",
    )

    context.job_queue.run_repeating(
        check_alerts,
        interval=60,
        first=10,
        chat_id=chat_id,
        name=f"{chat_id}_alerts",
    )

    context.job_queue.run_repeating(
        check_paper_trade,
        interval=15,
        first=5,
        chat_id=chat_id,
        name=f"{chat_id}_paper",
    )


async def now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        prices = get_prices()
        message = build_prices_message(prices)
        await update.message.reply_text(message, reply_markup=get_main_keyboard())
    except Exception as e:
        logger.exception("Ошибка в /now")
        await update.message.reply_text(
            f"Ошибка в /now: {e}",
            reply_markup=get_main_keyboard(),
        )


async def send_prices(context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = context.job.chat_id
        prices = get_prices()
        message = build_prices_message(prices)
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=get_main_keyboard(),
        )
    except Exception:
        logger.exception("Ошибка в send_prices")


async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    global last_prices, last_alerts

    try:
        chat_id = context.job.chat_id
        prices = get_prices()

        for symbol, data in prices.items():
            price = data["price"]

            if symbol in last_prices:
                old_price = last_prices[symbol]
                diff = ((price - old_price) / old_price) * 100

                if abs(diff) >= ALERT_THRESHOLD:
                    last_alert = last_alerts.get(symbol, 0)

                    if abs(diff - last_alert) >= 0.5:
                        alert_text = "🚀 растёт" if diff > 0 else "🔻 падает"

                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ {symbol} {alert_text} на {diff:.2f}%",
                            reply_markup=get_main_keyboard(),
                        )

                        last_alerts[symbol] = diff

        last_prices = {symbol: data["price"] for symbol, data in prices.items()}
    except Exception:
        logger.exception("Ошибка в check_alerts")


async def paper_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        entry = float(context.args[0])
        stop_loss = float(context.args[1])
        take_profit = float(context.args[2])
        usd_amount = float(context.args[3])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Используй так:\n/paper_on 2200 2180 2220 100",
            reply_markup=get_main_keyboard(),
        )
        return

    enable_paper_trade(entry, stop_loss, take_profit, usd_amount)

    await update.message.reply_text(
        f"✅ Paper mode включён\n"
        f"Symbol: ETHUSDT\n"
        f"Вход: {entry}\n"
        f"Stop-loss: {stop_loss}\n"
        f"Take-profit: {take_profit}\n"
        f"Сумма входа: ${usd_amount}",
        reply_markup=get_main_keyboard(),
    )


async def paper_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global paper_trade

    paper_trade["enabled"] = False
    paper_trade["in_position"] = False
    paper_trade["entry_price"] = None
    paper_trade["coin_amount"] = None

    await update.message.reply_text(
        "🛑 Paper mode выключен",
        reply_markup=get_main_keyboard(),
    )


async def paper_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = (
        f"Paper mode: {'ON' if paper_trade['enabled'] else 'OFF'}\n"
        f"Symbol: {paper_trade['symbol']}\n"
        f"Entry: {paper_trade['entry']}\n"
        f"Stop-loss: {paper_trade['stop_loss']}\n"
        f"Take-profit: {paper_trade['take_profit']}\n"
        f"USD amount: {paper_trade['usd_amount']}\n"
        f"In position: {paper_trade['in_position']}\n"
        f"Entry price: {paper_trade['entry_price']}\n"
        f"Coin amount: {paper_trade['coin_amount']}"
    )
    await update.message.reply_text(status, reply_markup=get_main_keyboard())


async def paper_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = paper_trade["last_result"]
    if result is None:
        await update.message.reply_text(
            "Пока нет закрытых paper-сделок",
            reply_markup=get_main_keyboard(),
        )
    else:
        await update.message.reply_text(result, reply_markup=get_main_keyboard())


async def check_paper_trade(context: ContextTypes.DEFAULT_TYPE):
    global paper_trade

    try:
        if not paper_trade["enabled"]:
            return

        chat_id = context.job.chat_id
        prices = get_prices()

        eth = prices.get("ETHUSDT")
        if not eth:
            return

        current_price = eth["price"]

        if not paper_trade["in_position"]:
            if current_price <= paper_trade["entry"]:
                coin_amount = paper_trade["usd_amount"] / current_price

                paper_trade["in_position"] = True
                paper_trade["entry_price"] = current_price
                paper_trade["coin_amount"] = coin_amount

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🟢 Paper BUY ETHUSDT по {current_price:.2f}\n"
                        f"Сумма входа: ${paper_trade['usd_amount']:.2f}\n"
                        f"Куплено ETH: {coin_amount:.6f}"
                    ),
                    reply_markup=get_main_keyboard(),
                )
            return

        if current_price <= paper_trade["stop_loss"]:
            exit_value = paper_trade["coin_amount"] * current_price
            pnl = exit_value - paper_trade["usd_amount"]
            pnl_pct = (pnl / paper_trade["usd_amount"]) * 100

            text = (
                f"🔴 Paper SELL ETHUSDT по stop-loss: {current_price:.2f}\n"
                f"Сумма входа: ${paper_trade['usd_amount']:.2f}\n"
                f"Сумма выхода: ${exit_value:.2f}\n"
                f"Результат: {pnl:.2f}$ ({pnl_pct:.2f}%)"
            )

            paper_trade["last_result"] = text
            paper_trade["in_position"] = False
            paper_trade["entry_price"] = None
            paper_trade["coin_amount"] = None

            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=get_main_keyboard(),
            )
            return

        if current_price >= paper_trade["take_profit"]:
            exit_value = paper_trade["coin_amount"] * current_price
            pnl = exit_value - paper_trade["usd_amount"]
            pnl_pct = (pnl / paper_trade["usd_amount"]) * 100

            text = (
                f"🚀 Paper SELL ETHUSDT по take-profit: {current_price:.2f}\n"
                f"Сумма входа: ${paper_trade['usd_amount']:.2f}\n"
                f"Сумма выхода: ${exit_value:.2f}\n"
                f"Результат: {pnl:.2f}$ ({pnl_pct:.2f}%)"
            )

            paper_trade["last_result"] = text
            paper_trade["in_position"] = False
            paper_trade["entry_price"] = None
            paper_trade["coin_amount"] = None

            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=get_main_keyboard(),
            )
    except Exception:
        logger.exception("Ошибка в check_paper_trade")


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    for job in context.job_queue.get_jobs_by_name(f"{chat_id}_prices"):
        job.schedule_removal()

    for job in context.job_queue.get_jobs_by_name(f"{chat_id}_alerts"):
        job.schedule_removal()

    for job in context.job_queue.get_jobs_by_name(f"{chat_id}_paper"):
        job.schedule_removal()

    await update.message.reply_text(
        "Остановлено ❌",
        reply_markup=get_main_keyboard(),
    )


async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        build_help_message(),
        reply_markup=get_main_keyboard(),
    )


async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text == "📊 Цены сейчас":
        await now(update, context)
        return

    if text == "📈 Paper статус":
        await paper_status(update, context)
        return

    if text == "📋 Paper результат":
        await paper_result(update, context)
        return

    if text == "⛔ Остановить бота":
        await stop(update, context)
        return

    if text == "🛑 Paper OFF":
        await paper_off(update, context)
        return

    if text == "ℹ️ Помощь":
        await help_menu(update, context)
        return

    if text == "🧪 ETH paper 2200/2180/2220/100":
        enable_paper_trade(2200, 2180, 2220, 100)
        await update.message.reply_text(
            "✅ Быстрый paper trade включён\n"
            "ETHUSDT\n"
            "Вход: 2200\n"
            "Stop-loss: 2180\n"
            "Take-profit: 2220\n"
            "Сумма входа: $100",
            reply_markup=get_main_keyboard(),
        )
        return

    await update.message.reply_text(
        "Не понял кнопку/сообщение. Нажми кнопку из меню 👇",
        reply_markup=get_main_keyboard(),
    )


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("now", now))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("paper_on", paper_on))
    app.add_handler(CommandHandler("paper_off", paper_off))
    app.add_handler(CommandHandler("paper_status", paper_status))
    app.add_handler(CommandHandler("paper_result", paper_result))
    app.add_handler(CommandHandler("help", help_menu))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons))

    app.run_polling()


if __name__ == "__main__":
    main()
