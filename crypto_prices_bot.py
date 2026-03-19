import os
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

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
    "in_position": False,
    "entry_price": None,
    "last_result": None
}


def get_prices():
    url = "https://api.binance.com/api/v3/ticker/24hr"
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    await update.message.reply_text(
        "Готово ✅\n\n"
        "Я буду:\n"
        "• присылать цены каждые 10 минут\n"
        "• отдельно писать, если монета растёт или падает на 2%+\n"
        "• следить за paper trade по ETHUSDT\n\n"
        "Команды:\n"
        "/start\n"
        "/now\n"
        "/stop\n"
        "/paper_on 2200 2180 2220\n"
        "/paper_off\n"
        "/paper_status\n"
        "/paper_result"
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
        await update.message.reply_text(message)
    except Exception as e:
        logger.exception("Ошибка в /now")
        await update.message.reply_text(f"Ошибка в /now: {e}")


async def send_prices(context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = context.job.chat_id
        prices = get_prices()
        message = build_prices_message(prices)
        await context.bot.send_message(chat_id=chat_id, text=message)
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
                            text=f"⚠️ {symbol} {alert_text} на {diff:.2f}%"
                        )

                        last_alerts[symbol] = diff

        last_prices = {symbol: data["price"] for symbol, data in prices.items()}
    except Exception:
        logger.exception("Ошибка в check_alerts")


async def paper_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global paper_trade

    try:
        entry = float(context.args[0])
        stop_loss = float(context.args[1])
        take_profit = float(context.args[2])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Используй так:\n/paper_on 2200 2180 2220"
        )
        return

    paper_trade["enabled"] = True
    paper_trade["entry"] = entry
    paper_trade["stop_loss"] = stop_loss
    paper_trade["take_profit"] = take_profit
    paper_trade["in_position"] = False
    paper_trade["entry_price"] = None
    paper_trade["last_result"] = None

    await update.message.reply_text(
        f"✅ Paper mode включён\n"
        f"Symbol: ETHUSDT\n"
        f"Вход: {entry}\n"
        f"Stop-loss: {stop_loss}\n"
        f"Take-profit: {take_profit}"
    )


async def paper_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global paper_trade

    paper_trade["enabled"] = False
    paper_trade["in_position"] = False
    paper_trade["entry_price"] = None

    await update.message.reply_text("🛑 Paper mode выключен")


async def paper_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = (
        f"Paper mode: {'ON' if paper_trade['enabled'] else 'OFF'}\n"
        f"Symbol: {paper_trade['symbol']}\n"
        f"Entry: {paper_trade['entry']}\n"
        f"Stop-loss: {paper_trade['stop_loss']}\n"
        f"Take-profit: {paper_trade['take_profit']}\n"
        f"In position: {paper_trade['in_position']}\n"
        f"Entry price: {paper_trade['entry_price']}"
    )
    await update.message.reply_text(status)


async def paper_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = paper_trade["last_result"]
    if result is None:
        await update.message.reply_text("Пока нет закрытых paper-сделок")
    else:
        await update.message.reply_text(result)


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
                paper_trade["in_position"] = True
                paper_trade["entry_price"] = current_price

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🟢 Paper BUY ETHUSDT по {current_price:.2f}"
                )
            return

        if current_price <= paper_trade["stop_loss"]:
            pnl = current_price - paper_trade["entry_price"]
            pnl_pct = (pnl / paper_trade["entry_price"]) * 100

            text = (
                f"🔴 Paper SELL ETHUSDT по stop-loss: {current_price:.2f}\n"
                f"Результат: {pnl:.2f}$ ({pnl_pct:.2f}%)"
            )

            paper_trade["last_result"] = text
            paper_trade["in_position"] = False
            paper_trade["entry_price"] = None

            await context.bot.send_message(chat_id=chat_id, text=text)
            return

        if current_price >= paper_trade["take_profit"]:
            pnl = current_price - paper_trade["entry_price"]
            pnl_pct = (pnl / paper_trade["entry_price"]) * 100

            text = (
                f"🚀 Paper SELL ETHUSDT по take-profit: {current_price:.2f}\n"
                f"Результат: {pnl:.2f}$ ({pnl_pct:.2f}%)"
            )

            paper_trade["last_result"] = text
            paper_trade["in_position"] = False
            paper_trade["entry_price"] = None

            await context.bot.send_message(chat_id=chat_id, text=text)
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

    await update.message.reply_text("Остановлено ❌")


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("now", now))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("paper_on", paper_on))
    app.add_handler(CommandHandler("paper_off", paper_off))
    app.add_handler(CommandHandler("paper_status", paper_status))
    app.add_handler(CommandHandler("paper_result", paper_result))

    app.run_polling()


if __name__ == "__main__":
    main()
