"""Run this on the server:  python3 check_api.py
Checks that the installed instagrapi provides everything this bot uses, and prints what is missing."""
import importlib.metadata as md
import inspect
import sys

try:
    import instagrapi
    from instagrapi import Client
    from instagrapi import exceptions as exc
except Exception as e:  # noqa: BLE001
    sys.exit(f"Cannot import instagrapi: {e}")

try:
    _v = md.version("instagrapi")
except Exception:  # noqa: BLE001
    _v = getattr(instagrapi, "__version__", "unknown")
print("instagrapi", _v, "| python", sys.version.split()[0])
bad = 0


def report(ok, label, note=""):
    global bad
    bad += (not ok)
    print(("  ok      " if ok else "  MISSING ") + label + (f"  {note}" if note else ""))


print("\nClient methods used by the bot:")
methods = """login login_legacy login_by_sessionid relogin logout get_settings set_settings account_info challenge_resolve
totp_generate_code set_locale set_country set_country_code set_timezone_offset set_app set_user_agent
user_info_by_username user_about_v1 user_medias user_clips user_stories user_highlights user_followers user_following
media_info media_pk_from_url photo_download video_download album_download igtv_download clip_download clip_download_by_url
story_pk_from_url story_download story_download_by_url highlight_pk_from_url highlight_info
track_info_by_canonical_id track_download_by_url""".split()
for m in methods:
    report(callable(getattr(Client, m, None)), m)

print("\nSignatures the bot relies on:")
def has_param(method, param):
    fn = getattr(Client, method, None)
    if not fn:
        return False
    ps = inspect.signature(fn).parameters
    return param in ps or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in ps.values())
for method, param in [("login", "relogin"), ("login", "verification_code"), ("login_legacy", "relogin"),
                      ("user_info_by_username", "use_cache"), ("user_followers", "amount"), ("user_following", "amount"),
                      ("user_medias", "amount"), ("user_clips", "amount")]:
    report(has_param(method, param), f"{method}({param}=...)", "(bot adapts automatically if absent)" if method in ("login", "login_legacy", "user_info_by_username") else "")

print("\nClient() options:")
ps = inspect.signature(Client.__init__).parameters
for p in ("settings", "proxy", "delay_range", "tls_verify"):
    report(p in ps or any(x.kind is inspect.Parameter.VAR_KEYWORD for x in ps.values()), p, "(bot adapts automatically if absent)" if p == "tls_verify" else "")

print("\nExceptions (bot substitutes a stub for any that are missing):")
names = """AccountSuspended AuthRequiredProxyError BadCredentials BadPassword ChallengeRequired ChallengeSelfieCaptcha ChallengeUnknownStep
CheckpointRequired ClientConnectionError ClientError ClientIncompleteReadError ClientLoginRequired ClientNeedsUpgradeError
ClientRequestTimeout ClientThrottledError ConnectProxyError ConsentRequired FeedbackRequired LegacyForceSetNewPasswordForm LoginRequired
PleaseWaitFewMinutes ProxyAddressIsBlocked RateLimitError RecaptchaChallengeForm ReloginAttemptExceeded SelectContactPointRecoveryForm
SentryBlock SubmitPhoneNumberForm TwoFactorRequired UserNotFound ClientNotFoundError PrivateAccount""".split()
for n in names:
    report(hasattr(exc, n), n)

print("\nHelpers:")
for mod, name in [("instagrapi.config", "DEFAULT_APP_VERSION"), ("instagrapi.utils", "json_value"), ("instagrapi.mixins.challenge", "ChallengeChoice")]:
    try:
        report(hasattr(importlib_m := __import__(mod, fromlist=[name]), name), f"{mod}.{name}")
    except Exception as e:  # noqa: BLE001
        report(False, f"{mod}.{name}", str(e))

print(f"\n{bad} item(s) missing." + (" The bot degrades gracefully where it can; paste this output if something fails." if bad else " All good."))
