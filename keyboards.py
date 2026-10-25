from config import Config


def main_menu_keyboard():
    buttons = [
        [
            {"type": "callback", "text": "📤 Загрузить фото", "payload": "menu:upload"},
            {"type": "callback", "text": "👫 Парные фото", "payload": "menu:couple"},
        ],
        [
            {"type": "callback", "text": "🖼️ Стили", "payload": "menu:styles"},
            {"type": "callback", "text": "💎 Мои жетоны", "payload": "menu:tokens"},
        ],
        [
            {"type": "callback", "text": "💳 Купить генерацию", "payload": "menu:buy"},
            {"type": "callback", "text": "❓ Помощь", "payload": "menu:help"},
        ],
        [
            {"type": "callback", "text": "🗑 Очистить селфи", "payload": "menu:clean"},
            {"type": "callback", "text": "🏠 Главное меню", "payload": "menu:main"},
        ],
        [
            {"type": "callback", "text": "✍️ Свой промпт", "payload": "menu:custom"},
            {"type": "callback", "text": "🎬 Создать видео", "payload": "menu:video"},
        ],
    ]
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def back_to_menu_keyboard():
    buttons = [[{"type": "callback", "text": "🏠 Главное меню", "payload": "menu:main"}]]
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def styles_keyboard():
    """Стили по 2 в ряд (укладываемся в лимит MAX — 30 рядов)."""
    buttons = []
    row = []
    for key, style in Config.STYLES.items():
        row.append({
            "type": "callback",
            "text": style["name"],
            "payload": f"select_style_{key}",
        })
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"type": "callback", "text": "🏠 Меню", "payload": "menu:main"}])
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def model_select_keyboard():
    buttons = [
        [{"type": "callback", "text": "🚀 Gemini (базовое) – 38₽",
          "payload": "select_model_gemini"}],
        [{"type": "callback", "text": "💎 GPT Image High – 76₽",
          "payload": "select_model_gpt"}],
        [{"type": "callback", "text": "🍌 Nano Banana Pro – 75₽",
          "payload": "select_model_nanobanana"}],
        [{"type": "callback", "text": "🏠 Меню", "payload": "menu:main"}],
    ]
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def pay_method_keyboard(tokens: int, token_cost: int, price_rub: int):
    buttons = []
    if tokens >= token_cost:
        buttons.append([{
            "type": "callback",
            "text": f"💎 Использовать жетоны ({token_cost} шт., у вас {tokens})",
            "payload": "use_token",
        }])
    buttons.append([{
        "type": "callback",
        "text": f"💳 Купить за {price_rub}₽",
        "payload": "buy_generation",
    }])
    buttons.append([{"type": "callback", "text": "🏠 Меню", "payload": "menu:main"}])
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def payment_link_keyboard(payment_url: str, amount: int):
    buttons = [[{"type": "link", "text": f"💳 Оплатить {amount}₽", "url": payment_url}]]
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


def upload_done_keyboard():
    buttons = [
        [{"type": "callback", "text": "✅ Готово", "payload": "upload:done"}],
        [{"type": "callback", "text": "❌ Отмена", "payload": "upload:cancel"}],
    ]
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]