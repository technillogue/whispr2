#!/usr/bin/python3.9
# Copyright (c) 2021 MobileCoin Inc.
# Copyright (c) 2021 The Forest Team
import asyncio
import logging
from collections import Counter
from functools import wraps
from pathlib import Path
from typing import Awaitable, Callable, Optional

import mc_util
import phonenumbers as pn
from forest import utils
from forest.core import (
    Message,
    QuestionBot,
    Response,
    UserError,
    requires_admin,
    run_bot,
)
from forest.pdictng import aPersistDict, aPersistDictOfLists


def takes_number(command: Callable) -> Callable:
    @wraps(command)  # keeps original name and docstring for /help
    async def wrapped_command(self: "Whispr", msg: Message) -> str:
        if msg.arg1:
            maybe_number = await self.name_numbers.get(msg.arg1)
            if maybe_number:
                return await command(self, msg, maybe_number)
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


async def chain(*coros: Awaitable) -> None:
    for coro in coros:
        await coro


class Whispr(QuestionBot):
    do_bot_balance = QuestionBot.do_balance

    def __init__(self, bot_number: Optional[str] = None) -> None:
        self.user_names: aPersistDict[str] = aPersistDict("user_names")
        self.name_numbers: aPersistDict[str] = aPersistDict("name_numbers")
        self.followers: aPersistDictOfLists[str] = aPersistDictOfLists("followers")
        self.blocked: aPersistDict[bool] = aPersistDict("blocked")
        self.claimed_airdrop: aPersistDict[bool] = aPersistDict("claimed_airdrop")
        self.follow_price: aPersistDict[int] = aPersistDict("follow_price")
        self.locked: aPersistDict[bool] = aPersistDict("locked")
        super().__init__(bot_number)

    async def start_process(self) -> None:
        await self.admin("\N{deciduous tree}\N{robot face}\N{hiking boot}")
        await super().start_process()

    async def greet(self, recipient: str) -> None:
        await self.user_names.set(recipient, recipient)
        await self.name_numbers.set(recipient, recipient)
        await super().send_message(
            recipient,
            [
                "welcome to whispr, a social media that runs on signal. "
                "text STOP or BLOCK to not receive messages. type /help "
                "to view available commands.",
                "send a 0.01 'tip' to someone. when they claim it, get 0.01 MOB yourself",
            ],
        )
        name = await self.ask_freeform_question(
            recipient, "what would you like to be called?"
        )
        if name in await self.name_numbers.keys():
            await super().send_message(
                recipient,
                f"'{name}' is already taken, use /name to set a different name",
            )
        else:
            await self.user_names.set(recipient, name)
            await self.name_numbers.set(name, recipient)
            await super().send_message(
                recipient, f"other users will now see you as {name}"
            )

    async def send_message(  # pylint: disable=too-many-arguments
        self,
        recipient: Optional[str],
        msg: Response,
        group: Optional[str] = None,  # maybe combine this with recipient?
        endsession: bool = False,
        attachments: Optional[list[str]] = None,
        content: str = "",
        **other_params: str,
    ) -> str:
        if recipient and recipient in await self.blocked.keys():
            logging.debug("recipient % is blocked, not sending", recipient)
            return ""
        ret = await super().send_message(
            recipient, msg, group, endsession, attachments, content, **other_params
        )
        if recipient and recipient not in await self.user_names.keys():
            await self.greet(recipient)
        return ret

    async def handle_message(self, message: Message) -> Response:
        if message.text and message.text.lower() in ("stop", "block"):
            await self.blocked.set(message.source, True)
            return "i'll stop messaging you. text START or UNBLOCK to resume texts"
        if message.text and message.text.lower() in ("start", "unblock"):
            if await self.blocked.pop(message.source, default=False):
                return "welcome back"
            return "you weren't blocked"
        return await super().handle_message(message)

    async def default(self, message: Message) -> None:
        """send a message to your followers"""
        logging.info(message)
        if not message.source or (not message.full_text and not message.attachments):
            logging.debug(
                "no message source %s or not message text %s",
                message.source,
                message.text,
            )
        elif message.source not in await self.user_names.keys():
            await self.send_message(message.source, f"{message.text} yourself")
            # ensures they'll get a welcome message
        else:
            name = await self.user_names.get(message.source)
            for follower in await self.followers.get(message.source, []):
                logging.info("sending to follower %s", follower)
                # self.sent_messages[round(time.time())][follower] = message
                if utils.AUXIN:
                    attachments = [
                        str(Path("/tmp") / attach["fileName"])
                        for attach in (message.attachments or [])
                    ]
                else:
                    attachments = [
                        str(Path("attachments") / attach["id"])
                        for attach in (message.attachments or [])
                    ]
                logging.info(attachments)
                await self.send_message(
                    follower, f"{name}: {message.full_text}", attachments=attachments
                )
            await self.send_reaction(message, "\N{Outbox Tray}")

    async def do_help(self, msg: Message) -> Response:
        return (await super().do_help(msg)).lower()  # type: ignore

    async def do_name(self, msg: Message) -> str:
        """/name [name]. set or change your name"""
        name = msg.arg1
        old_name = await self.user_names.get(msg.source, "")
        if not isinstance(name, str):
            return (
                f"missing name argument. usage: /name [name]. your name is {old_name}"
            )
        if name in await self.name_numbers.keys():
            return f"'{name}' is already taken, use /name to set a different name"
        await self.user_names.set(msg.source, name)
        await self.name_numbers.set(name, msg.source)
        return f"other users will now see you as {name}. you used to be {old_name}"

    async def do_set_follow_price(self, msg: Message) -> str:
        "set follow price"
        price = await self.ask_floatable_question(
            msg.source, "how much MOB to follow you?"
        )
        if price is None:
            return "okay, never mind"
        await self.follow_price.set(msg.source, mc_util.mob2pmob(price))
        return f"it now costs {price} to follow you"

    @takes_number
    async def do_follow(self, msg: Message, target_number: str) -> str:
        """/follow [number or name]. follow someone"""
        if msg.source not in await self.followers.get(target_number, []):
            price = await self.follow_price.get(target_number, 0)
            if price:
                balance = await self.get_user_pmob_balance(msg.source)
                if price > balance:
                    return f"following costs {mc_util.pmob2mob(price)} MOB"
                price_usd = await self.mobster.pmob2usd(price)
                await self.mobster.ledger_manager.put_pmob_tx(
                    msg.source, -price_usd, -price, f"follow {target_number}"
                )
                await self.send_message(
                    target_number,
                    "sending you a payment from {msg.source} for following you",
                )
                asyncio.create_task(
                    chain(
                        self.send_typing(recipient=target_number),
                        self.send_payment(
                            target_number,
                            price - mc_util.FEE_PMOB,
                            f"{msg.source} followed you",
                        ),
                        self.send_typing(recipient=target_number, stop=True),
                    )
                )
            name = await self.user_names.get(msg.source, msg.name or msg.source)
            await self.send_message(target_number, f"{name} has followed you")
            await self.followers.extend(target_number, msg.source)
            # offer to follow back?
            return f"followed {msg.arg1}"
        return f"you're already following {msg.arg1}"

    @takes_number
    async def do_invite(self, msg: Message, invitee: str) -> str:
        """
        /invite [number or name]. invite someone to follow you
        """
        inviter = msg.source

        async def follow() -> None:
            name = await self.user_names.get(inviter, msg.name or inviter)
            if await self.ask_yesno_question(
                invitee,
                f"{name} invited you to follow them on whispr. "
                "text (y)es or (n)o/cancel to accept",
            ):
                #
                await self.followers.extend(inviter, invitee)
                await self.send_message(invitee, f"followed {name}")
                await self.send_message(inviter, f"{invitee} followed you")
            else:
                await self.send_message(invitee, f"didn't follow {name}")

        if invitee not in await self.followers.get(inviter, []):
            asyncio.create_task(follow())
            return f"invited {invitee}"
        return f"{invitee} already follows you"

    async def do_followers(self, msg: Message) -> str:
        """/followers. list your followers"""
        followers = [
            await self.user_names.get(number, number)
            for number in await self.followers.get(msg.source, [])
        ]
        if followers:
            return ", ".join(followers)
        return "you don't have any followers"

    async def do_following(self, msg: Message) -> str:
        """/following. list who you follow"""
        followed = [
            await self.user_names.get(number, number)
            for number, followers in await self.followers.items()
            if msg.source in followers
        ]
        if not followed:
            return "you aren't following anyone"
        return ", ".join(followed)

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
        await self.followers.remove_from(target_number, msg.source)
        return f"unfollowed {msg.arg1}"

    @requires_admin
    @takes_number
    async def do_forceinvite(self, msg: Message, target_number: str) -> str:
        if target_number in await self.followers.get(msg.source, []):
            return f"{msg.arg1} is already following you"
        await self.followers.extend(msg.source, target_number)
        await self.send_message(target_number, f"you are now following {msg.source}")
        return f"{msg.arg1} is now following you"

    async def do_lock(self, msg: Message) -> str:
        "don't let people discover you"
        if await self.locked.get(msg.source):
            return "you're already locked"
        await self.locked.set(msg.source, True)
        return "you will no longer show up in recommended accounts to follow"

    async def do_unlock(self, msg: Message) -> str:
        "let people discover you"
        if not await self.locked.get(msg.source):
            return "you weren't locked"
        await self.locked.set(msg.source, False)
        return "you will show up in recommended accounts to follow"

    async def do_recommend(self, msg: Message) -> str:
        user_follows = [
            number
            for number, followers in await self.followers.items()
            if msg.source in followers
        ]
        people_you_follow_follow = [
            await self.user_names.get(number, number)
            for person in user_follows
            for number, followers in await self.followers.items()
            if person in followers
            and number not in user_follows
            and number != msg.source
            and not await self.locked.get(number)
        ]
        # [
        #     (
        #         await self.user_names.get(person, person),
        #         sum(
        #             user_follow in await self.followers.get(person)
        #             for user_follow in user_follows
        #         ),
        #     )
        #     for person in await self.user_names.keys()
        #     if person not in user_follows
        #     and person != msg.source
        #     and not await self.locked.get(person)
        # ]
        if not people_you_follow_follow:
            return "you already follow everyone followed by people you follow"
        return "\n".join(
            f"{name} is followed by {n} people you follow"
            for name, n in Counter(people_you_follow_follow).most_common(n=10)
        )

        # await self.user_names.get(number, number): [
        #     await self.user_names.get(number2, number2)
        #     for number2, followers in await self.followers.items()
        #     if number in followers
        # ]
        # Counter(
        #     await self.user_names.get(number2, number2)
        #     for number, followers in await self.followers.items()
        #     for number2, followers2 in await self.followers.items()
        #     if msg.source in followers and number in follower2
        # )

    # /tip opal 0.1
    # /tip opal -> asks how much or assumes an amount
    # if the person sending the tip and can get an airdrop

    @takes_number
    async def do_tip(self, msg: Message, target_number: str) -> str:
        if not msg.arg2:
            msg.arg2 = await self.ask_floatable_question(
                msg.source, "how much MOB to tip?"
            )
            if not msg.arg2:
                return "okay, never mind"
        if msg.source not in await self.claimed_airdrop.keys():
            # deferred airdrop logic goes here
            pass
        balance = await self.get_user_pmob_balance(msg.source)
        tip = mc_util.mob2pmob(float(msg.arg2))
        if tip > balance:
            return "insufficiant balance"
        tip_usd = await self.mobster.pmob2usd(tip)
        await self.mobster.ledger_manager.put_pmob_tx(
            msg.source, -tip_usd, -tip, f"tip {target_number}"
        )
        await self.mobster.ledger_manager.put_pmob_tx(
            msg.source, tip_usd, tip, f"tip from {target_number}"
        )
        asyncio.create_task(self.send_tip(msg, target_number, tip))
        return "sending a tip"

    async def send_tip(self, msg: Message, target_number: str, amount: int) -> None:
        name = await self.user_names.get(message.source)
        try:
            await self.send_payment(
                target_number,
                amount,
                f"{name} tipped you",
            )
            amount_usd = await self.mobster.pmob2usd(amount)
            await self.mobster.ledger_manager.put_pmob_tx(
                msg.source, -amount_usd, -amount, f"tip {target_number}"
            )
            # person receiving the tip received it, we can send the airdrop to the person tipping
        except UserError:
            await self.send_message(
                target_number,
                (
                    f"{name} is trying to tip you. "
                    "activate payments, and say 'withdraw' to get your tip"
                ),
            )

    async def do_balance(self, msg: Message) -> str:
        "returns your whispr balance in MOB"
        balance_pmob = await self.get_user_pmob_balance(msg.source)
        balance_msg = (
            f"your current balance is {mc_util.pmob2mob(balance_pmob).normalize()} MOB"
        )
        if balance_pmob == 0:
            balance_msg += "\n\nsend whipsr some mobilecoin to follow paid accounts or tip"
        return balance_msg

    async def do_withdraw(self, msg: Message) -> str:
        balance = await self.get_user_pmob_balance(msg.source)
        balance_mob = mc_util.pmob2mob(balance)
        balance_usd = await self.mobster.pmob2usd(balance)
        await self.respond(msg, f"sending you {balance_mob} MOB")
        await self.send_typing(msg)
        await self.send_payment(msg.source, balance, "withdraw")
        await self.mobster.ledger_manager.put_pmob_tx(
            msg.source, -balance_usd, -balance, "withdraw"
        )
        # check if the person withdrawing received a tip from someone who hasn't received an airdrop yet
        # if so, we want to credit/send the person who sent that tip,
        # now that the person receiving the tip got money
        await self.send_typing(msg, stop=True)
        return "sent you your MOB!"


if __name__ == "__main__":
    run_bot(Whispr)
