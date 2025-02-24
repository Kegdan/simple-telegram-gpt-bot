import argparse, json, logging, os, openai, requests
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackContext, filters

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') or exit("🚨Error: TELEGRAM_TOKEN is not set.")
openai.api_key = os.getenv('OPENAI_API_KEY') or None
SESSION_DATA = {}

def load_configuration():
    with open('configuration.json', 'r') as file:
        return json.load(file)

def get_session_id(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        session_id = str(update.effective_chat.id if update.effective_chat.type in ['group', 'supergroup'] else update.effective_user.id)
        return await func(update, context, session_id, *args, **kwargs)
    return wrapper

def initialize_session_data(func):
    async def wrapper(update: Update, context: CallbackContext, session_id, *args, **kwargs):
        if session_id not in SESSION_DATA:
            logging.debug(f"Initializing session data for session_id={session_id}")
            SESSION_DATA[session_id] = load_configuration()['default_session_values']
        else:
            logging.debug(f"Session data already exists for session_id={session_id}")
        logging.debug(f"SESSION_DATA[{session_id}]: {SESSION_DATA[session_id]}")
        return await func(update, context, session_id, *args, **kwargs)
    return wrapper

def check_api_key(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if not openai.api_key:
            await update.message.reply_text("⚠️Please configure your OpenAI API Key: /set openai_api_key THE_API_KEY")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def command_start(update: Update, context: CallbackContext):
    await update.message.reply_text("ℹ️Welcome! Go ahead and say something to start the conversation. More features can be found in this command: /help")

@get_session_id
async def command_check(update: Update, context: CallbackContext, session_id):
    # Получаем сообщение, на которое ответил пользователь
    if update.message.reply_to_message:
        original_message = update.message.reply_to_message.text

        # Проверяем, содержит ли сообщение ссылку
        if 'http' in update.message.text:
            url = update.message.text.strip()

            # Отправляем запрос ко мне через API
            response = openai.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "user",
                        "content": f"""
                            Проверь что утверждение "{original_message}" следует из содержимного по ссылке {url}. Обоснуй ответ.

                            Формат ответа:

                            ("Подтверждаю" или "Не подтверждаю"
                            "Обосновнание:"
                            список фактов)""",
                    },
                ],
            )

            await update.message.reply_text(response.choices[0].message.content)
        else:
            await update.message.reply_text('Пожалуйста, отправьте ссылку в ответ на сообщение.')
    else:
        await update.message.reply_text('Вы должны ответить на сообщение с ссылкой.')

async def command_help(update: Update, context: CallbackContext):
    commands = [
        ("/check", "Check proof"),
    ]
    help_text = "<b>📚 Usage Commands:</b>\n"
    for command, description in commands:
        help_text += f"<code>{command}</code> - {description}\n"
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

def register_handlers(application):
    application.add_handlers(handlers={ 
        -1: [
            CommandHandler('start', command_start),
            CommandHandler('check', command_check),
            CommandHandler('help', command_help)
        ]
    })

def railway_dns_workaround():
    from time import sleep
    sleep(1.3)
    for _ in range(3):
        if requests.get("https://api.telegram.org", timeout=3).status_code == 200:
            print("The api.telegram.org is reachable.")
            return
        print(f'The api.telegram.org is not reachable. Retrying...({_})')
    print("Failed to reach api.telegram.org after 3 attempts.")

def main():
    parser = argparse.ArgumentParser(description="Run the Telegram bot.")
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.disable(logging.WARNING)
    railway_dns_workaround()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    register_handlers(application)
    try:
        print("The Telegram Bot will now be running in long polling mode.")
        application.run_polling()
    except Exception as e:
        logging.error(f"An error occurred: {e}")

if __name__ == '__main__':
    main()