from datetime import datetime, timezone

from modules.base import BaseModule, Command
from utils.ui import CORE_COMMANDS, esc, screen


def _ago(ts) -> str:
    if not ts:
        return "never"
    secs = int(datetime.now(timezone.utc).timestamp() - ts)
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{secs // 60} min ago"
    return f"{secs // 3600} h ago"


class StatusModule(BaseModule):
    name = "status"
    description = "Connection status"

    def get_commands(self):
        desc, usage = CORE_COMMANDS["status"]
        return {"status": Command(self.status, desc, usage)}

    async def status(self, args):
        ig = self.ctx.ig
        lines = []
        if ig.logged_in:
            lines.append(f"Instagram: connected as @{esc(ig.username)} ({esc(ig.auth.login_method)})")
        else:
            lines.append("Instagram: not connected. Use /connect.")
            if ig.last_alert:
                lines.append(esc(ig.last_alert))
        watcher = self.ctx.modules.get("watcher") if self.ctx.modules else None
        if watcher is not None:
            if not self.ctx.modules.is_enabled(watcher):
                lines.append("Watchlist: off")
            else:
                h = watcher.health()
                paused = f", {h['paused']} paused" if h["paused"] else ""
                lines.append(f"Watchlist: {h['accounts']} account(s){paused}, last check {_ago(h['last_check'])}")
                for _when, user, text in h["errors"][-2:]:
                    lines.append(f"@{esc(user)}: {esc(text)}")
        return screen("Status", "\n".join(lines))
