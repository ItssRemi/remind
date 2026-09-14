import asyncio
import random
import re
import time
from typing import Optional

import discord
from redbot.core import Config, commands


class ReminderNoticeView(discord.ui.LayoutView):
    """Persistent Components V2 view shown when a reminder is created."""

    def __init__(self, cog: "Reminder", reminder_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.reminder_id = reminder_id

        container = discord.ui.Container(
            discord.ui.TextDisplay(
                self.cog.get_notice_content(reminder_id)
            ),
            discord.ui.ActionRow(
                discord.ui.Button(
                    label="Cancel",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"remind_cancel:{reminder_id}",
                ),
                discord.ui.Button(
                    label="x",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"remind_close:{reminder_id}",
                ),
            ),
        )

        self.add_item(container)

        for item in container.children[-1].children:
            if item.custom_id == f"remind_cancel:{reminder_id}":
                item.callback = self.cancel_callback
            elif item.custom_id == f"remind_close:{reminder_id}":
                item.callback = self.close_callback

    async def cancel_callback(self, interaction: discord.Interaction):
        await self.cog.handle_cancel(interaction, self.reminder_id)

    async def close_callback(self, interaction: discord.Interaction):
        await self.cog.handle_close(interaction, self.reminder_id)


class ReminderView(discord.ui.LayoutView):
    """Persistent Components V2 view shown when a reminder fires."""

    def __init__(self, cog: "Reminder", reminder_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.reminder_id = reminder_id

        button = discord.ui.Button(
            label="Repeat",
            style=discord.ButtonStyle.secondary,
            custom_id=f"remind_repeat:{reminder_id}",
        )
        button.callback = self.repeat_callback

        section = discord.ui.Section(
            accessory=button,
        )

        section.add_item(
            discord.ui.TextDisplay(
                self.cog.get_reminder_content(reminder_id)
            )
        )

        self.add_item(section)

    async def repeat_callback(self, interaction: discord.Interaction):
        await self.cog.handle_repeat(
            interaction,
            self.reminder_id,
        )


class ReminderListView(discord.ui.LayoutView):
    """Components V2 reminder list with up to five reminders per page."""

    def __init__(
        self,
        cog: "Reminder",
        user_id: int,
        page: int = 0,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.page = page

        self.reminder_ids = self.cog.get_owned_reminder_ids(user_id)
        self.total_pages = max(
            1,
            (len(self.reminder_ids) + 4) // 5,
        )

        self.page = min(
            max(page, 0),
            self.total_pages - 1,
        )

        start = self.page * 5
        page_ids = self.reminder_ids[start:start + 5]

        lines = []
        for index, reminder_id in enumerate(
            page_ids,
            start=start + 1,
        ):
            reminder = self.cog._reminder_cache[reminder_id]
            timestamp = int(reminder["due_at"])
            title = reminder.get("title") or ""
            lines.append(
                f"{index}. <t:{timestamp}:R> {title}"
            )

        content = "\n".join(lines) or "You don't have any reminders."

        container = discord.ui.Container(
            discord.ui.TextDisplay("## Reminders"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(content),
        )

        if page_ids:
            row = discord.ui.ActionRow()

            for index, reminder_id in enumerate(
                page_ids,
                start=start + 1,
            ):
                button = discord.ui.Button(
                    label=str(index),
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"remind_select:{user_id}:{reminder_id}",
                )
                button.callback = self.select_callback
                row.add_item(button)

            container.add_item(row)

        if self.total_pages > 1:
            nav = discord.ui.ActionRow()

            previous = discord.ui.Button(
                label="Previous",
                style=discord.ButtonStyle.secondary,
                custom_id=f"remind_page:{user_id}:{self.page - 1}",
                disabled=self.page == 0,
            )
            previous.callback = self.previous_callback

            next_button = discord.ui.Button(
                label="Next",
                style=discord.ButtonStyle.secondary,
                custom_id=f"remind_page:{user_id}:{self.page + 1}",
                disabled=self.page >= self.total_pages - 1,
            )
            next_button.callback = self.next_callback

            nav.add_item(previous)
            nav.add_item(next_button)
            container.add_item(nav)

        container.add_item(
            discord.ui.Separator()
        )
        container.add_item(
            discord.ui.TextDisplay(
                f"-# Page {self.page + 1} of {self.total_pages}"
            )
        )

        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "that isn't your reminder list.",
                ephemeral=True,
            )
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        custom_id = interaction.data.get("custom_id", "")
        reminder_id = custom_id.rsplit(":", 1)[-1]

        if reminder_id not in self.cog._reminder_cache:
            await interaction.response.send_message(
                "that reminder no longer exists.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            view=ReminderDetailView(
                self.cog,
                self.user_id,
                reminder_id,
            )
        )

    async def previous_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            view=ReminderListView(
                self.cog,
                self.user_id,
                self.page - 1,
            )
        )

    async def next_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            view=ReminderListView(
                self.cog,
                self.user_id,
                self.page + 1,
            )
        )


class ReminderDetailView(discord.ui.LayoutView):
    """Components V2 view for editing one reminder."""

    def __init__(
        self,
        cog: "Reminder",
        user_id: int,
        reminder_id: str,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.reminder_id = reminder_id

        reminder = self.cog._reminder_cache.get(reminder_id)
        if reminder is None:
            self.add_item(
                discord.ui.Container(
                    discord.ui.TextDisplay(
                        "that reminder no longer exists."
                    )
                )
            )
            return

        title = reminder.get("title") or ""
        timestamp = int(reminder["due_at"])

        row = discord.ui.ActionRow()

        time_button = discord.ui.Button(
            label="Time",
            style=discord.ButtonStyle.secondary,
            custom_id=f"remind_edit_time:{reminder_id}",
        )
        time_button.callback = self.time_callback

        title_button = discord.ui.Button(
            label="Title",
            style=discord.ButtonStyle.secondary,
            custom_id=f"remind_edit_title:{reminder_id}",
        )
        title_button.callback = self.title_callback

        delete_button = discord.ui.Button(
            label="Delete",
            style=discord.ButtonStyle.danger,
            custom_id=f"remind_edit_delete:{reminder_id}",
        )
        delete_button.callback = self.delete_callback

        row.add_item(time_button)
        row.add_item(title_button)
        row.add_item(delete_button)

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    f"## Reminder {self.cog.get_reminder_number(user_id, reminder_id)}"
                ),
                discord.ui.Separator(),
                discord.ui.TextDisplay(
                    f"<t:{timestamp}:R> {title}"
                ),
                discord.ui.Separator(),
                row,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "that isn't your reminder.",
                ephemeral=True,
            )
            return False
        return True

    async def time_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            ReminderTimeModal(
                self.cog,
                self.reminder_id,
            )
        )

    async def title_callback(self, interaction: discord.Interaction):
        reminder = self.cog._reminder_cache.get(self.reminder_id)
        if reminder is None:
            await interaction.response.send_message(
                "that reminder no longer exists.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            ReminderTitleModal(
                self.cog,
                self.reminder_id,
                reminder.get("title") or "",
            )
        )

    async def delete_callback(self, interaction: discord.Interaction):
        await self.cog.handle_delete_one(
            interaction,
            self.reminder_id,
        )


class ReminderTimeModal(discord.ui.Modal, title="Change reminder time"):
    def __init__(self, cog: "Reminder", reminder_id: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.reminder_id = reminder_id

        self.time_input = discord.ui.TextInput(
            label="Time from now",
            placeholder="30m, 2h, 7d, 1w",
            required=True,
            max_length=32,
        )
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        seconds = self.cog._parse_time(str(self.time_input.value))

        if seconds is None or seconds <= 0:
            await interaction.response.send_message(
                "use a time like `30m`, `2h`, `7d`, or `1w`.",
                ephemeral=True,
            )
            return

        if seconds > self.cog.MAX_REMINDER_SECONDS:
            await interaction.response.send_message(
                "the maximum reminder time is 365 days.",
                ephemeral=True,
            )
            return

        if not await self.cog.change_time(
            interaction,
            self.reminder_id,
            seconds,
        ):
            return

        await interaction.response.send_message(
            f"reminder moved to <t:{int(time.time() + seconds)}:R>.",
            ephemeral=True,
        )


class ReminderTitleModal(discord.ui.Modal, title="Change reminder title"):
    def __init__(
        self,
        cog: "Reminder",
        reminder_id: str,
        current_title: str,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.reminder_id = reminder_id

        self.title_input = discord.ui.TextInput(
            label="Title",
            placeholder="What do you need to remember?",
            required=False,
            max_length=256,
            default=current_title,
        )
        self.add_item(self.title_input)

    async def on_submit(self, interaction: discord.Interaction):
        reminder = self.cog._reminder_cache.get(self.reminder_id)

        if reminder is None:
            await interaction.response.send_message(
                "that reminder no longer exists.",
                ephemeral=True,
            )
            return

        if interaction.user.id != reminder["user_id"]:
            await interaction.response.send_message(
                "that isn't your reminder.",
                ephemeral=True,
            )
            return

        reminder["title"] = str(self.title_input.value).strip() or None

        await self.cog._save_reminder(
            self.reminder_id,
            reminder,
        )

        await self.cog._refresh_reminder_ui(
            self.reminder_id
        )

        await interaction.response.send_message(
            "reminder title updated.",
            ephemeral=True,
        )


class Reminder(commands.Cog):
    """Simple persistent reminder system."""

    DEFAULT_REASONS = [
        "I was told to bother you.",
        "do the thing.",
        "past you sent me.",
        "it is time.",
        "beep beep.",
        "reason: ¯\\_(ツ)_/¯",
        "you asked for this.",
        "you have been summoned.",
        "ding.",
        "go go go.",
        "remember something.",
        "time to pretend you remember.",
        "hello yes, reminder.",
        "it is time. for what? idk.",
    ]

    TIME_PATTERN = re.compile(
        r"^(?P<amount>\d+(?:\.\d+)?)"
        r"(?P<unit>"
        r"s|sec|secs|second|seconds|"
        r"m|min|mins|minute|minutes|"
        r"h|hr|hrs|hour|hours|"
        r"d|day|days|"
        r"w|week|weeks"
        r")$",
        re.IGNORECASE,
    )

    UNIT_SECONDS = {
        "s": 1,
        "sec": 1,
        "secs": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "minute": 60,
        "minutes": 60,
        "h": 60 * 60,
        "hr": 60 * 60,
        "hrs": 60 * 60,
        "hour": 60 * 60,
        "hours": 60 * 60,
        "d": 60 * 60 * 24,
        "day": 60 * 60 * 24,
        "days": 60 * 60 * 24,
        "w": 60 * 60 * 24 * 7,
        "week": 60 * 60 * 24 * 7,
        "weeks": 60 * 60 * 24 * 7,
    }

    MAX_REMINDER_SECONDS = 365 * 24 * 60 * 60

    def __init__(self, bot):
        self.bot = bot

        self.config = Config.get_conf(
            self,
            identifier=928374650192837,
        )

        self.config.register_global(
            reminders={}
        )

        self._reminder_cache: dict[str, dict] = {}
        self.reminder_tasks: dict[str, asyncio.Task] = {}

    async def cog_load(self):
        reminders = await self.config.reminders()
        self._reminder_cache = dict(reminders)

        now = time.time()

        for reminder_id, reminder in self._reminder_cache.items():
            state = reminder.get("state", "waiting")

            # Migrate older reminders to the new title field.
            if "title" not in reminder:
                reminder["title"] = reminder.get("reason")
                self._reminder_cache[reminder_id] = reminder

            if state == "fired":
                message_id = reminder.get("reminder_message_id")
                if message_id:
                    self._register_persistent_view(
                        reminder_id,
                        message_id,
                    )
                continue

            # Waiting reminders can have a creation confirmation
            # message. Restore its Cancel/x buttons after restart.
            confirmation_message_id = reminder.get(
                "confirmation_message_id"
            )
            if confirmation_message_id:
                self._register_persistent_notice_view(
                    reminder_id,
                    confirmation_message_id,
                )

            due_at = reminder["due_at"]

            if due_at <= now:
                task = asyncio.create_task(
                    self._deliver_reminder(reminder_id)
                )
            else:
                task = asyncio.create_task(
                    self._wait_for_reminder(reminder_id)
                )

            self.reminder_tasks[reminder_id] = task

    async def cog_unload(self):
        for task in self.reminder_tasks.values():
            task.cancel()
        self.reminder_tasks.clear()

    def _register_persistent_view(
        self,
        reminder_id: str,
        message_id: int,
    ):
        view = ReminderView(self, reminder_id)
        try:
            self.bot.add_view(view, message_id=message_id)
        except (ValueError, TypeError):
            self.bot.logger.exception(
                "Failed to register reminder view %s",
                reminder_id,
            )

    def _register_persistent_notice_view(
        self,
        reminder_id: str,
        message_id: int,
    ):
        view = ReminderNoticeView(self, reminder_id)
        try:
            self.bot.add_view(view, message_id=message_id)
        except (ValueError, TypeError):
            self.bot.logger.exception(
                "Failed to register reminder notice view %s",
                reminder_id,
            )

    def _parse_time(self, value: str) -> Optional[float]:
        match = self.TIME_PATTERN.fullmatch(value.strip())

        if not match:
            return None

        amount = float(match.group("amount"))
        unit = match.group("unit").lower()

        return amount * self.UNIT_SECONDS[unit]

    def _make_reason(self, reason: Optional[str]) -> str:
        if reason:
            return reason.rstrip(".") + "."

        return random.choice(self.DEFAULT_REASONS)

    def get_notice_content(self, reminder_id: str) -> str:
        reminder = self._reminder_cache.get(reminder_id)

        if reminder is None:
            return "Reminder."

        timestamp = int(reminder["due_at"])
        title = reminder.get("title") or ""

        if title:
            return f"See you <t:{timestamp}:R>! {title}"
        return f"See you <t:{timestamp}:R>!"

    def get_reminder_content(self, reminder_id: str) -> str:
        reminder = self._reminder_cache.get(reminder_id)

        if reminder is None:
            return "Reminder."

        title = reminder.get("title")

        if title:
            return f"<@{reminder['user_id']}>, {title}"
        return (
            f"<@{reminder['user_id']}>, "
            f"{self._make_reason(reminder.get('reason'))}"
        )

    def get_owned_reminder_ids(self, user_id: int) -> list[str]:
        return [
            reminder_id
            for reminder_id, reminder in sorted(
                self._reminder_cache.items(),
                key=lambda item: item[1].get("due_at", 0),
            )
            if reminder.get("user_id") == user_id
        ]

    def get_reminder_number(self, user_id: int, reminder_id: str) -> int:
        ids = self.get_owned_reminder_ids(user_id)

        try:
            return ids.index(reminder_id) + 1
        except ValueError:
            return 1

    async def _save_reminder(
        self,
        reminder_id: str,
        reminder: dict,
    ):
        self._reminder_cache[reminder_id] = reminder

        async with self.config.reminders() as reminders:
            reminders[reminder_id] = reminder

    async def _delete_reminder(self, reminder_id: str):
        self._reminder_cache.pop(reminder_id, None)

        async with self.config.reminders() as reminders:
            reminders.pop(reminder_id, None)

    async def _delete_message(
        self,
        channel_id: int,
        message_id: Optional[int],
    ):
        if not message_id:
            return

        channel = self.bot.get_channel(channel_id)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                return

        try:
            await channel.get_partial_message(message_id).delete()
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass

    async def _wait_for_reminder(self, reminder_id: str):
        try:
            reminder = self._reminder_cache.get(reminder_id)

            if reminder is None:
                return

            if reminder.get("state", "waiting") != "waiting":
                return

            delay = max(
                0,
                reminder["due_at"] - time.time(),
            )

            await asyncio.sleep(delay)
            await self._deliver_reminder(reminder_id)

        except asyncio.CancelledError:
            raise

        except Exception:
            self.bot.logger.exception(
                "Reminder task failed: %s",
                reminder_id,
            )

        finally:
            self.reminder_tasks.pop(reminder_id, None)

    async def _deliver_reminder(self, reminder_id: str):
        reminder = self._reminder_cache.get(reminder_id)

        if reminder is None:
            return

        if reminder.get("state", "waiting") != "waiting":
            return

        reminder["state"] = "fired"
        reminder["reminder_message_id"] = None

        await self._save_reminder(
            reminder_id,
            reminder,
        )

        # The creation notice is no longer needed once the actual
        # reminder fires.
        await self._delete_message(
            reminder["channel_id"],
            reminder.get("confirmation_message_id"),
        )
        reminder["confirmation_message_id"] = None
        await self._save_reminder(
            reminder_id,
            reminder,
        )

        channel = self.bot.get_channel(reminder["channel_id"])

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(
                    reminder["channel_id"]
                )
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                self.bot.logger.exception(
                    "Could not access channel for reminder %s",
                    reminder_id,
                )
                return

        view = ReminderView(self, reminder_id)

        try:
            sent_message = await channel.send(
                view=view,
                reference=discord.MessageReference(
                    message_id=reminder["command_message_id"],
                    channel_id=reminder["channel_id"],
                    guild_id=reminder.get("guild_id"),
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                ),
            )
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            self.bot.logger.exception(
                "Failed to send reminder %s",
                reminder_id,
            )
            return

        reminder["reminder_message_id"] = sent_message.id

        await self._save_reminder(
            reminder_id,
            reminder,
        )

        self._register_persistent_view(
            reminder_id,
            sent_message.id,
        )

    async def handle_cancel(
        self,
        interaction: discord.Interaction,
        reminder_id: str,
    ):
        reminder = self._reminder_cache.get(reminder_id)

        if reminder is None:
            await interaction.response.send_message(
                "that reminder no longer exists.",
                ephemeral=True,
            )
            return

        if interaction.user.id != reminder["user_id"]:
            await interaction.response.send_message(
                "that isn't your reminder.",
                ephemeral=True,
            )
            return

        task = self.reminder_tasks.pop(reminder_id, None)
        if task and not task.done():
            task.cancel()

        await self._delete_message(
            reminder["channel_id"],
            reminder.get("reminder_message_id"),
        )

        await self._delete_reminder(reminder_id)

        try:
            await interaction.response.defer()
            await interaction.message.delete()
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass

    async def handle_close(
        self,
        interaction: discord.Interaction,
        reminder_id: str,
    ):
        reminder = self._reminder_cache.get(reminder_id)

        if reminder is None:
            await interaction.response.send_message(
                "that reminder no longer exists.",
                ephemeral=True,
            )
            return

        if interaction.user.id != reminder["user_id"]:
            await interaction.response.send_message(
                "that isn't your reminder.",
                ephemeral=True,
            )
            return

        reminder["confirmation_message_id"] = None
        await self._save_reminder(
            reminder_id,
            reminder,
        )

        try:
            await interaction.response.defer()
            await interaction.message.delete()
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass

    async def handle_repeat(
        self,
        interaction: discord.Interaction,
        reminder_id: str,
    ):
        reminder = self._reminder_cache.get(reminder_id)

        if reminder is None:
            await interaction.response.send_message(
                "that reminder no longer exists.",
                ephemeral=True,
            )
            return

        if interaction.user.id != reminder["user_id"]:
            await interaction.response.send_message(
                "that isn't your reminder.",
                ephemeral=True,
            )
            return

        if reminder.get("state") != "fired":
            await interaction.response.send_message(
                "that reminder isn't ready to be repeated.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            await interaction.message.delete()
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass

        old_task = self.reminder_tasks.pop(
            reminder_id,
            None,
        )

        if old_task and not old_task.done():
            old_task.cancel()

        reminder["state"] = "waiting"
        reminder["reminder_message_id"] = None
        reminder["confirmation_message_id"] = None
        reminder["due_at"] = time.time() + reminder["duration"]

        await self._save_reminder(
            reminder_id,
            reminder,
        )

        task = asyncio.create_task(
            self._wait_for_reminder(reminder_id)
        )
        self.reminder_tasks[reminder_id] = task

        await interaction.followup.send(
            f"reminder repeated for "
            f"{self._format_duration(reminder['duration'])}.",
            ephemeral=True,
        )

    async def _refresh_reminder_ui(self, reminder_id: str):
        reminder = self._reminder_cache.get(reminder_id)

        if reminder is None:
            return

        message_id = (
            reminder.get("reminder_message_id")
            if reminder.get("state") == "fired"
            else reminder.get("confirmation_message_id")
        )

        if not message_id:
            return

        channel = self.bot.get_channel(reminder["channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(
                    reminder["channel_id"]
                )
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                return

        try:
            message = channel.get_partial_message(message_id)

            if reminder.get("state") == "fired":
                await message.edit(
                    view=ReminderView(self, reminder_id)
                )
            else:
                await message.edit(
                    view=ReminderNoticeView(self, reminder_id)
                )
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass

    async def change_time(
        self,
        interaction: discord.Interaction,
        reminder_id: str,
        seconds: float,
    ) -> bool:
        reminder = self._reminder_cache.get(reminder_id)

        if reminder is None:
            await interaction.response.send_message(
                "that reminder no longer exists.",
                ephemeral=True,
            )
            return False

        if interaction.user.id != reminder["user_id"]:
            await interaction.response.send_message(
                "that isn't your reminder.",
                ephemeral=True,
            )
            return False

        old_task = self.reminder_tasks.pop(
            reminder_id,
            None,
        )
        if old_task and not old_task.done():
            old_task.cancel()

        reminder["due_at"] = time.time() + seconds
        reminder["duration"] = seconds
        reminder["state"] = "waiting"

        # A changed reminder gets a fresh timer. A fired reminder's
        # old message is deleted before changing it.
        await self._delete_message(
            reminder["channel_id"],
            reminder.get("reminder_message_id"),
        )

        reminder["reminder_message_id"] = None

        await self._save_reminder(
            reminder_id,
            reminder,
        )

        if not reminder.get("confirmation_message_id"):
            channel = self.bot.get_channel(reminder["channel_id"])

            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(
                        reminder["channel_id"]
                    )
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ):
                    channel = None

            if channel is not None:
                try:
                    notice = await channel.send(
                        view=ReminderNoticeView(
                            self,
                            reminder_id,
                        )
                    )
                    reminder["confirmation_message_id"] = notice.id
                    await self._save_reminder(
                        reminder_id,
                        reminder,
                    )
                    self._register_persistent_notice_view(
                        reminder_id,
                        notice.id,
                    )
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ):
                    pass
        else:
            await self._refresh_reminder_ui(reminder_id)

        self.reminder_tasks[reminder_id] = asyncio.create_task(
            self._wait_for_reminder(reminder_id)
        )

        return True

    async def handle_delete_one(
        self,
        interaction: discord.Interaction,
        reminder_id: str,
    ):
        reminder = self._reminder_cache.get(reminder_id)

        if reminder is None:
            await interaction.response.send_message(
                "that reminder no longer exists.",
                ephemeral=True,
            )
            return

        if interaction.user.id != reminder["user_id"]:
            await interaction.response.send_message(
                "that isn't your reminder.",
                ephemeral=True,
            )
            return

        task = self.reminder_tasks.pop(reminder_id, None)
        if task and not task.done():
            task.cancel()

        await self._delete_message(
            reminder["channel_id"],
            reminder.get("reminder_message_id"),
        )
        await self._delete_message(
            reminder["channel_id"],
            reminder.get("confirmation_message_id"),
        )

        await self._delete_reminder(reminder_id)

        await interaction.response.send_message(
            "reminder deleted.",
            ephemeral=True,
        )

    def _format_duration(self, seconds: float) -> str:
        seconds = int(seconds)

        weeks, seconds = divmod(
            seconds,
            7 * 24 * 60 * 60,
        )
        days, seconds = divmod(
            seconds,
            24 * 60 * 60,
        )
        hours, seconds = divmod(
            seconds,
            60 * 60,
        )
        minutes, seconds = divmod(
            seconds,
            60,
        )

        parts = []

        if weeks:
            parts.append(
                f"{weeks} week"
                f"{'s' if weeks != 1 else ''}"
            )
        if days:
            parts.append(
                f"{days} day"
                f"{'s' if days != 1 else ''}"
            )
        if hours:
            parts.append(
                f"{hours} hour"
                f"{'s' if hours != 1 else ''}"
            )
        if minutes:
            parts.append(
                f"{minutes} minute"
                f"{'s' if minutes != 1 else ''}"
            )
        if seconds:
            parts.append(
                f"{seconds} second"
                f"{'s' if seconds != 1 else ''}"
            )

        return ", ".join(parts) or "0 seconds"

    @commands.command(name="remind")
    @commands.guild_only()
    async def remind(
        self,
        ctx: commands.Context,
        duration: Optional[str] = None,
        *,
        reason: Optional[str] = None,
    ):
        """
        Set, list, or delete reminders.

        Examples:
            ..remind 12m
            ..remind 7d Collect Collection Rewards
            ..remind list
            ..remind delete
        """

        # ---------------------------------
        # LIST
        # ---------------------------------

        if duration and duration.lower() == "list":
            view = ReminderListView(
                self,
                ctx.author.id,
            )

            await ctx.send(
                view=view,
            )

            try:
                await ctx.message.delete()
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                pass

            return

        # ---------------------------------
        # DELETE ALL
        # ---------------------------------

        if duration and duration.lower() == "delete":
            owned_reminders = {
                reminder_id: reminder
                for reminder_id, reminder
                in self._reminder_cache.items()
                if reminder["user_id"] == ctx.author.id
            }

            if not owned_reminders:
                await ctx.send(
                    "you don't have any reminders."
                )
                return

            deleted = 0

            for reminder_id, reminder in owned_reminders.items():
                task = self.reminder_tasks.pop(
                    reminder_id,
                    None,
                )

                if task and not task.done():
                    task.cancel()

                await self._delete_message(
                    reminder["channel_id"],
                    reminder.get("reminder_message_id"),
                )
                await self._delete_message(
                    reminder["channel_id"],
                    reminder.get("confirmation_message_id"),
                )

                await self._delete_reminder(reminder_id)
                deleted += 1

            await ctx.send(
                f"deleted {deleted} reminder"
                f"{'s' if deleted != 1 else ''}."
            )
            return

        # ---------------------------------
        # CREATE
        # ---------------------------------

        if not duration:
            await ctx.send(
                "use `..remind <time> [title]`, "
                "`..remind list`, or `..remind delete`."
            )
            return

        seconds = self._parse_time(duration)

        if seconds is None:
            await ctx.send(
                "use a time like `30s`, `12m`, "
                "`2h`, `7d`, or `1w`."
            )
            return

        if seconds <= 0:
            await ctx.send(
                "the reminder time has to be greater than 0."
            )
            return

        if seconds > self.MAX_REMINDER_SECONDS:
            await ctx.send(
                "the maximum reminder time is 365 days."
            )
            return

        reminder_id = str(ctx.message.id)
        title = reason.strip() if reason else None

        reminder = {
            "user_id": ctx.author.id,
            "guild_id": ctx.guild.id,
            "channel_id": ctx.channel.id,
            "command_message_id": ctx.message.id,
            "reminder_message_id": None,
            "confirmation_message_id": None,
            "duration": seconds,
            "due_at": time.time() + seconds,
            "reason": None,
            "title": title,
            "state": "waiting",
        }

        await self._save_reminder(
            reminder_id,
            reminder,
        )

        # The user's command is removed, then the clean V2
        # confirmation replaces it.
        try:
            await ctx.message.delete()
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass

        notice = ReminderNoticeView(
            self,
            reminder_id,
        )

        try:
            sent_message = await ctx.send(
                view=notice,
            )
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            await self._delete_reminder(reminder_id)
            raise

        reminder["confirmation_message_id"] = sent_message.id
        await self._save_reminder(
            reminder_id,
            reminder,
        )

        self._register_persistent_notice_view(
            reminder_id,
            sent_message.id,
        )

        task = asyncio.create_task(
            self._wait_for_reminder(reminder_id)
        )

        self.reminder_tasks[reminder_id] = task


async def setup(bot):
    await bot.add_cog(
        Reminder(bot)
    )
