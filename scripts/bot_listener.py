import logging
import subprocess
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from config import token_key, chat_id

logging.basicConfig(level=logging.INFO)

READ_TEMP_SCRIPT = "/home/elyes/projects/cpu-temperature/read_temp"

def read_cpu_temp() -> int:
    try:
        result = subprocess.run(
            [READ_TEMP_SCRIPT], capture_output=True, text=True, timeout=5
        )
        return int(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return -1

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != str(chat_id):
        return

    temp = read_cpu_temp()
    if temp == -1:
        await update.message.reply_text("🟢 PC is ON, but couldn't read CPU temp")
    else:
        await update.message.reply_text(f"🟢 PC is ON\n🌡️ CPU temp: {temp}°C")

def main():
    app = ApplicationBuilder().token(token_key).build()
    app.add_handler(CommandHandler("status", status))
    app.run_polling()

if __name__ == "__main__":
    main()