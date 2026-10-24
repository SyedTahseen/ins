"""Small helpers so the bot survives differences between instagrapi releases.

instagrapi changes signatures between versions (extra/removed keyword arguments, new/removed
attributes). These helpers pass only the arguments the installed version accepts.
"""
import inspect

from utils.logger import get_logger

log = get_logger("compat")


def accepted_kwargs(fn, kwargs: dict) -> dict:
    """Return the subset of kwargs that fn can take (everything if fn has **kwargs or can't be inspected)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return dict(kwargs)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)
    dropped = [k for k in kwargs if k not in params]
    if dropped:
        log.debug("%s does not accept %s; skipping", getattr(fn, "__name__", fn), dropped)
    return {k: v for k, v in kwargs.items() if k in params}


def call(fn, *args, **kwargs):
    return fn(*args, **accepted_kwargs(fn, kwargs))


def make_client(factory, **kwargs):
    """Build an instagrapi Client with only the constructor options the installed version supports."""
    target = factory.__init__ if inspect.isclass(factory) else factory
    try:
        sig_kwargs = {k: v for k, v in kwargs.items()}
        params = inspect.signature(target).parameters
        if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            sig_kwargs = {k: v for k, v in kwargs.items() if k in params}
            skipped = sorted(set(kwargs) - set(sig_kwargs))
            if skipped:
                log.warning("Installed instagrapi Client() does not support %s; ignoring", skipped)
        return factory(**sig_kwargs)
    except TypeError:
        log.warning("Client() rejected some options; retrying with only settings and proxy")
        return factory(**{k: v for k, v in kwargs.items() if k in ("settings", "proxy") and v})


def call_if(obj, name: str, *args):
    """Call obj.name(*args) when it exists; return None otherwise."""
    fn = getattr(obj, name, None)
    return fn(*args) if callable(fn) else None


def user_by_username(cl, username: str):
    """user_info_by_username without relying on the optional use_cache argument."""
    return call(cl.user_info_by_username, username, use_cache=False)
