import asyncio
import re

from telegram import BotCommand, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from core.context import AppContext, Tg
from core.instagram import InstagramClient
from core.module_manager import ModuleManager
from utils.db import ScopedStore
from utils.logger import get_logger
from utils.prefs import PACES, Prefs
from utils.ui import BLUE, CORE_COMMANDS, RED, bad, btn, esc, kb, onoff, screen

log = get_logger("bot")

USERS_KEY = "users"
WIPE_KEYS = ("session", "session_meta", "prefs", "watchlist")
USERNAME_RE = re.compile(r"[A-Za-z0-9._]{1,30}")
MENU_ORDER = ("start", "help", "status", "watchlist", "settings", "connect", "logout")

INTRO = (
    "<b>👋 Welcome!</b>\n\n"
    "This bot is built to download and retrieve content from social media and music platforms. "
    "Just send a link and the bot will automatically detect the service. 🚀\n\n"
    "✨ Send your link — let the bot handle the rest. /help"
)


class UserSession:
    def __init__(self, bot_app: "FetchIGBot", user_id: int):
        self.user_id = user_id
        cfg = bot_app.cfg
        self.store = ScopedStore(bot_app.root_store, f"u{user_id}_")
        self.ig = InstagramClient(cfg, self.store)
        self.prefs = Prefs(self.store)
        tg = Tg(bot_app.app.bot, user_id, cfg.max_media_mb * 1_000_000, cfg.ig_proxy, cfg.ig_tls_verify)
        self.ctx = AppContext(cfg=cfg, ig=self.ig, store=self.store, tg=tg, prefs=self.prefs)
        self.modules = ModuleManager(self.ctx)
        self.ctx.modules = self.modules
        self.modules.load_modules()
        self.awaiting: dict | None = None
        self.started = False
        self.login_task: asyncio.Task | None = None
        self.ig.on_alert = self._tell

    async def _tell(self, text: str) -> None:
        try:
            await self.ctx.tg.bot.send_message(self.user_id, text)
        except TelegramError:
            log.info("Could not message user %s", self.user_id)

    async def start(self) -> None:
        if not self.started:
            self.started = True
            await self.modules.start_all()

    async def stop(self) -> None:
        if self.started:
            self.started = False
            await self.modules.stop_all()
        await self.ig.stop()


class FetchIGBot:
    def __init__(self, cfg, root_store):
        self.cfg = cfg
        self.root_store = root_store
        self.sessions: dict[int, UserSession] = {}
        self.app: Application | None = None
        self._lock = asyncio.Lock()

    def build(self) -> Application:
        self.app = (
            Application.builder().token(self.cfg.tg_token).concurrent_updates(True)
            .post_init(self._post_init).post_shutdown(self._post_shutdown).build()
        )
        self.app.add_handler(CallbackQueryHandler(self.on_callback))
        self.app.add_handler(MessageHandler(filters.COMMAND, self.on_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        return self.app

    def _menu_commands(self) -> list[BotCommand]:
        probe = ModuleManager(AppContext(cfg=self.cfg, ig=None, store=None))
        probe.load_modules()
        described = {name: desc for name, (desc, _usage) in CORE_COMMANDS.items()}
        for name, (command, _module) in probe.all_commands().items():
            described.setdefault(name, command.description)
        described.pop("cancel", None)
        ordered = [n for n in MENU_ORDER if n in described] + [n for n in described if n not in MENU_ORDER]
        return [BotCommand(n, described[n][:256]) for n in ordered]

    async def _post_init(self, app: Application) -> None:
        try:
            await app.bot.set_my_commands(self._menu_commands())
        except Exception:
            log.exception("Could not publish the command menu")
        for uid in await self.root_store.get(USERS_KEY, []) or []:
            try:
                sess = await self.session(int(uid))
                if await sess.ig.restore_saved_session():
                    await sess.start()
                    log.info("Restored the session of user %s", uid)
            except Exception:
                log.exception("Could not restore user %s", uid)

    async def _post_shutdown(self, app: Application) -> None:
        for sess in list(self.sessions.values()):
            try:
                await sess.stop()
            except Exception:
                log.exception("Error stopping a session")

    async def session(self, user_id: int) -> UserSession:
        async with self._lock:
            sess = self.sessions.get(user_id)
            if sess is None:
                sess = UserSession(self, user_id)
                await sess.prefs.load()
                self.sessions[user_id] = sess
                users = await self.root_store.get(USERS_KEY, []) or []
                if user_id not in users:
                    await self.root_store.set(USERS_KEY, users + [user_id])
            return sess

    @staticmethod
    def _private(update: Update) -> bool:
        chat = update.effective_chat
        return bool(chat and chat.type == "private" and update.effective_user)

    @staticmethod
    async def _reply(message, text: str, markup=None):
        return await message.reply_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)

    @staticmethod
    async def _show(query, text: str, markup=None) -> None:
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        except TelegramError:
            pass

    @staticmethod
    async def _edit(bot, chat_id: int, message_id: int, text: str, markup=None) -> None:
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode="HTML",
                                        reply_markup=markup, disable_web_page_preview=True)
        except TelegramError:
            pass

    async def _forget_message(self, update: Update) -> None:
        try:
            await update.effective_message.delete()
        except TelegramError:
            pass

    @staticmethod
    def clear_pending(sess: UserSession, chat_id: int) -> bool:
        had = sess.awaiting is not None
        sess.awaiting = None
        return sess.modules.cancel_pending(chat_id) or had

    async def on_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._private(update):
            return
        message = update.effective_message
        head, *args = (message.text or "").split()
        name = head[1:].split("@")[0].lower()
        sess = await self.session(update.effective_user.id)
        pending = self.clear_pending(sess, message.chat_id)

        if name == "start":
            await self._reply(message, *self.home_view())
        elif name == "cancel":
            await self._reply(message, "Cancelled." if pending else "Nothing to cancel.")
        elif name == "connect":
            if self.login_running(sess):
                await self._reply(message, bad("A login is already in progress."))
            else:
                await self._reply(message, *self.connect_view(sess))
        elif name == "logout":
            await self._reply(message, *self.logout_view())
        elif name == "settings":
            await self._reply(message, *self.settings_view(sess))
        else:
            found = sess.modules.all_commands().get(name)
            if not found:
                await self._reply(message, bad("Unknown command. Use /help to see what I can do."))
                return
            command, module = found
            if not sess.modules.is_enabled(module):
                await self._reply(message, bad("That feature is switched off. Turn it on in /settings, Features."))
                return
            try:
                if command.takes_update:
                    await command.handler(args, update)
                else:
                    reply = await command.handler(args)
                    if reply:
                        await self._reply(message, reply)
            except Exception:
                log.exception("Command /%s failed", name)
                await self._reply(message, bad("Something went wrong. Try again in a moment."))

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._private(update):
            return
        message = update.effective_message
        text = (message.text or "").strip()
        sess = await self.session(update.effective_user.id)

        if sess.ig.auth.prompter.waiting:
            if sess.ig.auth.prompter.submit(text):
                await self._forget_message(update)
            return
        if sess.awaiting:
            await self.connect_step(sess, update, text)
            return
        if not await sess.modules.handle_text(text, update):
            await self._reply(message, "Send an Instagram link or a username, or open /help.")

    @staticmethod
    def home_view() -> tuple[str, InlineKeyboardMarkup]:
        return INTRO, kb([btn("Status", "nav:status", RED), btn("Watchlist", "m:watch:ls:h", BLUE)], [btn("Connect", "nav:connect")])

    def status_view_markup(self) -> InlineKeyboardMarkup:
        return kb([btn("Back", "nav:start")])

    def connect_view(self, sess: UserSession) -> tuple[str, InlineKeyboardMarkup]:
        head = f"Connected as @{esc(sess.ig.username)}. Connecting again replaces it.\n\n" if sess.ig.logged_in else ""
        body = (
            head + "Choose how to connect.\n\n"
            "<b>Cookie</b>: paste the sessionid cookie from instagram.com in a browser where you are "
            "logged in. Quick, but Instagram can reject a browser cookie sooner.\n\n"
            "<b>Password</b>: your username and password (2FA supported). The password is used once and never saved; "
            "the session is kept and reused."
        )
        return screen("Connect Instagram", body), kb([btn("Cookie", "cn:cookie"), btn("Password", "cn:pass")], [btn("Cancel", "cn:no")])

    @staticmethod
    def login_running(sess: UserSession) -> bool:
        return bool(sess.login_task and not sess.login_task.done())

    async def connect_step(self, sess: UserSession, update: Update, text: str) -> None:
        message, aw = update.effective_message, sess.awaiting
        chat_id, prompt, bot = message.chat_id, aw["msg"], update.get_bot()
        cancel = kb([btn("Cancel", "cn:no")])
        if text.lower() in ("cancel", "stop"):
            sess.awaiting = None
            await self._forget_message(update)
            await self._edit(bot, chat_id, prompt, *self.home_view())
            return
        step = aw["step"]
        if step == "cookie":
            sess.awaiting = None
            await self._forget_message(update)
            await self._run_login(sess, bot, chat_id, prompt, sess.ig.login_with_cookie(text))
        elif step == "username":
            user = text.lstrip("@").strip()
            await self._forget_message(update)
            if not USERNAME_RE.fullmatch(user):
                await self._edit(bot, chat_id, prompt,
                                 screen("Connect with password", bad("That is not a valid username.") + "\nSend it again."), cancel)
                return
            sess.awaiting = {"step": "password", "username": user, "msg": prompt}
            await self._edit(bot, chat_id, prompt,
                             screen("Connect with password", f"Username: @{esc(user)}\n\nNow send the password. Your message is deleted right after."),
                             cancel)
        elif step == "password":
            user = aw["username"]
            sess.awaiting = None
            await self._forget_message(update)
            await self._run_login(sess, bot, chat_id, prompt, sess.ig.login_with_password(user, text))

    async def _run_login(self, sess: UserSession, bot, chat_id: int, prompt: int, coro) -> None:
        await self._edit(bot, chat_id, prompt, screen("Connecting", "⏳ Talking to Instagram. This can take a minute."))

        async def job():
            try:
                ok, text = await coro
            except Exception:
                log.exception("Login crashed")
                ok, text = False, "Login failed unexpectedly. Try again."
            if ok:
                await sess.start()
                await self._edit(bot, chat_id, prompt, screen("Connected", f"✅ {esc(text)}"), self.home_view()[1])
            else:
                await self._edit(bot, chat_id, prompt, screen("Connection failed", bad(esc(text))),
                                 kb([btn("Try again", "nav:connect")], [btn("Back", "nav:start")]))

        sess.login_task = asyncio.create_task(job())

    def settings_view(self, sess: UserSession) -> tuple[str, InlineKeyboardMarkup]:
        ig, prefs = sess.ig, sess.prefs
        pace = str(prefs.get("pace")).title()
        audio = prefs.get("dl_audio")
        body = "\n".join([
            f"Account: {'@' + esc(ig.username) if ig.logged_in else 'not connected'}",
            f"Audio button: {onoff(audio)} (adds a button under downloaded Reels)",
            f"Watchlist pace: {pace} (Safe checks less often, Fast more often)",
            "Files up to 50 MB can be sent.",
        ])
        rows = [
            [btn("Watchlist", "m:watch:ls:s"), btn("Features", "nav:features")],
            [btn(f"Audio button: {onoff(audio)}", "set:audio"), btn(f"Pace: {pace}", "set:pace")],
            [btn("Account", "nav:account")],
            [btn("Back", "nav:start")],
        ]
        return screen("Settings", body), kb(*rows)

    def features_view(self, sess: UserSession) -> tuple[str, InlineKeyboardMarkup]:
        rows, lines = [], []
        for m in sess.modules.modules:
            if getattr(m, "toggleable", False):
                on = sess.modules.is_enabled(m)
                lines.append(f"{esc(m.label)}: {onoff(on)}\n{esc(m.description)}")
                rows.append([btn(f"{m.label}: {onoff(on)}", f"ft:{m.name}")])
        rows.append([btn("Back", "nav:settings")])
        return screen("Features", "Switch a feature off to hide its commands.\n\n" + "\n\n".join(lines)), kb(*rows)

    def account_view(self, sess: UserSession) -> tuple[str, InlineKeyboardMarkup]:
        ig = sess.ig
        if ig.logged_in:
            body = f"Connected as @{esc(ig.username)} ({esc(ig.auth.login_method)})."
            rows = [[btn("Reconnect", "nav:connect"), btn("Disconnect", "nav:logout")]]
        else:
            body = "Not connected."
            rows = [[btn("Connect", "nav:connect")]]
        rows.append([btn("Back", "nav:settings")])
        return screen("Account", body), kb(*rows)

    @staticmethod
    def logout_view() -> tuple[str, InlineKeyboardMarkup]:
        return (
            screen("Disconnect", "This signs out of Instagram and deletes your saved login, settings and watchlist."),
            kb([btn("Yes, disconnect", "lo:yes"), btn("Cancel", "nav:account")]),
        )

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not query.message or query.message.chat.type != "private":
            return
        sess = await self.session(query.from_user.id)
        data = query.data or ""
        message = query.message

        if data.startswith("m:"):
            _, prefix, rest = (data.split(":", 2) + ["", ""])[:3]
            found = sess.modules.all_callbacks().get(prefix)
            if found and sess.modules.is_enabled(found[1]):
                await query.answer()
                await found[0](rest, query, context)
            elif found:
                await query.answer("That feature is switched off. Turn it on in Settings, Features.", show_alert=True)
            else:
                await query.answer()
            return

        if data == "nav:connect" and self.login_running(sess):
            await query.answer("A login is already in progress.", show_alert=True)
            return

        await query.answer()
        if data == "nav:start":
            await self._show(query, *self.home_view())
        elif data == "nav:status":
            module = sess.modules.get("status")
            text = await module.status([]) if module else bad("Status is unavailable.")
            await self._show(query, text, self.status_view_markup())
        elif data == "nav:settings":
            await self._show(query, *self.settings_view(sess))
        elif data == "nav:features":
            await self._show(query, *self.features_view(sess))
        elif data == "nav:account":
            await self._show(query, *self.account_view(sess))
        elif data == "nav:connect":
            self.clear_pending(sess, message.chat_id)
            await self._show(query, *self.connect_view(sess))
        elif data == "nav:logout":
            await self._show(query, *self.logout_view())
        elif data == "lo:yes":
            await self.wipe(sess)
            await self._show(query, screen("Disconnected", "Your login, settings and watchlist were deleted."),
                             kb([btn("Connect", "nav:connect")]))
        elif data == "set:audio":
            await sess.prefs.set("dl_audio", not sess.prefs.get("dl_audio"))
            await self._show(query, *self.settings_view(sess))
        elif data == "set:pace":
            order = list(PACES)
            current = sess.prefs.get("pace")
            nxt = order[(order.index(current) + 1) % len(order)] if current in order else order[0]
            await sess.prefs.set("pace", nxt)
            await self._show(query, *self.settings_view(sess))
        elif data.startswith("ft:"):
            module = sess.modules.get(data[3:])
            if module and getattr(module, "toggleable", False):
                await sess.prefs.set_feature(module.name, not sess.modules.is_enabled(module))
            await self._show(query, *self.features_view(sess))
        elif data == "cn:no":
            sess.awaiting = None
            await self._show(query, *self.home_view())
        elif data == "cn:cookie":
            sess.awaiting = {"step": "cookie", "msg": message.message_id}
            await self._show(
                query,
                screen("Connect with cookie",
                       "Send the sessionid cookie value.\n\n"
                       "In a browser where you are logged in to instagram.com, open the developer tools, go to "
                       "Application (or Storage), Cookies, instagram.com, and copy the value of sessionid. "
                       "Your message is deleted right after."),
                kb([btn("Cancel", "cn:no")]),
            )
        elif data == "cn:pass":
            sess.awaiting = {"step": "username", "msg": message.message_id}
            await self._show(query, screen("Connect with password", "Send your Instagram username."), kb([btn("Cancel", "cn:no")]))

    async def wipe(self, sess: UserSession) -> None:
        if sess.login_task and not sess.login_task.done():
            sess.login_task.cancel()
        sess.awaiting = None
        await sess.stop()
        await sess.ig.logout()
        for key in WIPE_KEYS:
            await sess.store.set(key, None)
        async with self._lock:
            self.sessions.pop(sess.user_id, None)
            users = await self.root_store.get(USERS_KEY, []) or []
            await self.root_store.set(USERS_KEY, [u for u in users if u != sess.user_id])
