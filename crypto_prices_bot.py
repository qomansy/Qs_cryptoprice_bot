import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SYMBOLS = ["ETHUSDT", "BTCUSDT", "TONUSDT", "APTUSDT", "DOTUSDT"]
ALERT_THRESHOLD = 2.5

last_prices = {}
last_alerts = {}

def get_prices():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    response = requests.get(url).json()
    data = {}
    for coin in response:
        if coin["symbol"] in SYMBOLS:
            data[coin["symbol"]] = {
                "price": float(coin["lastPrice"]),
                "change": float(coin["priceChangePercent"])
            }
    return data

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Готово ✅\n\n"
        "Буду присылать цены каждые 10 минут.\n\n"
        "Команды:\n"
        "/start\n"
        "/now\n"
        "/stop"
    )
    context.job_queue.run_repeating(send_prices, interval=600, first=1, chat_id=update.effective_chat.id)

async def now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_prices(context)

async def send_prices(context: ContextTypes.DEFAULT_TYPE):
    global last_prices
    chat_id = context.job.chat_id

    prices = get_prices()
    message = "📊 Актуальные цены:\n\n"

    for symbol, data in prices.items():
        price = data["price"]
        change = data["change"]

        emoji = "🟢" if change >= 0 else "🔴"

        message += f"{symbol}: ${price:.4f} ({emoji} {change:.2f}%)\n"

        # АЛЕРТ
        if symbol in last_prices:
            old_price = last_prices[symbol]
            diff = ((price - old_price) / old_price) * 100

            if abs(diff) >= ALERT_THRESHOLD:
                alert = "🚀 вырос" if diff > 0 else "🔻 упал"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ {symbol} {alert} на {diff:.2f}%"
                )

    last_prices = {s: d["price"] for s, d in prices.items()}

    await context.bot.send_message(chat_id=chat_id, text=message)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.job_queue.stop()
    await update.message.reply_text("Остановлено ❌")

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("now", now))
    app.add_handler(CommandHandler("stop", stop))

    app.run_polling()

if __name__ == "__main__":
    main()
