"""Điểm danh HoYoLAB (Genshin) + báo code mới, chạy hằng ngày trên GitHub Actions.

Biến môi trường (đặt trong Settings > Secrets and variables > Actions):
  HOYO_ACCOUNTS    JSON: [{"label": "...", "cookies": "ltoken_v2=...; ltuid_v2=...; ..."}]
  DISCORD_WEBHOOK  (không bắt buộc) URL webhook Discord để nhận thông báo
Thoát với mã lỗi 1 nếu cookie hết hạn / lỗi -> GitHub tự gửi email báo.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp
import genshin

GAME = genshin.Game.GENSHIN
CODES_API = "https://hoyo-codes.seria.moe/codes?game=genshin"
SEEN_FILE = Path(__file__).with_name("seen_codes.json")


def gift_url(code: str) -> str:
    return f"https://genshin.hoyoverse.com/en/gift?code={code}"


async def claim(label: str, cookies: str) -> tuple[bool, str]:
    """Trả về (ổn?, thông điệp)."""
    client = genshin.Client(cookies, game=GAME)
    try:
        reward = await client.claim_daily_reward(reward=True)
        return True, f"✅ **{label}**: đã điểm danh, nhận {reward.name} x{reward.amount}"
    except genshin.AlreadyClaimed:
        return True, f"☑️ **{label}**: hôm nay đã điểm danh rồi"
    except genshin.InvalidCookies:
        return False, f"❌ **{label}**: cookie hết hạn, cần lấy cookie mới"
    except genshin.DailyGeetestTriggered:
        return False, f"⚠️ **{label}**: HoYoLAB bắt xác minh captcha, hôm nay hãy điểm danh tay trong app"
    except genshin.GenshinException as exc:
        return False, f"⚠️ **{label}**: lỗi HoYoLAB: {exc.msg or exc}"


async def redeem(label: str, cookies: str, code: str) -> str | None:
    """Thử tự nhập code (chỉ được khi cookie có cookie_token_v2). None = không nhập được."""
    if "cookie_token_v2" not in cookies:
        return None
    client = genshin.Client(cookies, game=GAME)
    try:
        await client.redeem_code(code)
        return f"🎁 **{label}**: đã tự nhập `{code}`"
    except genshin.RedemptionClaimed:
        return f"☑️ **{label}**: `{code}` đã nhập trước đó"
    except genshin.GenshinException:
        return None


async def fetch_codes() -> list[tuple[str, str]]:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(CODES_API) as r:
                r.raise_for_status()
                data = await r.json()
    except Exception as exc:  # noqa: BLE001
        print("Không lấy được danh sách code:", exc)
        return []
    out = []
    for item in data.get("codes", []):
        code = str(item.get("code", "")).strip().upper()
        if code:
            out.append((code, str(item.get("rewards", "")).strip()))
    return out


async def notify(text: str) -> None:
    url = os.getenv("DISCORD_WEBHOOK", "").strip()
    if not url:
        return
    async with aiohttp.ClientSession() as s:
        for i in range(0, len(text), 1900):  # Discord giới hạn 2000 ký tự
            await s.post(url, json={"content": text[i:i + 1900], "username": "Điểm danh Genshin"})


async def main() -> int:
    accounts = json.loads(os.environ["HOYO_ACCOUNTS"])
    lines, all_ok = [], True

    for acc in accounts:
        ok, msg = await claim(acc["label"], acc["cookies"])
        all_ok &= ok
        lines.append(msg)

    seen = set(json.loads(SEEN_FILE.read_text(encoding="utf-8"))) if SEEN_FILE.exists() else set()
    new_codes = [(c, rw) for c, rw in await fetch_codes() if c not in seen]
    if new_codes:
        lines.append("\n**Code mới** (bấm link khi đã đăng nhập để nhận quà):")
        for code, rewards in new_codes:
            done = []
            for acc in accounts:
                r = await redeem(acc["label"], acc["cookies"], code)
                if r:
                    done.append(r)
                await asyncio.sleep(6)  # tránh bị cooldown khi nhập nhiều code
            lines.append(f"• `{code}` – {rewards}\n  {gift_url(code)}")
            lines.extend("  " + d for d in done)
            seen.add(code)
        SEEN_FILE.write_text(json.dumps(sorted(seen), indent=1), encoding="utf-8")

    report = "\n".join(lines)
    print(report)
    await notify(report)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
