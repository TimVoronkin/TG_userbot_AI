from pyrogram import Client  # type: ignore
from pyrogram.errors import PeerIdInvalid  # type: ignore
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from datetime import datetime
import asyncio
import markdown # type: ignore
import bleach # type: ignore
allowed_tags = ['b', 'i', 'u', 'code', 'pre', 'a', 'blockquote']
from google import genai  # Импортируем библиотеку для работы с Geminy

from config import admin_username, TG_api_id, TG_api_hash, TGbot_token, AI_api_key  # Импортируем конфиденциальные данные

# Инициализация клиента Geminy
AI_client = genai.Client(api_key=AI_api_key)
AI_prompt = "Сократи переписку до сути, расскажи темы, ключевые идеи, интересные повороты, стиль общения участников. Без воды, дружелюбно и понятно."

lines_crop = 10 * 3  # Количество строк для отображения в сокращённой версии истории чата. 3 потому что обычно 3 строки на сообщение

# Функция для обработки команды /start
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text('Hello World!')

# Функция для обработки команды /list
async def list_chats(update: Update, context: CallbackContext) -> None:
    if update.message.from_user.username == admin_username:
        # Получаем аргументы команды
        try:
            limit = int(context.args[0]) if context.args else 5  # Устанавливаем лимит из аргумента или по умолчанию 5
            if limit <= 0:
                limit = 5  # Если указано некорректное число, используем стандартное значение
        except ValueError:
            limit = 5  # Если аргумент не число, используем стандартное значение

        # Создаем клиент Pyrogram
        app = Client("my_userbot", api_id=TG_api_id, api_hash=TG_api_hash)

        # Основная логика Pyrogram
        async with app:  # Используем асинхронный контекстный менеджер
            try:
                # Получаем последние 5 чатов
                dialogs = []
                async for dialog in app.get_dialogs(limit=limit):
                    dialogs.append(f"🆔 <code>{dialog.chat.id}</code>\n👤 {dialog.chat.first_name} {dialog.chat.last_name}\n👥 {dialog.chat.title}\n🔗 @{dialog.chat.username}\n🧬{dialog.chat.type}\n")

                # Формируем результат
                if dialogs:
                    result = f"Recent {limit} chats:\n\n" + "\n".join(dialogs)
                else:
                    result = "No available chats"
            except Exception as e:
                result = f"An error occurred: {e}"
                print(result)

        # Отправляем результат обратно в Telegram-чат
        await update.message.reply_text(result, parse_mode="HTML")
    else:
        # Игнорировать сообщение, если имя пользователя не совпадает
        print("Message from an unknown user. Ignored.")

# Функция для обработки текстовых сообщений
async def echo(update: Update, context: CallbackContext) -> None:
    # Проверка, что сообщение отправлено мной
    if update.message.from_user.username == admin_username:
        processing_message = await update.message.reply_text("⏳ Loading...")

        # Получаем текущее время
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{current_time}] Message from {update.message.from_user.username}: {update.message.text}")

        # Разделяем сообщение на строки
        try:
            lines = update.message.text.split("\n")
            chat_id = lines[0].strip()  # Первый рядок — chat_id
            try:
                msg_count = int(lines[1].strip())  # Второй рядок — msg_count
            except (IndexError, ValueError):
                msg_count = 10  # Если второй строки нет или она некорректна, используем значение по умолчанию
        except (IndexError, ValueError):
            await processing_message.edit_text("Error: Invalid input format. Please provide chat_id on the first line and msg_count on the second line.")
            return
        
        # Создаем клиент Pyrogram
        app = Client("my_userbot", api_id=TG_api_id, api_hash=TG_api_hash)

        # Основная логика Pyrogram
        async with app:  # Используем асинхронный контекстный менеджер
            try:
                # Получаем информацию о чате
                chat = await app.get_chat(chat_id)
                result = f"💬 ''{chat.title or chat.first_name}''\n🆔 <code>{chat_id}</code>\n#️⃣ last {msg_count} messages:\n"
                await processing_message.edit_text(result+'\n⏳ Loading...', parse_mode="HTML")

                # Получаем последние сообщения из чата
                messages = []
                async for msg in app.get_chat_history(chat_id, limit=msg_count):  # Асинхронная итерация
                    messages.append(msg)
                    await asyncio.sleep(1)  # Задержка между запросами для предотвращения превышения лимита API

                if messages:
                    my_chat_histoty = ""  # Переменная для хранения истории чата
                    for msg in reversed(messages):  # Переворачиваем список для вывода в порядке от старых к новым
                        sender_name = msg.from_user.first_name if msg.from_user else "Unknown user"
                        message_time = msg.date.strftime('%Y-%m-%d %H:%M') if msg.date else "Unknown time"

                        # Определяем тип сообщения
                        if msg.text:
                            content = msg.text
                        elif msg.photo:
                            content = f"(image) {msg.caption or ''}"
                        elif msg.sticker:
                            content = f"({msg.sticker.emoji or ''} sticker)"
                        elif msg.video:
                            content = f"(video) {msg.caption or ''}"
                        elif msg.voice:
                            content = f"(voice message, {msg.voice.duration} sec long) {msg.caption or ''}"
                        elif msg.video_note:
                            content = f"(video message, {msg.video_note.duration} sec long)"
                        elif msg.document:
                            content = f"(document) {msg.document.file_name or ''}"
                        elif msg.animation:
                            content = "(GIF animation)"
                        elif msg.location:
                            content = f"(location: {msg.location.latitude}, {msg.location.longitude} )"
                        elif msg.poll:
                            options = ", ".join([f'"{option.text}"' for option in msg.poll.options])  # Извлекаем текст из каждого варианта
                            content = f"(poll ''{msg.poll.question}'', with options: {options})"
                        elif msg.new_chat_members:
                            content = f"({', '.join([member.first_name for member in msg.new_chat_members])} joined the chat)"
                        elif msg.left_chat_member:
                            content = f"({msg.left_chat_member.first_name} left the chat)"    
                        else:
                            content = "(unknown message type)"

                        # Формируем строку для текущего сообщения
                        my_chat_histoty += f"[{sender_name} at {message_time}]:\n{content}\n\n"

                    # Формируем сокращённую версию истории чата
                    lines = my_chat_histoty.splitlines()
                    if len(lines) > lines_crop * 2:
                        # Берём первые 20 строк, добавляем информацию о количестве строк, и последние 20 строк
                        shortened_history = "\n".join(lines[:lines_crop]) + f"\n\n...and {len(lines) - lines_crop*2} more lines...\n\n\n" + "\n".join(lines[-lines_crop:])
                    else:
                        # Если строк меньше 40, отправляем всё
                        shortened_history = my_chat_histoty

                    result += f"<blockquote expandable>{shortened_history}</blockquote>"
                    result += "\n🤖 AI Summary:\n"

                    await processing_message.edit_text(result+'\n⏳ Loading...', parse_mode="HTML")

                    # Отправляем историю чата в ИИ
                    try:
                        ai_response = AI_client.models.generate_content(
                            model="gemini-2.0-flash",
                            contents=f"{AI_prompt}\n\n{my_chat_histoty}",
                        )
                        result += f"<blockquote>{bleach.clean(markdown.markdown(ai_response.text), tags=allowed_tags, strip=True)}</blockquote>"
                    except Exception as e:
                        result += f"Error: {e}"

                else:
                    result = f"The chat with ID {chat_id} is empty or unavailable."
                    print(result)
            except PeerIdInvalid:
                result = f"Error: The chat with ID {chat_id} is unavailable."
                print(result)
            except Exception as e:
                result = f"An error occurred: {e}"
                print(result)

        # Редактируем сообщение после завершения обработки
        await processing_message.edit_text(result, parse_mode="HTML", disable_web_page_preview=True)

    else:
        # Игнорировать сообщение, если имя пользователя не совпадает
        print("Message from an unknown user. Ignored.")

# Функция для обработки команды /ai
async def ai_query(update: Update, context: CallbackContext) -> None:
    if update.message.from_user.username == admin_username:
        # Проверяем, есть ли запрос после команды
        if context.args:
            query = " ".join(context.args)  # Объединяем аргументы в строку
            processing_message = await update.message.reply_text("Processing your AI query...")

            try:
                # Отправляем запрос в Geminy
                response = AI_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=query,
                )

                # Получаем текст ответа
                ai_response = response.text
                await processing_message.edit_text(f"🤖 AI Response:\n{ai_response}")
            except Exception as e:
                # Обрабатываем ошибки
                await processing_message.edit_text(f"An error occurred while processing your query: {e}")
        else:
            await update.message.reply_text("Please provide a query after the /ai command.")
    else:
        print("Message from an unknown user. Ignored.")

# Основная функция для запуска Telegram-бота
def main() -> None:
    print("🚀 Script started!")
    application = Application.builder().token(TGbot_token).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_chats))
    application.add_handler(CommandHandler("ai", ai_query))  # Добавляем обработчик для команды /ai
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()