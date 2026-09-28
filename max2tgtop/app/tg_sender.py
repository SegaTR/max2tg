import asyncio
import io
import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Sequence

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode, PollLimit
from telegram.error import RetryAfter, TimedOut
from telegram.request import HTTPXRequest

log = logging.getLogger(__name__)

TG_MAX_LENGTH = 4096
TG_CAPTION_MAX = 1024
MAX_RETRIES = 3
_CURRENT_THREAD_ID: ContextVar[int | None] = ContextVar("tg_message_thread_id", default=None)


def reply_keyboard(max_chat_id) -> InlineKeyboardMarkup:
    """Build an inline keyboard with a single 'Reply' button."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 Ответить", callback_data=f"reply:{max_chat_id}")
    ]])


class TelegramSender:
    def __init__(
            self,
            token: str,
            chat_id: str,
            proxy_url: str | None = None,
            read_timeout: int | None = None,
            write_timeout: int | None = None,
            media_write_timeout: int | None = None,
            base_url: str | None = None,
            topic_map_path: str = "logs/max_chat_topics.json",
    ):
        request = HTTPXRequest(proxy=proxy_url, read_timeout=read_timeout, write_timeout=write_timeout, media_write_timeout=media_write_timeout)
        if base_url:
            self._bot = Bot(token=token, request=request, base_url=base_url+"/bot", base_file_url=base_url+"/file/bot")
        else:
            self._bot = Bot(token=token, request=request)
        self._chat_id = chat_id
        self._topic_map_path = topic_map_path
        self._topic_map: dict[str, int] = {}
        self._topic_titles: dict[str, str] = {}
        self._topic_lock = asyncio.Lock()
        try:
            with open(topic_map_path, encoding="utf-8") as topic_file:
                loaded_topics = json.load(topic_file)
            for max_chat_id, topic_data in loaded_topics.items():
                key = str(max_chat_id)
                if isinstance(topic_data, dict):
                    self._topic_map[key] = int(topic_data["thread_id"])
                    if topic_data.get("title"):
                        self._topic_titles[key] = str(topic_data["title"])
                else:
                    # Backward compatibility with the original {max_chat_id: thread_id} format.
                    self._topic_map[key] = int(topic_data)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            log.exception("Unable to read Telegram topic map %s", topic_map_path)

    @property
    def bot(self) -> Bot:
        return self._bot

    async def start(self):
        await self._bot.initialize()
        me = await self._bot.get_me()
        log.info("Telegram bot ready: @%s", me.username)

    async def stop(self):
        await self._bot.shutdown()

    async def ensure_topic(self, max_chat_id, title: str) -> int:
        """Return the Telegram topic for a Max chat, creating it on first use."""
        key = str(max_chat_id)
        topic_title = (title or f"Max {key}").strip()[:128] or f"Max {key}"
        if key in self._topic_map and self._topic_titles.get(key) == topic_title:
            return self._topic_map[key]

        async with self._topic_lock:
            if key in self._topic_map and self._topic_titles.get(key) == topic_title:
                return self._topic_map[key]

            if key in self._topic_map:
                thread_id = self._topic_map[key]
                try:
                    await self._bot.edit_forum_topic(
                        chat_id=self._chat_id,
                        message_thread_id=thread_id,
                        name=topic_title,
                    )
                except Exception:
                    log.exception("Unable to rename Telegram topic for Max chat %s", key)
                    return thread_id
                self._topic_titles[key] = topic_title
                self._save_topic_map()
                log.info("Renamed Telegram topic (thread_id=%d) for Max chat %s to %r", thread_id, key, topic_title)
                return thread_id

            try:
                topic = await self._bot.create_forum_topic(chat_id=self._chat_id, name=topic_title)
            except Exception as exc:
                raise RuntimeError(
                    "Не удалось создать топик Telegram. Убедись, что TG_CHAT_ID — супергруппа "
                    "с включёнными темами и у бота есть право управлять темами."
                ) from exc

            thread_id = int(topic.message_thread_id)
            self._topic_map[key] = thread_id
            self._topic_titles[key] = topic_title
            self._save_topic_map()
            log.info("Created Telegram topic %r (thread_id=%d) for Max chat %s", topic_title, thread_id, key)
            return thread_id

    def resolve_max_chat_id(self, thread_id: int | None):
        """Resolve a Telegram forum topic back to its Max chat ID."""
        if thread_id is None:
            return None
        for max_chat_id, mapped_thread_id in self._topic_map.items():
            if mapped_thread_id == thread_id:
                try:
                    return int(max_chat_id)
                except ValueError:
                    return max_chat_id
        return None

    def _save_topic_map(self) -> None:
        directory = os.path.dirname(self._topic_map_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary_path = f"{self._topic_map_path}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as topic_file:
            topics = {
                key: {"thread_id": thread_id, "title": self._topic_titles.get(key, "")}
                for key, thread_id in self._topic_map.items()
            }
            json.dump(topics, topic_file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, self._topic_map_path)

    @contextmanager
    def topic_context(self, thread_id: int):
        token = _CURRENT_THREAD_ID.set(thread_id)
        try:
            yield
        finally:
            _CURRENT_THREAD_ID.reset(token)

    @staticmethod
    def _thread_kwargs() -> dict:
        thread_id = _CURRENT_THREAD_ID.get()
        return {"message_thread_id": thread_id} if thread_id is not None else {}

    def _truncate(self, text: str, limit: int, suffix: str = "…") -> str:
        if len(text) > limit:
            return text[: limit - len(suffix)] + suffix
        return text

    def _truncate_caption(self, text: str) -> str:
        if len(text) > TG_CAPTION_MAX:
            return text[: TG_CAPTION_MAX - 20] + "\n\n[...усечено]"
        return text

    async def _retry(self, coro_factory):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await coro_factory()
            except RetryAfter as e:
                log.warning("Telegram rate limit, retry after %ss", e.retry_after)
                await asyncio.sleep(e.retry_after)
            except TimedOut:
                log.warning("Telegram timeout (attempt %d/%d). Consider increasing TG_ timeouts settings", attempt, MAX_RETRIES)
                await asyncio.sleep(2 * attempt)
            except Exception:
                log.exception("Failed to send to Telegram (attempt %d/%d)", attempt, MAX_RETRIES)
                if attempt == MAX_RETRIES:
                    return None
                await asyncio.sleep(2 * attempt)
        return None

    async def send(self, text: str, reply_markup=None) -> None:
        if not text:
            return

        if len(text) > TG_MAX_LENGTH:
            text = text[: TG_MAX_LENGTH - 20] + "\n\n[...усечено]"

        await self._retry(
            lambda: self._bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                **self._thread_kwargs(),
            )
        )

    async def send_photo(self, data: bytes, caption: str = "", filename: str = "photo.jpg", reply_markup=None) -> None:
        caption = self._truncate_caption(caption)
        await self._retry(
            lambda: self._bot.send_photo(
                chat_id=self._chat_id,
                photo=InputFile(io.BytesIO(data), filename=filename),
                caption=caption or None,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                **self._thread_kwargs(),
            )
        )

    async def send_document(self, data: bytes, caption: str = "", filename: str = "file", reply_markup=None) -> None:
        caption = self._truncate_caption(caption)
        await self._retry(
            lambda: self._bot.send_document(
                chat_id=self._chat_id,
                document=InputFile(io.BytesIO(data), filename=filename),
                caption=caption or None,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                **self._thread_kwargs(),
            )
        )

    async def send_video(self, data: bytes, caption: str = "", filename: str = "video.mp4", reply_markup=None) -> bool:
        caption = self._truncate_caption(caption)
        result = await self._retry(
            lambda: self._bot.send_video(
                chat_id=self._chat_id,
                video=InputFile(io.BytesIO(data), filename=filename),
                caption=caption or None,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                **self._thread_kwargs(),
            )
        )
        return result is not None

    async def send_voice(self, data: bytes, caption: str = "", reply_markup=None) -> None:
        caption = self._truncate_caption(caption)
        result = await self._retry(
            lambda: self._bot.send_voice(
                chat_id=self._chat_id,
                voice=InputFile(io.BytesIO(data), filename="voice.ogg"),
                caption=caption or None,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                **self._thread_kwargs(),
            )
        )
        if result is None:
            log.info("send_voice failed, falling back to send_audio")
            await self._retry(
                lambda: self._bot.send_audio(
                    chat_id=self._chat_id,
                    audio=InputFile(io.BytesIO(data), filename="audio.m4a"),
                    caption=caption or None,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                    **self._thread_kwargs(),
                )
            )

    async def send_sticker(self, data: bytes, reply_markup=None) -> None:
        await self._retry(
            lambda: self._bot.send_sticker(
                chat_id=self._chat_id,
                sticker=InputFile(io.BytesIO(data), filename="sticker.webp"),
                reply_markup=reply_markup,
                **self._thread_kwargs(),
            )
        )

    async def send_poll(self, question: str, options: Sequence[str], reply_markup=None) -> None:
        """Send a poll. Caller must ensure at least PollLimit.MIN_OPTION_NUMBER non-empty options."""
        question = self._truncate(question, PollLimit.MAX_QUESTION_LENGTH)
        options = [
            self._truncate(opt, PollLimit.MAX_OPTION_LENGTH)
            for opt in options[: PollLimit.MAX_OPTION_NUMBER]
        ]
        await self._retry(
            lambda: self._bot.send_poll(
                chat_id=self._chat_id,
                question=question,
                options=options,
                question_parse_mode=ParseMode.HTML,
                is_anonymous=False,
                allows_multiple_answers=False,
                reply_markup=reply_markup,
                **self._thread_kwargs(),
            )
        )
