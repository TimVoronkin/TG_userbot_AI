from pyrogram import Client  # type: ignore
from pyrogram.errors import PeerIdInvalid  # type: ignore
from pyrogram.enums import ChatType  # Импортируем перечисление типов чатов
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from datetime import datetime
import asyncio
import markdown # type: ignore
import bleach # type: ignore
allowed_tags = ['b', 'i', 'u', 'code', 'pre', 'a', 'blockquote']
from google import genai  # Импортируем библиотеку для работы с Geminy

# from config import admin_username, TG_api_id, TG_api_hash, TGbot_token, AI_api_key  # Импортируем конфиденциальные данные
import os
admin_username = os.getenv("admin_username")
TG_api_id = os.getenv("TG_api_id")
TG_api_hash = os.getenv("TG_api_hash")
TGbot_token = os.getenv("TGbot_token")
AI_api_key = os.getenv("AI_api_key")
if not all([admin_username, TG_api_id, TG_api_hash, TGbot_token, AI_api_key]):
    raise ValueError("One or more environment variables are missing!")


# Инициализация клиента Geminy
AI_client = genai.Client(api_key=AI_api_key)
AI_prompt = "Очень коротко выдели главные темы, идеи, люди итд в этой переписке. Напиши пукнтами, без форматирования"

lines_crop = 10 * 3  # Количество строк для отображения в сокращённой версии истории чата. 3 потому что обычно 3 строки на сообщение

delay_TG = 0.5  # Задержка между запросами для предотвращения превышения лимита API

# Инициализация клиента Pyrogram
app = Client("my_userbot", api_id=TG_api_id, api_hash=TG_api_hash)

# Хранилище истории диалогов
dialog_history = {}
my_chat_histoty = "No chat history available."

# команда /start
async def start(update: Update, context: CallbackContext) -> None:
    log_to_console(update)
    await update.message.reply_text('Hello World!')

# команда /ping
async def ping(update: Update, context: CallbackContext) -> None:
    log_to_console(update)
    if update.message.from_user.username == admin_username:

        results = []
        processing_message = await update.message.reply_text("\n".join(results) + "⏳ Running diagnostics...")

        # Check Telegram bot connectivity
        try:
            await context.bot.get_me()
            results.append("✅ Telegram bot is working correctly.")
        except Exception as e:
            results.append(f"❌ Telegram bot error: {e}")

        # Check Pyrogram userbot connectivity
        try:
            await app.get_me()  # Убрано использование async with
            results.append("✅ Pyrogram userbot is working correctly.")
        except Exception as e:
            results.append(f"❌ Pyrogram userbot error: {e}")

        # Check AI client connectivity
        try:
            AI_client.models.list()
            results.append("✅ Geminy AI client is working correctly.")
        except Exception as e:
            results.append(f"❌ Geminy AI client error: {e}")

        # Send diagnostic results
        await processing_message.edit_text(f"Bot is working! 👌<blockquote expandable>{'\n'.join(results)}</blockquote>", parse_mode="HTML")

# команда /list
async def list_chats(update: Update, context: CallbackContext) -> None:
    log_to_console(update)
    if update.message.from_user.username == admin_username:
        try:
            limit = int(context.args[0]) if context.args else 5
            if limit <= 0:
                limit = 5
        except ValueError:
            limit = 5

        try:
            # Получаем последние чаты
            dialogs = []
            async for dialog in app.get_dialogs(limit=limit):  # Убрано использование async with

                display_name = dialog.chat.title if dialog.chat.title else (dialog.chat.first_name or '') + ' ' + (dialog.chat.last_name or '')

                # Определяем иконку в зависимости от типа чата
                if dialog.chat.type == ChatType.PRIVATE:
                    icon = "👤"
                    direct_link = f"tg://user?id={dialog.chat.id}"
                elif dialog.chat.type == ChatType.GROUP:
                    icon = "🫂"
                    direct_link = f"tg://join?invite={dialog.chat.invite_link}" if dialog.chat.invite_link else ""
                elif dialog.chat.type == ChatType.SUPERGROUP:
                    icon = "👥"
                    direct_link = f"tg://join?invite={dialog.chat.invite_link}" if dialog.chat.invite_link else f"t.me/c/{str(dialog.chat.id)[3:]}/-1"
                elif dialog.chat.type == ChatType.CHANNEL:
                    icon = "📢"
                    direct_link = f"tg://resolve?domain={dialog.chat.username}" if dialog.chat.username else f"t.me/c/{str(dialog.chat.id)[3:]}/-1"
                elif dialog.chat.type == ChatType.BOT:
                    icon = "🤖"
                    direct_link = f"t.me/{dialog.chat.username}" if dialog.chat.username else ""
                else:
                    icon = "❓"
                    direct_link = ""

                dialogs.append(f"<a href='{direct_link}'>🆔 </a><code>{dialog.chat.id}</code>\n<a href='https://docs.pyrogram.org/api/enums/ChatType#pyrogram.enums.{dialog.chat.type}'>{icon}</a> {display_name}{f'\n🔗 @{dialog.chat.username}' if dialog.chat.username else ''}\n")

            # Формируем результат
            if dialogs:
                result = f"Recent {limit} chats:\n\n" + "\n".join(dialogs)
            else:
                result = "⚠️ No available chats"
        except Exception as e:
            result = f"⚠️ An error occurred: {e}"
            print(result)

        # Отправляем результат обратно в Telegram-чат
        await update.message.reply_text(result, parse_mode="HTML", disable_web_page_preview=True)

# команда /ai
async def ai_query(update: Update, context: CallbackContext) -> None:
    log_to_console(update)
    user_id = update.message.from_user.id  # Уникальный идентификатор пользователя

    if update.message.from_user.username == admin_username:
        # Проверяем, есть ли запрос после команды
        if context.args:
            query = " ".join(context.args)  # Объединяем аргументы в строку
            processing_message = await update.message.reply_text("⏳ Processing answer...")

            # Инициализируем историю диалога, если её нет
            if user_id not in dialog_history:
                dialog_history[user_id] = []

            # Добавляем запрос пользователя в историю
            dialog_history[user_id].append(f"User: {query}")

            try:
                # Формируем полный контекст для ИИ
                context_for_ai = "\n".join(dialog_history[user_id])

                # Отправляем запрос в Geminy
                ai_response = AI_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=context_for_ai,
                )

                # Проверяем, является ли response строкой или объектом
                response = ai_response if isinstance(ai_response, str) else ai_response.text

                # Добавляем ответ ИИ в историю
                dialog_history[user_id].append(f"AI: {response}")

                # Ограничиваем длину истории до 20 сообщений
                if len(dialog_history[user_id]) > 20:
                    dialog_history[user_id] = dialog_history[user_id][-20:]

                # Отправляем ответ пользователю
                await processing_message.edit_text(
                    f"🤖 AI Response:\n<blockquote>{bleach.clean(markdown.markdown(response), tags=allowed_tags, strip=True)}</blockquote>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception as e:
                await processing_message.edit_text(f"⚠️ An error occurred while processing your query: {e}")
        else:
            await update.message.reply_text("⚠️ Please provide a query after the /ai command.")

# команда /ai_clean
async def ai_clean(update: Update, context: CallbackContext) -> None:
    print("dialog_history:\n"+str(dialog_history))
    user_id = update.message.from_user.id
    if user_id in dialog_history:
        del dialog_history[user_id]
    await update.message.reply_text("🗑️ AI dialogue history cleared.")
    print("🗑️ AI dialogue history cleared.")

# команда /id
async def reply_id(update: Update, context: CallbackContext) -> None:
    log_to_console(update)
    if update.message.from_user.username == admin_username:

        if update.message.reply_to_message:
            replied_message_id = update.message.reply_to_message.message_id
            await update.message.reply_text(f"🆔 The ID of the replied message is: {replied_message_id}")
        else:
            await update.message.reply_text("⚠️ Please reply to a message to use this command.")

# Основные сообщения
async def echo(update: Update, context: CallbackContext) -> None:
    log_to_console(update)
    # Проверка, что сообщение отправлено мной
    if update.message.from_user.username == admin_username:

        # ОТВЕТНОЕ СООБЩЕНИЕ
        if update.message.reply_to_message:
            global my_chat_histoty  # Указываем, что будем использовать глобальную переменную

            AI_prompt_in_message = update.message.text
            print("AI_prompt_in_message:\n"+AI_prompt_in_message)
            result = "🤖 AI Summary:\n"
            processing_message = await update.message.reply_text(result+"⏳ Loading...", parse_mode="HTML") #, reply_to_message_id=update.message.message_id

            # Отправляем запрос в Geminy
            try:
                ai_response = AI_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=f"{AI_prompt_in_message}\n\n{my_chat_histoty}",
                )
                response = ai_response if isinstance(ai_response, str) else ai_response.text
                result += f"<blockquote>{bleach.clean(markdown.markdown(response), tags=allowed_tags, strip=True)}</blockquote>"
            except Exception as e:
                result += f"⚠️ Error: {e}"
            
            # Редактируем сообщение после завершения обработки
            await processing_message.edit_text(result, parse_mode="HTML", disable_web_page_preview=True)

        
        # ЗАПРОС
        else:

            # Отправляем сообщение 1
            processing_message = await update.message.reply_text("⏳ Loading...")

            # Читаем сообщение пользователя
            try:
                lines = update.message.text.split("\n")
                chat_id = lines[0].strip()
                try:
                    msg_count = int(lines[1].strip())
                except (IndexError, ValueError):
                    msg_count = 10  # Если второй строки нет или она некорректна, используем значение по умолчанию
            except (IndexError, ValueError):
                await processing_message.edit_text("⚠️ Error: Invalid input format. Please provide chat_id on the first line and msg_count on the second line.")
                return

            # Основная логика Pyrogram
            try:
                # Получаем информацию о чате
                chat = await app.get_chat(chat_id)  # Убрано использование async with
                result = f"💬 ''{chat.title or chat.first_name}''\n🆔 <code>{chat_id}</code>\n#️⃣ last {msg_count} messages:\n"
                await processing_message.edit_text(result + '\n⏳ Loading...', parse_mode="HTML")

                # Получаем последние сообщения из чата
                messages = []
                async for msg in app.get_chat_history(chat_id, limit=msg_count):  # Асинхронная итерация
                    messages.append(msg)

                    # Формируем ASCII прогресс-бар
                    progress_bar_length = 30  # Длина прогресс-бара
                    progress = int((len(messages) / msg_count) * progress_bar_length)  # 20 символов в прогресс-баре
                    progress_bar = f"{'█' * progress}{'░' * (progress_bar_length - progress)}" 
                    
                    remaining_sec = round((msg_count - len(messages)) * delay_TG, 1)  # Оставшееся время в секундах
                    remaining_time_str = f"{remaining_sec} sec"  # Форматируем оставшееся время
                    if remaining_sec >= 60:
                        remaining_time_str = f"{remaining_sec // 60} min {remaining_sec % 60} sec"
                    

                    # Обновляем сообщение с прогрессом
                    await processing_message.edit_text(
                        result + f"\n⏳ Loading... {len(messages)}/{msg_count} apx {remaining_time_str} left\n<code>{progress_bar}</code> {round(len(messages) / msg_count * 100, 1)}%",
                        parse_mode="HTML"
                    )
                    await asyncio.sleep(delay_TG)  # Задержка между запросами для предотвращения превышения лимита API

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
                        shortened_history = "\n".join(lines[:lines_crop]) + f"\n\n...and {len(lines) - lines_crop * 2} more lines...\n\n\n" + "\n".join(lines[-lines_crop:])
                    else:
                        # Если строк меньше 40, отправляем всё
                        shortened_history = my_chat_histoty

                    if messages:
                        first_message = messages[-1]
                        first_message_link = f"https://t.me/c/{str(chat.id)[3:]}/{first_message.id}" if chat.type in [ChatType.SUPERGROUP, ChatType.CHANNEL] else ""
                        time_since_first_message = datetime.now() - first_message.date
                    
                        # Форматируем время в зависимости от продолжительности
                        if time_since_first_message.days > 0:
                            time_since_str = f"{time_since_first_message.days} days ago"
                        elif time_since_first_message.seconds >= 3600:
                            time_since_str = f"{time_since_first_message.seconds // 3600} hours ago"
                        elif time_since_first_message.seconds >= 60:
                            time_since_str = f"{time_since_first_message.seconds // 60} minutes ago"
                        else:
                            time_since_str = "just now"
                    
                        result += f"🔝 <a href='{first_message_link}'>First message</a> {time_since_str}" if first_message_link else f"🔝 First message was sent {time_since_str}, but link is unavailable"
                        result += f"<blockquote expandable>{shortened_history}</blockquote>"

                        await process_ai_summary(update, processing_message)

                else:
                    result = f"⚠️ The chat with ID {chat_id} is empty or unavailable."
                    print(result)
            except PeerIdInvalid:
                result = f"⚠️ Error: The chat with ID {chat_id} is unavailable."
                print(result)
            except Exception as e:
                result = f"⚠️ An error occurred: {e}"
                print(result)

            await processing_message.edit_text(result, parse_mode="HTML", disable_web_page_preview=True)

# Новая функция для обработки AI Summary
async def process_ai_summary(update: Update, processing_message) -> None:
    result = "🤖 AI Summary:\n"

    # Отправляем запрос в Geminy
    try:
        ai_response = AI_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"{AI_prompt}\n\n{my_chat_histoty}",
        )
        response = ai_response if isinstance(ai_response, str) else ai_response.text
        result += f"<blockquote>{bleach.clean(markdown.markdown(response), tags=allowed_tags, strip=True)}</blockquote>"
    except Exception as e:
        result += f"⚠️ Error: {e}"
    
    # Редактируем сообщение после завершения обработки
    await processing_message.edit_text(result, parse_mode="HTML", disable_web_page_preview=True)

# Логирование всех сообщений
async def log_message(update: Update, context: CallbackContext) -> None:
    log_to_console(update)

def log_to_console(update: Update) -> None:
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    username = update.message.from_user.username if update.message.from_user else "(Unknown user)"
    message_text = update.message.text if update.message.text else "(non-text message)"

    # Выводим в консоль
    print(f"\n🗨️ [{current_time} @{username}]\n{message_text}")
    if update.message.from_user.username != admin_username:
        print(f"⚠️ Message from an unknown user. Ignored.")


async def send_startup_message(application: Application):
    async with application:
        await application.bot.send_message(chat_id=admin_username, text="🚀 Script updated and started!")

# Основная функция для запуска Telegram-бота
def main() -> None:
    print("🚀 Script started!")
    application = Application.builder().token(TGbot_token).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("list", list_chats))
    application.add_handler(CommandHandler("ai", ai_query))
    application.add_handler(CommandHandler("ai_clean", ai_clean))
    application.add_handler(CommandHandler("id", reply_id))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.add_handler(MessageHandler(filters.ALL, log_message))
    
    ''' Для телеграм бота команды:
    list - <n> show recent chats (default: 5 chats)
    ping - check the bot's connectivity
    start - test
    id - test. get the ID of the replied message
    ai -  test. Ask AI Gemini directly
    ai_clean -  test. Clear the AI dialogue history
    '''


    # Запускаем клиента Pyrogram
    app.start()  # Открываем соединение с Pyrogram

    try:
        # Запускаем бота
        application.run_polling()
        # Отправляем сообщение о запуске скрипта
        asyncio.run(send_startup_message(application))


    finally:
        # Закрываем клиента Pyrogram при завершении работы
        app.stop()

if __name__ == '__main__':
    main()