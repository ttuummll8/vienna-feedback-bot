import asyncio
import html
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

# НАПОМИНАНИЕ: бот должен быть назначен АДМИНИСТРАТОРОМ в канале CHANNEL_ID
# с правом публикации сообщений, иначе send_photo / send_document не сработает.
BOT_TOKEN = "8883254089:AAFvlPlW4IOHYhUFsrYtKDL7HGD6O_bcR_w"
CHANNEL_ID = -1004404224769
BOT_URL = "https://t.me/ViennPortfolioBot"
CHANNEL_URL = "https://t.me/c/4404224769"
AUTHOR_URL = "https://t.me/ViennaVB"
PHOTO_PATH = "logo.jpg"

BTN_REVIEW = "✍️ Оставить отзыв"
BTN_CHANNEL = "📢 Канал с отзывами"
BTN_AUTHOR = "👨‍💻 Связаться с автором"
BTN_CANCEL = "❌ Отмена"
BTN_SKIP = "⏭ Пропустить"

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class Feedback(StatesGroup):
    name = State()
    text = State()
    waiting_for_photo = State()


main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_REVIEW)],
        [KeyboardButton(text=BTN_CHANNEL), KeyboardButton(text=BTN_AUTHOR)],
    ],
    resize_keyboard=True,
)

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
    resize_keyboard=True,
)

photo_step_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_SKIP)],
        [KeyboardButton(text=BTN_CANCEL)],
    ],
    resize_keyboard=True,
)

channel_inline_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📢 Открыть канал с отзывами", url=CHANNEL_URL)]
    ]
)

author_inline_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💻 Написать автору", url=AUTHOR_URL)]
    ]
)

bot_inline_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Оставить свой отзыв", url=BOT_URL)]
    ]
)

WELCOME_CAPTION = (
    "🔥 *Рад тебя видеть!*\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "Этот бот создан для того, чтобы собирать честные отзывы "
    "и показывать реальные результаты.\n\n"
    "Если мы уже поработали — нажимай *«✍️ Оставить отзыв»*.\n"
    "Хочешь посмотреть, что говорят другие? Нажимай "
    "*«📢 Канал с отзывами»* ниже. 👇"
)


def _is_image_document(message: Message) -> bool:
    doc = message.document
    if not doc:
        return False
    mime = (doc.mime_type or "").lower()
    if mime.startswith("image/"):
        return True
    name = (doc.file_name or "").lower()
    return name.endswith(IMAGE_EXTENSIONS)


def _build_caption(data: dict, message: Message) -> str:
    user = message.from_user
    username = f"@{user.username}" if user and user.username else "без username"
    dt = datetime.now().strftime("%d.%m.%Y %H:%M")
    name = html.escape(str(data.get("name", "")))
    text = html.escape(str(data.get("text", "")))
    username = html.escape(username)
    caption = (
        "⭐ <b>Новый отзыв</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>{name}</b> ({username})\n\n"
        f"💬 {text}\n\n"
        f"📅 {dt}"
    )
    if len(caption) > 1024:
        caption = caption[:1021] + "..."
    return caption


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    try:
        photo = FSInputFile(PHOTO_PATH)
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=photo,
            caption=WELCOME_CAPTION,
            parse_mode="Markdown",
            reply_markup=main_kb,
        )
    except Exception:
        await message.answer(
            WELCOME_CAPTION,
            parse_mode="Markdown",
            reply_markup=main_kb,
        )


@dp.message(Command("cancel"))
@dp.message(F.text == BTN_CANCEL)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено. Вы в главном меню.", reply_markup=main_kb)


@dp.message(F.text == BTN_CHANNEL)
async def show_channel(message: Message) -> None:
    await message.answer(
        "📢 Все отзывы публикуются в канале.\nНажми кнопку ниже, чтобы открыть его.",
        reply_markup=channel_inline_kb,
    )


@dp.message(F.text == BTN_AUTHOR)
async def show_author(message: Message) -> None:
    await message.answer(
        "👨‍💻 Есть вопрос по боту или сотрудничеству?\n"
        "Напиши автору напрямую — кнопка ниже.",
        reply_markup=author_inline_kb,
    )


@dp.message(F.text == BTN_REVIEW)
async def start_feedback(message: Message, state: FSMContext) -> None:
    await state.set_state(Feedback.name)
    await message.answer(
        "Как вас зовут?\n<i>Минимум 2 символа. Для отмены нажмите «❌ Отмена».</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )


@dp.message(Feedback.name, F.text)
async def get_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(
            "Имя слишком короткое. Введите минимум 2 символа.",
            reply_markup=cancel_kb,
        )
        return
    await state.update_data(name=name)
    await state.set_state(Feedback.text)
    await message.answer(
        "Напишите текст отзыва.\n<i>Минимум 10 символов.</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )


@dp.message(Feedback.name)
async def name_invalid(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте имя текстом.", reply_markup=cancel_kb)


@dp.message(Feedback.text, F.text)
async def get_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 10:
        await message.answer(
            "Отзыв слишком короткий. Напишите минимум 10 символов.",
            reply_markup=cancel_kb,
        )
        return
    await state.update_data(text=text, photo=None)
    await state.set_state(Feedback.waiting_for_photo)
    await message.answer(
        "Можете прислать скриншот — фото или изображение файлом.\n"
        "<i>Это желательно, но необязательно: нажмите «⏭ Пропустить» "
        "или отправьте любое текстовое сообщение, чтобы опубликовать отзыв без фото.</i>",
        parse_mode="HTML",
        reply_markup=photo_step_kb,
    )


@dp.message(Feedback.text)
async def text_invalid(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте текст отзыва.", reply_markup=cancel_kb)


async def _publish_review(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    caption = _build_caption(data, message)
    photo_id = data.get("photo")
    document_id = data.get("document")

    try:
        if photo_id:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=bot_inline_kb,
            )
        elif document_id:
            await bot.send_document(
                chat_id=CHANNEL_ID,
                document=document_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=bot_inline_kb,
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=caption,
                parse_mode="HTML",
                reply_markup=bot_inline_kb,
            )
    except Exception as e:
        print(f"ОШИБКА: {e}")
        await message.answer(
            "Не удалось опубликовать отзыв в канал. "
            "Проверьте, что бот — администратор канала с правом публикации "
            "и что CHANNEL_ID указан верно. Можете прислать скриншот ещё раз "
            "или нажать «⏭ Пропустить».",
            reply_markup=photo_step_kb,
        )
        return

    await state.clear()
    await message.answer(
        "🎉 Спасибо за отзыв! Он опубликован в канале.",
        reply_markup=main_kb,
    )


@dp.message(Feedback.waiting_for_photo, F.photo)
async def waiting_for_photo(message: Message, state: FSMContext) -> None:
    await state.update_data(photo=message.photo[-1].file_id, document=None)
    await _publish_review(message, state)


@dp.message(Feedback.waiting_for_photo, F.document)
async def waiting_for_document(message: Message, state: FSMContext) -> None:
    if not _is_image_document(message):
        await state.update_data(photo=None, document=None)
        await _publish_review(message, state)
        return
    await state.update_data(photo=None, document=message.document.file_id)
    await _publish_review(message, state)


# Обработка нажатия кнопки «Пропустить» или отправки любого текста для пропуска
@dp.message(Feedback.waiting_for_photo, F.text == BTN_SKIP)
async def skip_photo_btn(message: Message, state: FSMContext) -> None:
    await state.update_data(photo=None, document=None)
    await _publish_review(message, state)


@dp.message(Feedback.waiting_for_photo, F.text)
async def skip_photo_text(message: Message, state: FSMContext) -> None:
    await state.update_data(photo=None, document=None)
    await _publish_review(message, state)


# Защита от отправки стикеров, аудио и прочего мусора на шаге фото
@dp.message(Feedback.waiting_for_photo)
async def photo_step_invalid(message: Message) -> None:
    await message.answer(
        "Пожалуйста, отправьте скриншот (фото/файл) или нажмите «⏭ Пропустить».",
        reply_markup=photo_step_kb,
    )


async def main() -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="cancel", description="Отменить действие"),
        ]
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
