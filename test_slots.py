"""Self-check: day-aware scheduling picks research-optimal slots."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from upload_youtube import next_free_slot, DAY_WEIGHT  # noqa: E402

used = set()
# simulate filling 6 video slots from a Wednesday
now = datetime(2026, 9, 2, 14, 0).astimezone()
base = now + timedelta(hours=3)
# monkeypatch datetime used in next_free_slot via its module import
import upload_youtube as uy  # noqa: E402
uy_datetime = uy.datetime


class FakeDT(uy_datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 2, 14, 0).astimezone()


uy.datetime = FakeDT
slots = []
for _ in range(6):
    s = next_free_slot("video", used)
    used.add(s.strftime("%Y-%m-%d %H:%M"))
    slots.append(s)
days = [s.strftime("%a %H:%M") for s in slots]
print("video slots:", days)
# from Wed: best video day is Sun (weight 0) - fill all its slots first,
# then next-best days Tue/Mon (weight 1). All morning hours.
assert all(d.startswith("Sun") for d in days[:4]), days
assert days[4].startswith("Tue") or days[4].startswith("Mon"), days
assert all(int(d.split()[1].split(":")[0]) < 13 for d in days), "video should be morning"

shorts = []
used_s = set()
for _ in range(3):
    s = next_free_slot("short", used_s)
    used_s.add(s.strftime("%Y-%m-%d %H:%M"))
    shorts.append(s.strftime("%a %H:%M"))
print("short slots:", shorts)
assert shorts[0].startswith("Fri") or shorts[0].startswith("Thu"), shorts
assert all(int(d.split()[1].split(":")[0]) >= 16 for d in shorts), "shorts should be evening"

# ig day-aware check
from instagram_upload import next_free_slot as ig_slot  # noqa: E402
import instagram_upload as iu  # noqa: E402


class FakeDT2(iu.datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 2, 14, 0).astimezone()


iu.datetime = FakeDT2
used_ig = set()
ig = ig_slot(used_ig)
print("ig slot:", ig.strftime("%a %H:%M"))
assert ig.strftime("%a") in ("Wed", "Thu"), ig
assert ig.strftime("%H") in ("12", "18"), ig

print("ALL SLOT CHECKS PASSED")
