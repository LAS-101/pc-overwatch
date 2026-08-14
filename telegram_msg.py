import asyncio
import sys
from telegram import Bot
from config import token_key, chat_id

async def alert(temperature: str):
    bot = Bot(token=token_key)
    message = f"⚠️ CPU Temperature Alert!\nCurrent temp: {temperature}°C"
    await bot.send_message(chat_id=chat_id, text=message)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 telegram_msg.py <temperature>")
        sys.exit(1)
    asyncio.run(alert(sys.argv[1]))