"""One-time SEO boost: rewrite titles/descriptions/tags + custom thumbnails
for all public videos on the channel. Run manually when needed."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from upload_youtube import get_service  # noqa: E402
from captions import generate_youtube, clean_title  # noqa: E402
from googleapiclient.http import MediaFileUpload  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FFMPEG = r"C:\Users\manth\DailyVideoBot\bin\ffmpeg.exe"
FONT = r"C:\Windows\Fonts\arialbd.ttf"
TMP = Path(r"C:\Users\manth\DailyVideoBot\thumbs")
THUMBNAILS_ENABLED = False   # user opted out (needs channel phone-verification)
TMP.mkdir(exist_ok=True)


def make_thumbnail(vid: str, title: str, out: Path):
    """Build thumbnail from YouTube's own frame image (works even for private videos
    via hqdefault), else gradient fallback; overlay headline text."""
    import requests
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance

    src = None
    for quality in ("maxresdefault", "sddefault", "hqdefault"):
        try:
            r = requests.get(f"https://i.ytimg.com/vi/{vid}/{quality}.jpg", timeout=20)
            if r.status_code == 200 and len(r.content) > 2000:
                from io import BytesIO
                src = Image.open(BytesIO(r.content)).convert("RGB")
                break
        except Exception:
            continue

    if src is not None:
        # crop/resize to 1280x720
        w, h = src.size
        target = 1280 / 720
        if w / h > target:
            nw = int(h * target)
            src = src.crop(((w - nw) // 2, 0, (w + nw) // 2, h))
        else:
            nh = int(w / target)
            src = src.crop((0, (h - nh) // 2, w, (h + nh) // 2))
        img = src.resize((1280, 720))
        img = ImageEnhance.Brightness(img).enhance(0.75)
    else:
        img = Image.new("RGB", (1280, 720))
        d0 = ImageDraw.Draw(img)
        for y in range(720):
            d0.line([(0, y), (1280, y)],
                    fill=(30 + y // 8, 10 + y // 14, 90 + y // 6))

    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 330, 70], fill=(200, 20, 20))
    draw.text((15, 12), "AI GENERATED", font=ImageFont.truetype(FONT, 38), fill="white")

    words = clean_title(title).upper().split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if len(test) > 22 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
        if len(lines) == 2:
            break
    if cur and len(lines) < 3:
        lines.append(cur)

    fnt = ImageFont.truetype(FONT, 64)
    y = 720 - 90 * len(lines) - 20
    for ln in lines:
        wd = draw.textlength(ln, font=fnt)
        x = max(10, (1280 - wd) / 2)
        draw.text((x - 3, y - 3), ln, font=fnt, fill="black")
        draw.text((x, y), ln, font=fnt, fill=(255, 210, 0))
        y += 90

    img.save(out, quality=88)
    return out


def main() -> None:
    svc = get_service()

    # fetch all my public uploads
    ch = svc.channels().list(part="contentDetails", mine=True).execute()
    pl = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    vids = svc.playlistItems().list(part="snippet", playlistId=pl, maxResults=50).execute()
    ids = [i["snippet"]["resourceId"]["videoId"] for i in vids["items"]]
    details = svc.videos().list(part="snippet,status,fileDetails", id=",".join(ids)).execute()

    print(f"Found {len(details['items'])} videos to boost\n")
    import re
    from captions import YT_SUFFIXES

    def strip_suffixes(t: str) -> str:
        for suf in YT_SUFFIXES:
            words = re.findall(r"\w+", suf)
            if not words:
                continue
            # tolerate emojis/punctuation/zero-width chars between words
            pat = r"[^\w]*" + r"[^\w]+".join(re.escape(w) for w in words)
            prev = None
            while prev != t and re.search(pat, t, flags=re.IGNORECASE):
                prev = t
                t = re.sub(pat, " ", t, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", t).strip(" -|.,|")

    for item in details["items"]:
        vid = item["id"]
        sn = item["snippet"]
        file_hint = item.get("fileDetails", {}).get("fileName") or ""
        meta = {"source_id": vid, "title": strip_suffixes(sn["title"]), "duration": 60}
        seo = generate_youtube(meta)

        # 1) metadata update (send FULL snippet back, modified)
        sn["title"] = seo["title"]
        sn["description"] = seo["description"]
        sn["tags"] = seo["tags"]
        try:
            svc.videos().update(part="snippet", body={"id": vid, "snippet": sn}).execute()
            print(f"[SEO OK] {vid}: {seo['title'][:65]}")
        except Exception as exc:
            print(f"[SEO FAIL] {vid}: {exc}")
            continue

        # 2) thumbnail (disabled - requires channel phone verification)
        if THUMBNAILS_ENABLED:
            jpg = TMP / f"{vid}.jpg"
            try:
                make_thumbnail(vid, seo["title"], jpg)
                svc.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(jpg))).execute()
                print(f"[THUMB OK] {vid}")
            except Exception as exc:
                print(f"[THUMB FAIL] {vid}: {exc}")

    print("\nDone.")


if __name__ == "__main__":
    main()
