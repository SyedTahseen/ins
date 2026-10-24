"""Run from ~/ins:  python3 debug_about.py cherryycolaaw
Prints the library's about-code, the error location and the raw response so the parser can be fixed."""
import glob, inspect, json, sys, traceback
from instagrapi import Client

username = sys.argv[1] if len(sys.argv) > 1 else "instagram"
from config import load_config
from utils.db import FileStore, MongoStore

cfg = load_config()
if cfg.mongo_uri:
    col = MongoStore(cfg.mongo_uri, cfg.mongo_db).col
    ids = [d["_id"] for d in col.find({"_id": {"$regex": "_session$"}}, {"_id": 1})]
    raw = col.find_one({"_id": ids[0]})["json"] if ids else None
    settings = json.loads(raw) if raw else None
else:
    files = glob.glob(str(cfg.data_dir / "u*_session.json"))
    settings = json.load(open(files[0])) if files else None
if not settings:
    sys.exit("No saved session found. Connect in the bot first.")
cl = Client(settings=settings)

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
