"""Постоянная клавиатура с кнопками быстрых запросов."""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_WEATHER, BTN_BTC, BTN_USD = "🌤 Погода", "₿ BTC", "💵 Доллар"
BTN_WORLD, BTN_RUSSIA, BTN_LOCAL = "🌍 Мир", "🇷🇺 Россия", "🏙 Нижний Новгород"
NEWS_BUTTONS = {BTN_WORLD: "Мир", BTN_RUSSIA: "Россия"}
# прикладывается к каждому сообщению бота: кнопки появляются без /start и не сворачиваются
KEYBOARD = ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True, keyboard=[
    [KeyboardButton(text=BTN_WEATHER), KeyboardButton(text=BTN_BTC), KeyboardButton(text=BTN_USD)],
    [KeyboardButton(text=BTN_WORLD), KeyboardButton(text=BTN_RUSSIA), KeyboardButton(text=BTN_LOCAL)],
])
