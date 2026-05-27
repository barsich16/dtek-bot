import requests
import os
import json
import hashlib
import subprocess
from datetime import datetime

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
# Your outage group number (1–6 for Kyiv, check yasno.com.ua to find yours)
GROUP = os.environ.get("DTEK_GROUP", "6.1")
# Region: "kiev" or "dnipro"
REGION = os.environ.get("DTEK_REGION", "kiev")

STATE_FILE = "last_state.json"
API_URL = "https://api.yasno.com.ua/api/v1/pages/home/schedule-turn-off-electricity"


def fetch_schedule() -> dict:
    r = requests.get(API_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    return r.json()


def hours_to_time(h: float) -> str:
    """Convert float hours (e.g. 12.5) to HH:MM string."""
    total_minutes = int(h * 60)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def format_slots(slots: list) -> str:
    if not slots:
        return "no outages"
    parts = []
    for slot in slots:
        start = hours_to_time(slot["start"])
        end = hours_to_time(slot["end"])
        kind = slot.get("type", "")
        emoji = "🔴" if "DEFINITE" in kind else "🟡"
        parts.append(f"{emoji} {start}–{end}")
    return ", ".join(parts)


def format_message(data: dict) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines = [f"⚡ <b>YASNO schedule update</b> — group {GROUP} ({now})\n"]

    daily = data.get("dailySchedule", {}).get(REGION, {})
    for period in ("today", "tomorrow"):
        entry = daily.get(period)
        if not entry:
            continue
        date_label = period.capitalize()
        groups = entry.get("groups", {})
        slots = groups.get(GROUP) or []
        lines.append(f"<b>{date_label}</b>: {format_slots(slots)}")

    if len(lines) == 1:
        # Fallback: unknown structure, dump raw
        lines.append(f"<pre>{json.dumps(data, indent=2, ensure_ascii=False)[:3000]}</pre>")

    return "\n".join(lines)


def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    ).raise_for_status()


def load_last_hash() -> str | None:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)["hash"]
    except (FileNotFoundError, KeyError):
        return None


def save_hash(h: str) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump({"hash": h, "updated": datetime.now().isoformat()}, f)


def git_commit_state() -> None:
    subprocess.run(["git", "config", "user.email", "dtek-bot@users.noreply.github.com"], check=True)
    subprocess.run(["git", "config", "user.name", "dtek-bot"], check=True)
    subprocess.run(["git", "add", STATE_FILE], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if result.returncode != 0:
        subprocess.run(["git", "commit", "-m", "chore: update state"], check=True)
        subprocess.run(["git", "push"], check=True)


def main() -> None:
    data = fetch_schedule()

    # Only hash the region+group data so unrelated regions don't trigger noise
    region_data = data.get("dailySchedule", {}).get(REGION, {})
    relevant = {
        period: entry.get("groups", {}).get(GROUP)
        for period, entry in region_data.items()
        if isinstance(entry, dict)
    }
    current_hash = hashlib.md5(
        json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()

    last_hash = load_last_hash()

    if current_hash != last_hash:
        print(f"Change detected: {last_hash} → {current_hash}")
        send_telegram(format_message(data))
        save_hash(current_hash)
        git_commit_state()
    else:
        print("No change detected.")


if name == "__main__":
    main()