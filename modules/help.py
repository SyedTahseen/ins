from modules.base import BaseModule, Command
from utils.ui import CORE_COMMANDS, esc, screen


class HelpModule(BaseModule):
    name = "help"
    description = "Command list"

    def get_commands(self):
        return {"help": Command(self.help, CORE_COMMANDS["help"][0], CORE_COMMANDS["help"][1])}

    async def help(self, args):
        manager = self.ctx.modules
        commands = manager.all_commands()
        if args:
            name = args[0].lstrip("/").lower()
            if name in CORE_COMMANDS:
                desc, usage = CORE_COMMANDS[name]
            elif name in commands:
                cmd, _module = commands[name]
                desc, usage = cmd.description, cmd.usage or f"/{name}"
            else:
                return f"❌ No command named /{esc(name)}."
            return screen(f"/{name}", f"{esc(desc)}\n\nUsage: {esc(usage)}")

        sections = ["<b>Basics</b>\n" + "\n".join(
            f"{esc(usage)} - {esc(desc)}" for desc, usage in CORE_COMMANDS.values()
        )]
        for module in manager.modules:
            own = {n: c for n, (c, m) in commands.items() if m is module and n not in CORE_COMMANDS}
            if own:
                sections.append(f"<b>{esc(module.label or module.name.title())}</b>\n" + "\n".join(
                    f"{esc(c.usage or '/' + n)} - {esc(c.description)}" for n, c in own.items()
                ))
        tip = "Send an Instagram link to download it, or a username to open the profile."
        return screen("Help", "\n\n".join(sections) + f"\n\n{tip}")
