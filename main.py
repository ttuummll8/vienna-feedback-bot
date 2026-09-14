import asyncio
import html
import itertools
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

# НАПОМИНАНИЕ: бот должен быть назначен АДМИНИСТРАТОРОМ в канале CHANNEL_ID
# и в чате модерации ADMIN_CHAT_ID с правом публикации сообщений, иначе
# send_photo / send_document / send_message в них не сработают.
BOT_TOKEN = "8883254089:AAFvlPlW4IOHYhUFsrYtKDL7HGD6O_bcR_w"
CHANNEL_ID = -1004404224769
ADMIN_CHAT_ID = -1004304443290
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
MENU_BUTTONS = {BTN_REVIEW, BTN_CHANNEL, BTN_AUTHOR, BTN_SKIP, BTN_CANCEL}

CB_APPROVE_PREFIX = "modapprove:"
CB_REJECT_PREFIX = "modreject:"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Очередь отзывов, ожидающих решения модератора: review_id -> данные отзыва
PENDING_REVIEWS: dict[int, dict] = {}
_review_id_counter = itertools.count(1)


class Feedback(StatesGroup):
    # НЕ называйте состояние "text" — конфликтует с F.text / Message.text в aiogram
    waiting_name = State()
    waiting_review = State()
    waiting_photo = State()


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


def _moderation_kb(review_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить", callback_data=f"{CB_APPROVE_PREFIX}{review_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=f"{CB_REJECT_PREFIX}{review_id}"
                ),
            ]
        ]
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


def _build_caption(data: dict) -> str:
    name = html.escape(str(data.get("name", "")))
    review = html.escape(str(data.get("review", "")))
    username = html.escape(str(data.get("username", "без username")))
    dt = data.get("dt") or datetime.now().strftime("%d.%m.%Y %H:%M")
    caption = (
        "⭐ <b>Новый отзыв</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>{name}</b> ({username})\n\n"
        f"💬 {review}\n\n"
        f"📅 {dt}"
    )
    if len(caption) > 1024:
        caption = caption[:1021] + "..."
    return caption


def _user_state(chat_id: int, user_id: int) -> FSMContext:
    """Позволяет очистить FSM-состояние пользователя из хэндлера модератора."""
    key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=user_id)
    return FSMContext(storage=dp.storage, key=key)


async def _send_to_moderation(message: Message, state: FSMContext) -> None:
    """Отправляет отзыв на проверку в ADMIN_CHAT_ID и очищает FSM пользователя."""
    data = await state.get_data()
    if not data.get("name") or not data.get("review"):
        await state.clear()
        await message.answer(
            "Данные отзыва потеряны. Начните заново через «✍️ Оставить отзыв».",
            reply_markup=main_kb,
        )
        return

    user = message.from_user
    username = f"@{user.username}" if user and user.username else "без username"

    review_id = next(_review_id_counter)
    PENDING_REVIEWS[review_id] = {
        "name": data.get("name"),
        "review": data.get("review"),
        "photo": data.get("photo"),
        "document": data.get("document"),
        "username": username,
        "dt": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "user_id": user.id if user else None,
        "chat_id": message.chat.id,
    }
    caption = _build_caption(PENDING_REVIEWS[review_id])
    kb = _moderation_kb(review_id)

    try:
        if data.get("photo"):
            await bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=data["photo"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=kb,
            )
        elif data.get("document"):
            await bot.send_document(
                chat_id=ADMIN_CHAT_ID,
                document=data["document"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=kb,
            )
        else:
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=caption,
                parse_mode="HTML",
                reply_markup=kb,
            )
    except Exception as e:
        print(f"ОШИБКА: {e}")
        PENDING_REVIEWS.pop(review_id, None)
        await state.clear()
        await message.answer(
            "Не удалось отправить отзыв на модерацию. "
            "Проверьте, что бот — администратор чата модерации "
            "с правом публикации и что ADMIN_CHAT_ID указан верно.",
            reply_markup=main_kb,
        )
        return

    # Важно: очищаем FSM пользователя сразу, чтобы второй круг анкеты
    # всегда начинался с чистого состояния, независимо от решения модератора.
    await state.clear()
    await message.answer(
        "🕓 Спасибо! Ваш отзыв отправлен на модерацию.\n"
        "Как только его проверят, мы вам напишем.",
        reply_markup=main_kb,
    )


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


@dp.message(StateFilter(None), F.text == BTN_CHANNEL)
async def show_channel(message: Message) -> None:
    await message.answer(
        "📢 Все отзывы публикуются в канале.\nНажми кнопку ниже, чтобы открыть его.",
        reply_markup=channel_inline_kb,
    )


@dp.message(StateFilter(None), F.text == BTN_AUTHOR)
async def show_author(message: Message) -> None:
    await message.answer(
        "👨‍💻 Есть вопрос по боту или сотрудничеству?\n"
        "Напиши автору напрямую — кнопка ниже.",
        reply_markup=author_inline_kb,
    )


@dp.message(F.text == BTN_REVIEW)
async def start_feedback(message: Message, state: FSMContext) -> None:
    # Полный сброс: второй и последующие отзывы всегда стартуют с чистого FSM
    await state.clear()
    await state.set_state(Feedback.waiting_name)
    await message.answer(
        "Как вас зовут?\n<i>Минимум 2 символа. Для отмены нажмите «❌ Отмена».</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )


@dp.message(StateFilter(Feedback.waiting_name), F.text)
async def get_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if name in MENU_BUTTONS:
        await message.answer(
            "Пожалуйста, введите имя текстом (минимум 2 символа).",
            reply_markup=cancel_kb,
        )
        return
    if len(name) < 2:
        await message.answer(
            "Имя слишком короткое. Введите минимум 2 символа.",
            reply_markup=cancel_kb,
        )
        return

    await state.update_data(name=name, review=None, photo=None, document=None)
    await state.set_state(Feedback.waiting_review)
    await message.answer(
        "Напишите текст отзыва.\n<i>Минимум 10 символов.</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb,
    )


@dp.message(StateFilter(Feedback.waiting_name))
async def name_invalid(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте имя текстом.", reply_markup=cancel_kb)


@dp.message(StateFilter(Feedback.waiting_review), F.text)
async def get_review(message: Message, state: FSMContext) -> None:
    review = (message.text or "").strip()
    if review in MENU_BUTTONS:
        await message.answer(
            "Пожалуйста, напишите текст отзыва (минимум 10 символов).",
            reply_markup=cancel_kb,
        )
        return
    if len(review) < 10:
        await message.answer(
            "Отзыв слишком короткий. Напишите минимум 10 символов.",
            reply_markup=cancel_kb,
        )
        return

    await state.update_data(review=review, photo=None, document=None)
    await state.set_state(Feedback.waiting_photo)
    await message.answer(
        "Можете прислать скриншот — фото или изображение файлом.\n"
        "<i>Это желательно, но необязательно. "
        "Чтобы отправить отзыв на модерацию без фото, нажмите «⏭ Пропустить».</i>",
        parse_mode="HTML",
        reply_markup=photo_step_kb,
    )


@dp.message(StateFilter(Feedback.waiting_review))
async def review_invalid(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте текст отзыва.", reply_markup=cancel_kb)


@dp.message(StateFilter(Feedback.waiting_photo), F.photo)
async def waiting_for_photo(message: Message, state: FSMContext) -> None:
    await state.update_data(photo=message.photo[-1].file_id, document=None)
    await _send_to_moderation(message, state)


@dp.message(StateFilter(Feedback.waiting_photo), F.document)
async def waiting_for_document(message: Message, state: FSMContext) -> None:
    if not _is_image_document(message):
        await message.answer(
            "Нужно изображение (фото или файл-картинка) "
            "либо нажмите «⏭ Пропустить».",
            reply_markup=photo_step_kb,
        )
        return
    await state.update_data(photo=None, document=message.document.file_id)
    await _send_to_moderation(message, state)


@dp.message(StateFilter(Feedback.waiting_photo), F.text == BTN_SKIP)
async def skip_photo(message: Message, state: FSMContext) -> None:
    """Пропуск шага фото: отправляем отзыв на модерацию без изображения."""
    await state.update_data(photo=None, document=None)
    await _send_to_moderation(message, state)


@dp.message(StateFilter(Feedback.waiting_photo))
async def photo_step_fallback(message: Message) -> None:
    await message.answer(
        "Отправьте фото (или изображение файлом) "
        "либо нажмите «⏭ Пропустить», чтобы отправить отзыв без картинки.",
        reply_markup=photo_step_kb,
    )


@dp.callback_query(F.data.startswith(CB_APPROVE_PREFIX))
async def approve_review(callback: CallbackQuery) -> None:
    review_id = int(callback.data.removeprefix(CB_APPROVE_PREFIX))
    data = PENDING_REVIEWS.pop(review_id, None)
    if not data:
        await callback.answer("Этот отзыв уже обработан.", show_alert=True)
        return

    caption = _build_caption(data)
    try:
        if data.get("photo"):
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=data["photo"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=bot_inline_kb,
            )
        elif data.get("document"):
            await bot.send_document(
                chat_id=CHANNEL_ID,
                document=data["document"],
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
        await callback.answer(
            "Не удалось опубликовать в канал. Проверьте права бота.",
            show_alert=True,
        )
        return

    # Уведомляем пользователя и на всякий случай ещё раз чистим его FSM,
    # чтобы исключить любые зацикливания на следующем круге анкеты.
    chat_id: Optional[int] = data.get("chat_id")
    user_id: Optional[int] = data.get("user_id")
    if chat_id is not None:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="🎉 Ваш отзыв одобрен и опубликован в канале! Спасибо!",
            )
        except Exception as e:
            print(f"ОШИБКА уведомления пользователя: {e}")
    if chat_id is not None and user_id is not None:
        await _user_state(chat_id, user_id).clear()

    try:
        if callback.message.caption is not None:
            await callback.message.edit_caption(
                caption=caption + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                caption + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML"
            )
    except Exception:
        pass

    await callback.answer("Опубликовано ✅")


@dp.callback_query(F.data.startswith(CB_REJECT_PREFIX))
async def reject_review(callback: CallbackQuery) -> None:
    review_id = int(callback.data.removeprefix(CB_REJECT_PREFIX))
    data = PENDING_REVIEWS.pop(review_id, None)
    if not data:
        await callback.answer("Этот отзыв уже обработан.", show_alert=True)
        return

    chat_id: Optional[int] = data.get("chat_id")
    user_id: Optional[int] = data.get("user_id")
    if chat_id is not None:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="😔 К сожалению, ваш отзыв не прошёл модерацию.",
            )
        except Exception as e:
            print(f"ОШИБКА уведомления пользователя: {e}")
    if chat_id is not None and user_id is not None:
        await _user_state(chat_id, user_id).clear()

    caption = _build_caption(data)
    try:
        if callback.message.caption is not None:
            await callback.message.edit_caption(
                caption=caption + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                caption + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML"
            )
    except Exception:
        pass

    await callback.answer("Отклонено ❌")


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
