#!/usr/bin/python3.9
# Copyright (c) 2021 MobileCoin Inc.
# Copyright (c) 2021 The Forest Team
import asyncio
import logging
from functools import wraps
from pathlib import Path
from typing import Callable, Optional
import phonenumbers as pn
from forest.core import Message, QuestionBot, Response, requires_admin, run_bot
from forest.pdictng import aPersistDict, aPersistDictOfLists


def takes_number(command: Callable) -> Callable:
    @wraps(command)  # keeps original name and docstring for /help
    async def wrapped_command(self: "QuestionBot", msg: Message) -> str:
        if msg.arg1 in self.user_names.inverse:
            target_number = self.user_names.inverse[msg.arg1]
            return await command(self, msg, target_number)
        try:
            assert msg.arg1
            parsed = pn.parse(msg.arg1, None)
            assert pn.is_valid_number(parsed)
            target_number = pn.format_number(parsed, pn.PhoneNumberFormat.E164)
            return await command(self, msg, target_number)
        except (pn.phonenumberutil.NumberParseException, AssertionError):
            return (
                f"{msg.arg1} doesn't look a valid number or user. "
                "did you include the country code?"
            )

    return wrapped_command


class Whispr(QuestionBot):
    user_names: aPersistDict[str] = aPersistDict("user_names")
    name_numbers: aPersistDict[str] = aPersistDict("name_numbers")
    followers: aPersistDictOfLists[str] = aPersistDictOfLists("followers")
    blocked: aPersistDictOfLists[bool] = aPersistDict("blocked")

    async def greet(self, recipient: str) -> None:
        await self.user_names.set(recipient, recipient)
        await self.name_numbers.set(recipient, recipient)
        await super().send_message(
            recipient,
            "welcome to whispr, a social media that runs on signal. "
            "text STOP or BLOCK to not receive messages. type /help "
            "to view available commands.",
        )
        name = await self.ask_freeform_question("what would you like to be called?")
        if name in await self.name_numbers.keys():
            await super().send_message(
                recipient,
                f"'{name}' is already taken, use /name to set a different name",
            )
        else:
            await self.user_names.set(recipient, name)
            await self.name_numbers.set(name, recipient)
            await super().send_message(f"other users will now see you as {name}")

    async def send_message(  # pylint: disable=too-many-arguments
        self,
        recipient: Optional[str],
        msg: Response,
        group: Optional[str] = None,  # maybe combine this with recipient?
        endsession: bool = False,
        attachments: Optional[list[str]] = None,
        content: str = "",
    ) -> str:
        if not recipient:
            return await super().send_message(
                recipient, msg, group, endsession, attachments, content
            )
        if recipient in self.blocked:
            logging.debug("recipient % is blocked, not sending", recipient)
            return ""
        ret = await super().send_message(
            recipient, msg, group, endsession, attachments, content
        )
        if not group and recipient not in await self.user_names.keys():
            await self.greet(recipient)
        return ret

    async def do_default(self, msg: Message) -> None:
        """send a message to your followers"""
        if msg.source not in await self.user_names.keys():
            self.send_message(msg.source, f"{msg.text} yourself")
            # ensures they'll get a welcome message
        else:
            name = await self.user_names.get(msg.source)
            for follower in await self.followers.get(msg.source):
                # self.sent_messages[round(time.time())][follower] = msg
                attachments = [
                    str(Path("attachments") / attach["id"])
                    for attach in msg.attachments
                ]
                await self.send_message(
                    follower, f"{name}: {msg.text}", attachments=attachments
                )
                await self.send_reaction(msg, "\N{Outbox Tray}")
            # ideally react to the message indicating it was sent?

    @takes_number
    async def do_follow(self, msg: Message, target_number: str) -> str:
        """/follow [number or name]. follow someone"""
        if msg.source not in await self.followers.get(target_number, []):
            # check for payment here
            await self.send_message(
                target_number, f"{msg.source_name} has followed you"
            )
            await self.followers.extend(target_number, msg.source)
            # offer to follow back?
            return f"followed {msg.arg1}"
        return f"you're already following {msg.arg1}"

    @takes_number
    async def do_invite(self, msg: Message, target_number: str) -> str:
        """
        /invite [number or name]. invite someone to follow you
        """

        async def follow() -> None:
            if await self.ask_yesno_question(
                target_number,
                f"{msg.source_name} invited you to follow them on whispr. "
                "text (y)es or (n)o/cancel to accept",
            ):
                await self.followers.extend(target_number, msg.source)
                await self.send_message(target_number, f"followed {msg.source}")
                await self.send_message(msg.source, f"{target_number} followed you")
            else:
                await self.send_message(target_number, f"didn't follow {msg.source}")

        if target_number not in await self.followers.get(msg.source, []):
            asyncio.create_task(follow())
            return f"invited {target_number}"
        return f"you're already following {target_number}"

    async def do_followers(self, msg: Message) -> str:
        """/followers. list your followers"""
        followers = await self.followers.get(msg.source, [])
        if followers:
            return ", ".join(
                await self.user_names.get(number, number) for number in followers
            )
        return "you don't have any followers"

    async def do_following(self, msg: Message) -> str:
        """/following. list who you follow"""
        following = ", ".join(
            await self.user_names.get(number, number)
            for number, followers in self.followers.items()
            if msg.source in followers
        )
        if not following:
            return "you aren't following anyone"
        return following

    @takes_number
    async def do_softblock(self, msg: Message, target_number: str) -> str:
        """/softblock [number or name]. removes someone from your followers"""
        if target_number not in await self.followers.get(msg.source, []):
            return f"{msg.arg1} isn't following you"
        await self.followers.remove_from(msg.source, target_number)
        return f"softblocked {msg.arg1}"

    @takes_number
    async def do_unfollow(self, msg: Message, target_number: str) -> str:
        """/unfollow [target_number or name]. unfollow someone"""
        if msg.source not in await self.followers.get(target_number, []):
            return f"you aren't following {msg.arg1}"
        self.followers.remove_from(target_number, msg.source)
        return f"unfollowed {msg.arg1}"

    @requires_admin
    @takes_number
    async def do_forceinvite(self, msg: Message, target_number: str) -> str:
        if target_number in await self.followers.get(msg.source, []):
            return f"{msg.arg1} is already following you"
        await self.followers.extend(target_number, msg.source)
        await self.send_message(target_number, f"you are now following {msg.source}")
        return f"{msg.arg1} is now following you"


if __name__ == "__main__":
    run_bot(Whispr)
