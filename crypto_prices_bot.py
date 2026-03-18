import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, List

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
UPDATE_EVERY_SECONDS = int(os.getenv('UPDATE_EVERY_SECONDS', '600'))
VS_CURRENCY = os.getenv('VS_CURRENCY', 'usd').lower()
STATE_FILE = Path('bot_state.json')

COINS: Dict[str, str] = {
    'BTC/USDT': 'bitcoin',
    'ETH/USDT': 'ethereum',
    'TON/USDT': 'the-open-network',
    'APT/USDT': 'aptos',
    'DOT/USDT': 'polkadot',
}
PAIR_ORDER: List[str] = ['ETH/USDT', 'BTC/USDT', 'TON/USDT', 'APT/USDT', 'DOT/USDT']


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except Exception:
            logger.exception('Could not read state file')
    return {'chat_ids': []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def add_chat_id(chat_id: int) -> None:
    state = load_state()
    chat_ids = set(state.get('chat_ids', []))
    chat_ids.add(chat_id)
    state['chat_ids'] = sorted(chat_ids)
    save_state(state)


def remove_chat_id(chat_id: int) -> None:
    state = load_state()
    chat_ids = set(state.get('chat_ids', []))
    chat_ids.discard(chat_id)
    state['chat_ids'] = sorted(chat_ids)
    save_state(state)


def get_chat_ids() -> List[int]:
    return load_state().get('chat_ids', [])


def fetch_prices() -> str:
    ids = ','.join(COINS[pair] for pair in PAIR_ORDER)
    url = 'https://api.coingecko.com/api/v3/simple/price'
    params = {
        'ids': ids,
        'vs_currencies': VS_CURRENCY,
        'include_24hr_change': 'true',
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    lines = ['📊 Актуальные цены:', '']
    for pair in PAIR_ORDER:
        coin_id = COINS[pair]
        price = data.get(coin_id, {}).get(VS_CURRENCY)
        change = data.get(coin_id, {}).get(f'{VS_CURRENCY}_24h_change')
        if price is None:
            lines.append(f'{pair}: нет данных')
            continue

        if isinstance(price, (int, float)):
            if price >= 1000:
                price_str = f'{price:,.2f}'
            elif price >= 1:
                price_str = f'{price:,.4f}'
            else:
                price_str = f'{price:,.6f}'
        else:
            price_str = str(price)

        if isinstance(change, (int, float)):
            sign = '🟢' if change >= 0 else '🔴'
            change_str = f' ({sign} {change:+.2f}% за 24ч)'
        else:
            change_str = ''

        lines.append(f'{pair}: ${price_str}{change_str}')

    return '\n'.join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    add_chat_id(chat_id)
    await update.message.reply_text(
        'Готово ✅\n\nЯ добавил этот чат в рассылку.\nТеперь буду присылать цены каждые 10 минут.\n\nКоманды:\n/start — включить\n/now — прислать цены сейчас\n/stop — выключить'
    )


async def now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        text = fetch_prices()
        await update.message.reply_text(text)
    except Exception as e:
        logger.exception('Price fetch failed')
        await update.message.reply_text(f'Не получилось получить цены: {e}')


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    remove_chat_id(chat_id)
    await update.message.reply_text('Ок, остановил рассылку для этого чата.')


async def broadcast_prices(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_ids = get_chat_ids()
    if not chat_ids:
        logger.info('No subscribers yet')
        return

    try:
        text = fetch_prices()
    except Exception:
        logger.exception('Broadcast fetch failed')
        return

    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
            await asyncio.sleep(0.2)
        except Exception:
            logger.exception('Failed to send message to chat_id=%s', chat_id)


async def post_init(app: Application) -> None:
    app.job_queue.run_repeating(
        broadcast_prices,
        interval=UPDATE_EVERY_SECONDS,
        first=30,
        name='crypto-price-broadcast',
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError('Set TELEGRAM_BOT_TOKEN environment variable')

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('now', now))
    app.add_handler(CommandHandler('stop', stop))
    logger.info('Bot started')
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
