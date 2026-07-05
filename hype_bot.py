import os
from telegram.ext import ApplicationBuilder, CommandHandler

async def start(update, context):
    await update.message.reply_text("🔥 HYPE AI BOT PRO funcionando correctamente!")

async def ping(update, context):
    await update.message.reply_text("Pong 🟢")

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    print("TOKEN CARGADO:", token)

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))

    app.run_polling()

if __name__ == "__main__":
    main()
