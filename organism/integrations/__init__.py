"""External communication adapters (Telegram Bot API via Python stdlib)."""

from .telegram import (
    TelegramAuthResult,
    TelegramBotClient,
    TelegramBridge,
    TelegramConfigError,
    TelegramNetworkError,
    authorize_telegram_update,
    derive_opaque_session_id,
    split_telegram_message,
)

__all__ = [
    "TelegramAuthResult",
    "TelegramBotClient",
    "TelegramBridge",
    "TelegramConfigError",
    "TelegramNetworkError",
    "authorize_telegram_update",
    "derive_opaque_session_id",
    "split_telegram_message",
]
