"""Tests for app/tg_sender.py — TelegramSender.send_poll, send_video, __init__."""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.constants import PollLimit

from app.tg_sender import TelegramSender


def _make_sender() -> TelegramSender:
    sender = TelegramSender.__new__(TelegramSender)
    sender._bot = MagicMock()
    sender._bot.send_poll = AsyncMock()
    sender._bot.send_video = AsyncMock()
    sender._bot.send_message = AsyncMock()
    sender._chat_id = "123"
    sender._topic_map_path = "unused-topic-map.json"
    sender._topic_map = {}
    sender._topic_titles = {}
    sender._topic_lock = asyncio.Lock()
    return sender


class TestSendPoll:
    @pytest.mark.asyncio
    async def test_sends_question_and_options_unchanged_when_within_limits(self):
        sender = _make_sender()

        await sender.send_poll("Вопрос?", ["Да", "Нет"])

        sender._bot.send_poll.assert_awaited_once()
        kwargs = sender._bot.send_poll.await_args.kwargs
        assert kwargs["question"] == "Вопрос?"
        assert kwargs["options"] == ["Да", "Нет"]

    @pytest.mark.asyncio
    async def test_truncates_question_over_limit(self):
        sender = _make_sender()
        long_question = "a" * (PollLimit.MAX_QUESTION_LENGTH + 50)

        await sender.send_poll(long_question, ["Да", "Нет"])

        sent_question = sender._bot.send_poll.await_args.kwargs["question"]
        assert len(sent_question) == PollLimit.MAX_QUESTION_LENGTH

    @pytest.mark.asyncio
    async def test_truncates_option_over_limit(self):
        sender = _make_sender()
        long_option = "b" * (PollLimit.MAX_OPTION_LENGTH + 50)

        await sender.send_poll("Q", [long_option, "Нет"])

        sent_options = sender._bot.send_poll.await_args.kwargs["options"]
        assert len(sent_options[0]) == PollLimit.MAX_OPTION_LENGTH

    @pytest.mark.asyncio
    async def test_caps_option_count_at_max(self):
        sender = _make_sender()
        options = [f"opt{i}" for i in range(PollLimit.MAX_OPTION_NUMBER + 5)]

        await sender.send_poll("Q", options)

        sent_options = sender._bot.send_poll.await_args.kwargs["options"]
        assert len(sent_options) == PollLimit.MAX_OPTION_NUMBER


class TestSendVideo:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        sender = _make_sender()
        sender._bot.send_video.return_value = MagicMock()

        result = await sender.send_video(b"data", caption="cap")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_telegram_rejects_upload(self):
        from telegram.error import BadRequest
        sender = _make_sender()
        sender._bot.send_video.side_effect = BadRequest("Request Entity Too Large")

        result = await sender.send_video(b"data", caption="cap")

        assert result is False


class TestTelegramSenderInit:
    def test_default_base_url_not_overridden(self):
        with patch("app.tg_sender.Bot") as bot_cls:
            TelegramSender(token="t", chat_id="1")

        kwargs = bot_cls.call_args.kwargs
        assert "base_url" not in kwargs
        assert "base_file_url" not in kwargs

    def test_custom_base_url_passed_to_bot(self):
        with patch("app.tg_sender.Bot") as bot_cls:
            TelegramSender(token="t", chat_id="1", base_url="http://localhost:8081")

        kwargs = bot_cls.call_args.kwargs
        assert kwargs["base_url"] == "http://localhost:8081/bot"
        assert kwargs["base_file_url"] == "http://localhost:8081/file/bot"


class TestForumTopics:
    @pytest.mark.asyncio
    async def test_creates_and_persists_topic_for_max_chat(self, tmp_path):
        sender = _make_sender()
        sender._topic_map_path = str(tmp_path / "topics.json")
        sender._bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=456))

        thread_id = await sender.ensure_topic(789, "Рабочий чат")

        assert thread_id == 456
        sender._bot.create_forum_topic.assert_awaited_once_with(chat_id="123", name="Рабочий чат")
        assert json.loads((tmp_path / "topics.json").read_text(encoding="utf-8")) == {
            "789": {"thread_id": 456, "title": "Рабочий чат"},
        }

    @pytest.mark.asyncio
    async def test_reuses_topic_mapping(self, tmp_path):
        sender = _make_sender()
        sender._topic_map["789"] = 456
        sender._bot.create_forum_topic = AsyncMock()

        assert await sender.ensure_topic(789, "Рабочий чат") == 456
        sender._bot.create_forum_topic.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_message_uses_current_topic_context(self):
        sender = _make_sender()

        with sender.topic_context(456):
            await sender.send("hello")

        assert sender._bot.send_message.await_args.kwargs["message_thread_id"] == 456

    @pytest.mark.asyncio
    async def test_send_message_without_topic_uses_root_chat(self):
        sender = _make_sender()

        await sender.send("hello")

        assert "message_thread_id" not in sender._bot.send_message.await_args.kwargs

    @pytest.mark.asyncio
    async def test_renames_legacy_topic_that_was_named_by_id(self, tmp_path):
        path = tmp_path / "topics.json"
        path.write_text('{"789": 456}', encoding="utf-8")
        sender = _make_sender()
        sender._topic_map_path = str(path)
        sender._topic_map = {"789": 456}
        sender._bot.edit_forum_topic = AsyncMock()

        assert await sender.ensure_topic(789, "Имя собеседника") == 456

        sender._bot.edit_forum_topic.assert_awaited_once_with(
            chat_id="123", message_thread_id=456, name="Имя собеседника",
        )
        assert json.loads(path.read_text(encoding="utf-8"))["789"] == {
            "thread_id": 456,
            "title": "Имя собеседника",
        }
