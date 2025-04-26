from pyrogram import Client  # type: ignore
from pyrogram.errors import PeerIdInvalid  # type: ignore
from pyrogram.enums import ChatType  # Импортируем перечисление типов чатов
from pyrogram.raw.functions.messages import GetDialogs
from pyrogram.raw.types import InputPeerEmpty
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from datetime import datetime
import json
import asyncio
import os
import markdown # type: ignore
import bleach # type: ignore
allowed_tags = ['b', 'i', 'u', 'code', 'pre', 'a', 'blockquote']
from google import genai

# ДЛЯ ЛОКАЛЬНОГО ЗАПУСКА
from config import admin_id, TG_api_id, TG_api_hash, TGbot_token, AI_api_key

# ДЛЯ ЗАПУСКА В HEROKU
# import os
# admin_id = int(os.getenv("admin_id"))
# TG_api_id = os.getenv("TG_api_id")
# TG_api_hash = os.getenv("TG_api_hash")
# TGbot_token = os.getenv("TGbot_token")
# AI_api_key = os.getenv("AI_api_key")

if not all([admin_id, TG_api_id, TG_api_hash, TGbot_token, AI_api_key]):
    raise ValueError("One or more configuration variables are missing!")

AI_default_prompt = "Очень коротко выдели главные темы, идеи, люди итд в этой переписке. Напиши пукнтами, без форматирования"
lines_crop = 10  # Количество строк для отображения в сокращённой версии истории чата. 3 потому что обычно 3 строки на сообщение
delay_TG = 0.5  # Задержка между запросами для предотвращения превышения лимита API Telegram

# Инициализация клиентов
AI_client = genai.Client(api_key=AI_api_key)
userbotTG_client = Client("my_userbot", api_id=TG_api_id, api_hash=TG_api_hash)
botTG_client = Application.builder().token(TGbot_token).build()

# Хранилище истории диалогов
dialog_history = {}
my_chat_histoty = "No chat history available."

# команда /start
async def start(update: Update, context: CallbackContext) -> None:
    log_any_user(update)
    await update.message.reply_text('Hello World!')

# команда /ping
async def ping(update: Update, context: CallbackContext) -> None:
    log_any_user(update)
    print("update.message.from_user.id: "+str(update.message.from_user.id))
    print("admin_id: "+str(admin_id))
    # Проверяем, что команда отправлена администратором
    if update.message.from_user.id == admin_id:

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
            await userbotTG_client.get_me()  # Убрано использование async with
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
        diagnostic_results = "\n".join(results)
        await processing_message.edit_text(
            "Bot is working! 👌<blockquote expandable>" + diagnostic_results + "</blockquote>",
            parse_mode="HTML"
        )

# Получаем иконку и ссылку чата
def get_chat_icon_and_link(chat):
    # Определяем иконку в зависимости от типа чата
    if chat.type == ChatType.PRIVATE:
        icon = "👤"
        if chat.username: # Если есть юзернейм
            direct_link = f"https://t.me/{chat.username}"
        else:
            direct_link = f"tg://user?id={chat.id}"
    elif chat.type == ChatType.GROUP:
        icon = "🫂"
        direct_link = f"https://t.me/joinchat/{chat.invite_link}" if chat.invite_link else ""
    elif chat.type == ChatType.SUPERGROUP:
        icon = "👥"
        if chat.username: # Если есть юзернейм
            direct_link = f"https://t.me/{chat.username}"
        else:
            direct_link = f"https://t.me/c/{str(chat.id)[3:]}/-1"
    elif chat.type == ChatType.CHANNEL:
        icon = "📢"
        if chat.username: # Если есть юзернейм
            direct_link = f"https://t.me/{chat.username}"
        else:
            direct_link = f"https://t.me/c/{str(chat.id)[3:]}/-1"
    elif chat.type == ChatType.BOT:
        icon = "🤖"
        direct_link = f"https://t.me/{chat.username}" if chat.username else ""
    else:
        icon = "❓"
        direct_link = ""
    return icon, direct_link

# команда /list
async def list_chats(update: Update, context: CallbackContext) -> None:
    log_any_user(update)
    if update.message.from_user.id == admin_id:
        try:
            limit = int(context.args[0]) if len(context.args) > 0 else 5
            if limit <= 0:
                limit = 5
        except ValueError:
            limit = 5

        # Определяем фильтры
        filter_mapping = {
            "p": "private",
            "private": "private",
            "приватные": "private",
            "личные": "private",
            "личка": "private",
            "лс": "private",
            "особисті": "private",
            "директ": "private",
            "dm": "private",
            "дм": "private",

            "g": "group",
            "group": "group",
            "groups": "group",
            "chat": "group",
            "чат": "group",
            "чаты": "group",
            "група": "group",
            "групи": "group",
            "группы": "group",

            "c": "channel",
            "channel": "channel",
            "channels": "channel",
            "канал": "channel",
            "каналы": "channel",
            "каналчики": "channel",
            "тгк": "channel"
            }
        filter_type = context.args[1].lower() if len(context.args) > 1 else None
        filter_type = filter_mapping.get(filter_type, None)  # Преобразуем значение через словарь
        
        try:
            dialogs = []
            fetched_count = 0  # Счётчик полученных диалогов
            async for dialog in userbotTG_client.get_dialogs():
                # Фильтр по типу чата
                if filter_type:
                    if filter_type == "private" and dialog.chat.type != ChatType.PRIVATE:
                        continue
                    elif filter_type == "group" and dialog.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
                        continue
                    elif filter_type == "channel" and dialog.chat.type != ChatType.CHANNEL:
                        continue

                # Добавляем подходящий диалог в список
                display_name = dialog.chat.title if dialog.chat.title else (dialog.chat.first_name or '') + ' ' + (dialog.chat.last_name or '')
                icon, direct_link = get_chat_icon_and_link(dialog.chat)
                
                dialogs.append(
                    "<a href='{direct_link}'>🆔 </a><code>{chat_id}</code>\n"
                    "<a href='https://docs.pyrogram.org/api/enums/ChatType#pyrogram.enums.{chat_type}'>{icon}</a> {display_name}"
                    "{username_link}\n".format(
                        direct_link=direct_link,
                        chat_id=dialog.chat.id,
                        chat_type=dialog.chat.type,
                        icon=icon,
                        display_name=display_name,
                        username_link=f"\n🔗 @{dialog.chat.username}" if dialog.chat.username else ""
                    )
                )

                fetched_count += 1

                # Прерываем, если достигли лимита
                if len(dialogs) >= limit:
                    break

            # Формируем результат
            if dialogs:
                result = f"Recent {limit} {filter_type + ' 'if filter_type else ''}chats:\n\n" + "\n".join(dialogs)
            else:
                result = "⚠️ No available chats"
        except Exception as e:
            result = f"⚠️ An error occurred: {e}"
            print(result)

        # Отправляем результат обратно в Telegram-чат
        await update.message.reply_text(result, parse_mode="HTML", disable_web_page_preview=True)

# команда /ai
async def ai_query(update: Update, context: CallbackContext) -> None:
    log_any_user(update)
    user_id = update.message.from_user.id  # Уникальный идентификатор пользователя

    if update.message.from_user.id == admin_id:
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

# команда /json
async def send_json(update: Update, context: CallbackContext) -> None:
    log_any_user(update)
    test_json = {
        "name": "Test User",
        "age": 25,
        "email": "testuser@example.com",
        "is_admin": False,
        "preferences": {
            "theme": "dark",
            "notifications": True
        }
    }
    # Сохраняем JSON в файл
    file_path = "test_data.json"
    with open(file_path, "w", encoding="utf-8") as file:
        import json
        json.dump(test_json, file, indent=4, ensure_ascii=False)

    # Отправляем файл пользователю
    await context.bot.send_document(
        chat_id=update.message.chat_id,
        document=open(file_path, "rb"),
        filename="test_data.json",
        caption="📄 Here is your test JSON file."
    )

# команда /id
async def reply_id(update: Update, context: CallbackContext) -> None:
    log_any_user(update)
    if update.message.from_user.id == admin_id:

        if update.message.reply_to_message:
            replied_message_id = update.message.reply_to_message.message_id
            await update.message.reply_text(f"🆔 The ID of the replied message is: {replied_message_id}")
        else:
            await update.message.reply_text("⚠️ Please reply to a message to use this command.")

# Основные сообщения
async def echo(update: Update, context: CallbackContext) -> None:
    log_any_user(update)
    # Проверка, что сообщение отправлено мной
    if update.message.from_user.id == admin_id:
        global my_chat_histoty  # Указываем, что будем использовать глобальную переменную

        # ОТВЕТНОЕ СООБЩЕНИЕ
        if update.message.reply_to_message:
            await AI_answer(update, context, AI_question=update.message.text)  # Вызов функции AI_answer для обработки ответа на сообщение
                
        # СООБЩЕНИЕ ЗАПРОС
        else:
            # Отправляем сообщение
            processing_message = await update.message.reply_text("⏳ Loading...", parse_mode="HTML", disable_web_page_preview=True)

            # Читаем сообщение пользователя
            try:
                lines = update.message.text.split("\n")
                chat_id = lines[0].strip()
                try:
                    msg_count = int(lines[1].strip()) # Читаем содержимое второй строки
                except (IndexError, ValueError):
                    msg_count = 10  # Если второй строки нет или она некорректна, используем значение по умолчанию

                try:
                    AI_question = lines[2].strip()  # Читаем содержимое третьей строки
                except IndexError:
                    AI_question = AI_default_prompt  # Если третьей строки нет, устанавливаем значение по умолчанию


            except (IndexError, ValueError):
                await processing_message.edit_text("⚠️ Error: Invalid input format. Please provide chat_id on the first line, msg_count on the second line, and optionally a third line.")
                return

            # Основная логика Pyrogram
            try:
                # Получаем информацию о чате
                chat = await userbotTG_client.get_chat(chat_id)  # Убрано использование async with
                icon, direct_link = get_chat_icon_and_link(chat)
                result = f"<a href='{direct_link}'>{icon} ''{chat.title or chat.first_name}''</a>\n🆔 <code>{chat_id}</code>\n#️⃣ last {msg_count} messages:\n"
                await processing_message.edit_text(result + '\n⏳ Loading...', parse_mode="HTML", disable_web_page_preview=True)

                # Получаем последние сообщения из чата
                messages = []
                async for msg in userbotTG_client.get_chat_history(chat_id, limit=msg_count):  # Асинхронная итерация
                    messages.append(msg)

                    # Формируем ASCII прогресс-бар
                    progress_bar_length = 30  # Длина прогресс-бара
                    progress = int((len(messages) / msg_count) * progress_bar_length)  # 20 символов в прогресс-баре
                    progress_bar = f"{'█' * progress}{'░' * (progress_bar_length - progress)}" 
                    
                    remaining_sec = int((msg_count - len(messages)) * delay_TG)  # Оставшееся время в секундах
                    if remaining_sec <= 60:
                        remaining_time_str = f"{remaining_sec} sec"
                    else:
                         remaining_time_str = f"{remaining_sec // 60} min {remaining_sec % 60} sec"
                    

                    # Обновляем сообщение с прогрессом
                    await processing_message.edit_text(
                        result + f"\n⏳ Loading...\n {len(messages)}/{msg_count} done ~{remaining_time_str} left\n<code>{progress_bar}</code> {round(len(messages) / msg_count * 100, 1)}%",
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    await asyncio.sleep(delay_TG)  # Задержка между запросами для предотвращения превышения лимита API

                if messages:
                    my_chat_histoty = []  # Переменная для хранения истории чата в виде списка
                    for msg in reversed(messages):  # Переворачиваем список для вывода в порядке от старых к новым
                        sender_name = msg.from_user.first_name if msg.from_user else "Unknown_user"
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

                        # Добавляем сообщение в список
                        my_chat_histoty.append({
                            "sender": sender_name,
                            "time": message_time,
                            "content": content
                        })

                    # Сохраняем историю в JSON-файл
                    file_path = f"tg_{msg_count}-msgs-from-{chat.title or chat.first_name}.json"
                    
                    # Формируем данные для сохранения
                    chat_json_data = {
                        "chat_title": chat.title or chat.first_name or "Unknown Chat",
                        "chat_type": chat.type.name if chat.type else "Unknown Type",
                        "link": direct_link,
                        "messages": my_chat_histoty
                        # "participants": []
                    }

                    
                    # Сохраняем данные в JSON-файл
                    with open(file_path, "w", encoding="utf-8") as file:
                        json.dump(chat_json_data, file, indent=4, ensure_ascii=False)
                    
                    print(f"\n💾 Chat history '{file_path}' saved!")


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
                
                    result += f"🔝 <a href='{first_message_link}'>First message</a> {time_since_str}" if first_message_link else f"🔝 First message was sent {time_since_str}"
    

                    chat_history_preview = ""
                    lines_count = 1
                    print(f"is {len(result)} + {len(my_chat_histoty)} < 4096 ?")
                    if len(result) + len(my_chat_histoty) < 4096:
                        print("yes\n")
                        chat_history_preview = "\n".join([
                            f"[{msg['sender']} at {msg['time']}]:\n{msg['content']}\n"
                            for msg in my_chat_histoty
                        ])
                    else:
                        print("no")
                        while len(result)+len(chat_history_preview) < 4096:
                            chat_history_preview = "\n".join([
                                f"[{msg['sender']} at {msg['time']}]:\n{msg['content']}\n"
                                for msg in my_chat_histoty[:lines_count]
                                ]) + f"\n... and {len(my_chat_histoty) - (lines_count * 2)} more lines ...\n\n" + "\n".join([
                                f"[{msg['sender']} at {msg['time']}]:\n{msg['content']}\n"
                                for msg in my_chat_histoty[-lines_count:]
                            ])
                            lines_count += 1
                            print(f"lines_count: {lines_count}")
                            print(f"shortened_history len: {len(chat_history_preview)}")

                    print(f"{len(result)} + {len(my_chat_histoty)} < 4096\n")
                    result += f"<blockquote expandable>{chat_history_preview}</blockquote>"

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
            print("\n💬 [ chat preview ]")

            await context.bot.send_document(
                chat_id=admin_id,
                document=open(file_path, "rb"),
                filename=file_path,
                caption=f"📄 Chat history from  '{chat.title or chat.first_name}'"
            )
            print("💬 [ chat history file ]")


            # Удаляем файл с рабочей папки
            try:
                os.remove(file_path)
                print(f"🗑️ File '{file_path}' has been deleted from working folder")
            except Exception as e:
                print(f"⚠️ Error deleting file '{file_path}': {e}")

            await AI_answer(update, context, AI_question=AI_question)


# AI ответ на сообщение
async def AI_answer(update: Update, context: CallbackContext, AI_question) -> None:
    global my_chat_histoty  # Указываем, что будем использовать глобальную переменную

    # AI_prompt_in_message = update.message.text
    print("💬 [ AI answer ]")
    result = "🤖 AI answer:\n"
    processing_message = await update.message.reply_text(result+"⏳ Loading...", parse_mode="HTML") #, reply_to_message_id=update.message.message_id

    # Отправляем запрос в Geminy
    try:
        ai_response = AI_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"{AI_question}\n\n{my_chat_histoty}",
        )
        response = ai_response if isinstance(ai_response, str) else ai_response.text
        result += f"<blockquote>{bleach.clean(markdown.markdown(response), tags=allowed_tags, strip=True)}</blockquote>"
    except Exception as e:
        result += f"⚠️ Error: {e}"
    
    # Редактируем сообщение после завершения обработки
    await processing_message.edit_text(result, parse_mode="HTML", disable_web_page_preview=True)

# все приходящие сообщения
async def log_message(update: Update, context: CallbackContext) -> None:

    log_any_user(update)
    
# Логирование сообщений в консоль
def log_any_user(update: Update) -> None:
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    username = f"@{update.message.from_user.username}" if update.message.from_user.username else "(no username)"
    message_text = update.message.text if update.message.text else "(non-text message)"
    user_id = update.message.from_user.id if update.message.from_user else "(Unknown user ID)"
    user_name = update.message.from_user.first_name or '' + ' ' + (update.message.from_user.last_name or '')

    # Выводим в консоль
    print(f"\n🗨️ [{current_time} {username}]\n{message_text}")

    if update.message.from_user.id != admin_id:
        asyncio.create_task(send_message(f"⚠️ Message from an unknown user!\n 👤 {user_name}\n{username}\n🆔 <code>{user_id}</code>\nmessage:"))
        asyncio.create_task(forward_message_to_admin(update))

# Функция для пересылки сообщения администратору
async def forward_message_to_admin(update: Update):
    bot = telegram.Bot(token=TGbot_token)
    try:
        # Используем copy_message для пересылки сообщения в том же виде
        await bot.copy_message(
            chat_id=admin_id,  # ID администратора
            from_chat_id=update.message.chat_id,  # ID чата, откуда пришло сообщение
            message_id=update.message.message_id  # ID сообщения для копирования
        )
        print(f"💬 Message forwarded to admin.")
    except Exception as e:
        print(f"⚠️ Error forwarding message to admin: {e}")

# Функция для отправки сообщения администратору
async def send_message(text: str):
    bot = telegram.Bot(token=TGbot_token)
    try:
        await bot.send_message(chat_id=admin_id, text=f"{text}", parse_mode="HTML")
        print(f"💬 Message sent to admin: {text}")
    except Exception as e:
        print(f"⚠️ Error sending message to admin: {e}")
        



# Основная функция для запуска Telegram-бота
def main() -> None:
    # Регистрируем обработчики
    botTG_client.add_handler(CommandHandler("start", start))
    botTG_client.add_handler(CommandHandler("ping", ping))
    botTG_client.add_handler(CommandHandler("list", list_chats))
    botTG_client.add_handler(CommandHandler("ai", ai_query))
    botTG_client.add_handler(CommandHandler("ai_clean", ai_clean))
    botTG_client.add_handler(CommandHandler("json", send_json))
    botTG_client.add_handler(CommandHandler("id", reply_id))
    botTG_client.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    botTG_client.add_handler(MessageHandler(filters.ALL, log_message))
    
    ''' Для телеграм бота команды:
    list - <n> <private/group/channel> show recent chats
    ping - check the bot's connectivity
    start - test
    id - test. get the ID of the replied message
    ai -  test. Ask AI Gemini directly
    ai_clean -  test. Clear the AI dialogue history
    '''

    try:
        # Запускаем бота
        botTG_client.run_polling()
    finally:
        # Закрываем клиента Pyrogram при завершении работы
        userbotTG_client.stop()

if __name__ == '__main__':
    print("🚀 Script started!")

    # Создаём цикл событий
    loop = asyncio.get_event_loop()

    # Отправляем начальное сообщение
    loop.run_until_complete(send_message("🚀 Script updated and started!"))

    # Запускаем клиента Pyrogram
    userbotTG_client.start()  # Открываем соединение с Pyrogram

    # Запускаем основного бота
    main()