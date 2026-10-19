import os
import asyncio
from telegram.request import HTTPXRequest
from src.downloader import download_video, get_video_qualities
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Chat ID: {update.effective_chat.id}")

    await update.message.reply_text(
        "سلام! 👋\n"
        "لینک ویدیوی YouTube رو برام بفرست. 🎬🎵"
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text.strip()

    if "youtube.com/" not in url and "youtu.be/" not in url:
        await update.message.reply_text(
            "لطفاً یک لینک معتبر YouTube بفرست. 🔗"
        )
        return

    context.user_data["youtube_url"] = url

    keyboard = [
        [
            InlineKeyboardButton("🎬 Video", callback_data="video"),
            InlineKeyboardButton("🎵 Audio", callback_data="audio"),
        ]
    ]

    await update.message.reply_text(
        "لینک دریافت شد ✅\n"
        "می‌خوای به چه صورت دانلودش کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("youtube_url")

    if not url:
        await query.edit_message_text(
            "لینک YouTube پیدا نشد. لطفاً دوباره لینک رو بفرست."
        )
        return

    if query.data == "video":
        await query.edit_message_text("⏳ در حال دریافت کیفیت‌های ویدیو...")

        try:
            qualities = await asyncio.to_thread(
                get_video_qualities,
                url,
            )
        except Exception as exc:
            print(f"Error getting video qualities: {exc}")
            await query.edit_message_text(
                "❌ دریافت کیفیت‌های ویدیو با خطا مواجه شد."
            )
            return

        heights = sorted(
            {
                quality["height"]
                for quality in qualities
                if quality.get("height")
            },
            reverse=True,
        )

        if not heights:
            await query.edit_message_text(
                "❌ هیچ کیفیت قابل دانلودی پیدا نشد."
            )
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    f"{height}p",
                    callback_data=f"quality:{height}",
                )
            ]
            for height in heights
        ]

        await query.edit_message_text(
            "🎬 کیفیت ویدیو رو انتخاب کن:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data == "audio":
        await query.edit_message_text("🎵 حالت Audio انتخاب شد.")


async def choose_quality(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query

    try:
        await query.answer()
    except Exception as exc:
        print(
            f"Callback answer warning: "
            f"{type(exc).__name__}: {exc!r}"
        )

    url = context.user_data.get("youtube_url")

    if not url:
        await query.edit_message_text(
            "❌ لینک YouTube پیدا نشد. لطفاً دوباره لینک رو بفرست."
        )
        return

    height = int(query.data.split(":", 1)[1])
    context.user_data["video_height"] = height

    await query.edit_message_text(
        f"⏳ در حال دانلود ویدیو با حداکثر کیفیت {height}p..."
    )

    try:
        result = await asyncio.to_thread(
            download_video,
            url,
            height,
            "downloads",
        )

        filepath = result["filepath"]

        with open(filepath, "rb") as video_file:
            await query.message.reply_video(
                video=video_file,
                caption=f"✅ ویدیو با کیفیت {result['height']}p آماده شد.",
            )

    except Exception as exc:
        print(f"Video download/send error: {type(exc).__name__}: {exc!r}")
        await query.message.reply_text(
            "❌ دانلود یا ارسال ویدیو با خطا مواجه شد."
    )



def main() -> None:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN was not found in .env")

    proxy_url = "socks5://172.23.16.1:10808"

    request = HTTPXRequest(
        proxy=proxy_url,
        connect_timeout=30,
        read_timeout=120,
        write_timeout=180,
    )

    get_updates_request = HTTPXRequest(
        proxy=proxy_url,
        connect_timeout=30,
        read_timeout=120,
        write_timeout=180,
    )

    app = (
        Application.builder()
        .token(TOKEN)
        .request(request)
        .get_updates_request(get_updates_request)
        .build()
    )

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        CallbackQueryHandler(choose_type, pattern="^(video|audio)$")
    )

    app.add_handler(
        CallbackQueryHandler(choose_quality, pattern=r"^quality:\d+$")
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url)
    )

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
