import asyncio
import sys
from telegram import Bot
from config import token_key, chat_id

async def alert(temperature: str):
    bot = Bot(token=token_key)
    message = f"⚠️ CPU Temperature Alert!\nCurrent temp: {temperature}°C"
    await bot.send_message(chat_id=chat_id, text=message)
