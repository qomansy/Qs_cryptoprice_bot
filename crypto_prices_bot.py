import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SYMBOLS = ["ETHUSDT", "BTCUSDT", "TONUSDT", "APTUSDT", "DOTUSDT"]
ALERT_THRESHOLD = 2.0

last_prices = {}
last_alerts = {}


def get_prices():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    response = requests.get(url, timeout=10).json()
    data = {}

    for coin in response:
        if coin["symbol"] in SYMBOLS:
            data[coin["symbol"]] = {
                "price": float(coin["lastPrice"]),
                "change": float(coin["priceChangePercent"])
            }

    return data


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

    # Удаляем старые задачи для этого чата, чтобы не было дублей
    old_price_jobs = context.job_queue.get_jobs_by_name(f"{chat_id}_prices")
    for job in old_price_jobs:
        job.schedule_removal()

    old_alert_jobs = context.job_queue.get_jobs_by_name(f"{chat_id}_alerts")
    for job in old_alert_jobs:
        job.schedule_removal()

    # Цены каждые 10 минут
    context.job_queue.run_repeating(
        send_prices,
        interval=600,
        first=1,
        chat_id=chat_id,
        name=f"{chat_id}_prices"
    )

    # Проверка импульса каждую минуту
    context.job_queue.run_repeating(
        check_alerts,
        interval=60,
        first=10,
        chat_id=chat_id,
        name=f"{chat_id}_alerts"
    )


async def now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prices = get_prices()
    message = "📊 Актуальные цены:\n\n"

    for symbol, data in prices.items():
        price = data["price"]
        change = data["change"]
        emoji = "🟢" if change >= 0 else "🔴"
        message += f"{symbol}: ${price:.4f} ({emoji} {change:.2f}%)\n"

    await update.message.reply_text(message)


async def send_prices(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    prices = get_prices()

    message = "📊 Актуальные цены:\n\n"

    for symbol, data in prices.items():
        price = data["price"]
        change = data["change"]
        emoji = "🟢" if change >= 0 else "🔴"
        message += f"{symbol}: ${price:.4f} ({emoji} {change:.2f}%)\n"

    await context.bot.send_message(chat_id=chat_id, text=message)


async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    global last_prices, last_alerts

    chat_id = context.job.chat_id
    prices = get_prices()

    for symbol, data in prices.items():
        price = data["price"]

        if symbol in last_prices:
            old_price = last_prices[symbol]
            diff = ((price - old_price) / old_price) * 100

            if abs(diff) >= ALERT_THRESHOLD:
                last_alert = last_alerts.get(symbol, 0)

                # антиспам: не шлём почти одинаковый сигнал повторно
                if abs(diff - last_alert) >= 0.5:
                    alert_text = "🚀 растёт" if diff > 0 else "🔻 падает"

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ {symbol} {alert_text} на {diff:.2f}%"
                    )

                    last_alerts[symbol] = diff

    last_prices = {symbol: data["price"] for symbol, data in prices.items()}


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    price_jobs = context.job_queue.get_jobs_by_name(f"{chat_id}_prices")
    for job in price_jobs:
        job.schedule_removal()

    alert_jobs = context.job_queue.get_jobs_by_name(f"{chat_id}_alerts")
    for job in alert_jobs:
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
