"""One-shot: check views on all published videos."""
import json
from pathlib import Path

import requests

KEY = "AIzaSyBvoDBp42F16zjg5p9pzh5dZuVz7PkW9gA"
state = json.loads(Path("schedule_state.json").read_text(encoding="utf-8"))
ids = [u["youtube_id"] for u in state["uploaded"]]
r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                 params={"part": "snippet,statistics,status",
                         "id": ",".join(ids[-45:]), "key": KEY}, timeout=30).json()
print(f"{'title':<42}{'views':>9}  {'likes':>6}  {'state':>7}")
for i in r.get("items", []):
    st = i.get("statistics", {})
    pub = i.get("status", {}).get("privacyStatus", "?")
    if pub == "private" and i.get("status", {}).get("publishAt"):
        pub = "sched"
    print(f"{i['snippet']['title'][:41]:<42}"
          f"{int(st.get('viewCount') or 0):>9}  "
          f"{int(st.get('likeCount') or 0):>6}  {pub:>7}")
