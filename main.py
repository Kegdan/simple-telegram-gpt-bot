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

def relay_errors(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            await update.message.reply_text(f"An error occurred. e: {e}")
    return wrapper

CONFIGURATION = load_configuration()
VISION_MODELS = CONFIGURATION.get('vision_models', [])
VALID_MODELS = CONFIGURATION.get('VALID_MODELS', {})

@relay_errors
@get_session_id
@initialize_session_data
@check_api_key
async def handle_message(update: Update, context: CallbackContext, session_id):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    session_data = SESSION_DATA[session_id]
    if update.message.photo and session_data['model'] in VISION_MODELS:
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_url = photo_file.file_path
        caption = update.message.caption or "Describe this image."
        session_data['chat_history'].append({
            "role": "user",
            "content": [
                {"type": "text", "text": caption},
                {"type": "image_url", "image_url": photo_url}
            ]
        })
    else:
        user_message = update.message.text
        session_data['chat_history'].append({
            "role": "user",
            "content": user_message
        })
    messages_for_api = [message for message in session_data['chat_history']]
    response = await response_from_openai(
        session_data['model'], 
        messages_for_api, 
        session_data['temperature'], 
        session_data['max_tokens']
    )
    session_data['chat_history'].append({
        'role': 'assistant',
        'content': response
    })
    await update.message.reply_markdown(response)

async def response_from_openai(model, messages, temperature, max_tokens):
    params = {'model': model, 'messages': messages, 'temperature': temperature}
    if model == "gpt-4-vision-preview": # legacy parameter
        max_tokens = 4096
    if max_tokens is not None: 
        params['max_tokens'] = max_tokens
    return openai.chat.completions.create(**params).choices[0].message.content

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
                model="gpt-3.5-turbo",
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

def update_session_preference(session_id, preference, value):
    if session_id in SESSION_DATA:
        SESSION_DATA[session_id][preference] = value
        logging.debug(f"Updated {preference} for session_id={session_id}: {value}")
    else:
        logging.warning(f"Tried to update preference for non-existing session_id={session_id}")

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
        ],
        1: [MessageHandler(filters.ALL & (~filters.COMMAND), handle_message)]
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