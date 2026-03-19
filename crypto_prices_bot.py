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
        "• отдельно писать, если монета растёт или падает на 2%+\n\n"
        "Команды:\n"
        "/start\n"
        "/now\n"
        "/stop"
    )

    for job in context.job_queue.get_jobs_by_name(f"{chat_id}_prices"):
        job.schedule_removal()

    for job in context.job_queue.get_jobs_by_name(f"{chat_id}_alerts"):
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


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    for job in context.job_queue.get_jobs_by_name(f"{chat_id}_prices"):
        job.schedule_removal()

    for job in context.job_queue.get_jobs_by_name(f"{chat_id}_alerts"):
        job.schedule_removal()

    await update.message.reply_text("Остановлено ❌")


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("now", now))
    app.add_handler(CommandHandler("stop", stop))

    app.run_polling()


if __name__ == "__main__":
    main()
