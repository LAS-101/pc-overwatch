import asyncio
import sys
from telegram import Bot
from config import token_key, chat_id,PC_NAME

async def send(message: str):
    bot = Bot(token=token_key)
    await bot.send_message(chat_id=chat_id, text=message)

def build_message(event: str) -> str:
    if event == "boot":
        return f"🟢 {PC_NAME} is now ON"
    elif event == "shutdown":
        return f"🔴 {PC_NAME} is shutting down"
    return event  # fallback: treat argument as a raw custom message

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 pc_notify.py <boot|shutdown>")
        sys.exit(1)
    asyncio.run(send(build_message(sys.argv[1])))