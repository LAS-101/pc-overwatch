import asyncio
from telegram_msg import alert

temperature = 49
if temperature > 40:
    asyncio.run(alert(temperature))