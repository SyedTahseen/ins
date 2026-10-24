"""Run from ~/ins:  python3 debug_about.py cherryycolaaw
Prints the library's about-code, the error location and the raw response so the parser can be fixed."""
import glob, inspect, json, sys, traceback
from instagrapi import Client

username = sys.argv[1] if len(sys.argv) > 1 else "instagram"
files = glob.glob("data/u*_session.json")
if not files:
    sys.exit("No saved session found in ./data. Connect in the bot first.")
cl = Client(settings=json.load(open(files[0])))
print("session file:", files[0])

print("\n===== library source: user_about_v1 =====")
print(inspect.getsource(Client.user_about_v1))
for name in dir(Client):
    if "about" in name.lower() and name != "user_about_v1":
        print("also:", name)
try:
    import instagrapi.extractors as ex
    for n in dir(ex):
        if "about" in n.lower():
            print("\n===== extractor", n, "=====")
            print(inspect.getsource(getattr(ex, n)))
except Exception as e:
    print("extractors:", e)

print("\n===== running it =====")
try:
    pk = cl.user_id_from_username(username)
    print("pk:", pk)
    print(cl.user_about_v1(str(pk)))
except Exception:
    traceback.print_exc()
    print("\n===== raw last_json (first 3000 chars) =====")
    print(json.dumps(cl.last_json, indent=1, default=str)[:3000])
