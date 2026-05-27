import requests
import os
import json
import hashlib
import subprocess
from datetime import datetime

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
# Group ID from DTEK (1=Kyiv group 1, 2=group 2, etc.)
GROUP_ID = os.environ.get("DTEK_GROUP", "1")

STATE_FILE = "last_state.json"
DTEK_API_URL = (
    "https://api.dtek.ua/api/power-off-schedule/v2/schedule"
    f"?groupId={GROUP_ID}"
)


def fetch_schedule() -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    r = requests.get(DTEK_API_URL, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def format_message(data: dict) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines = [f"⚡ <b>DTEK schedule update</b> ({now})\n"]

    schedules = data.get("schedules") or data.get("data") or []
    if not schedules:
        # Fallback: dump raw if structure is unknown
        lines.append(f"<pre>{json.dumps(data, indent=2, ensure_ascii=False)[:3000]}</pre>")
        return "\n".join(lines)

    for entry in schedules[:7]:  # limit to 7 days
        date = entry.get("date", "")
        intervals = entry.get("disconnectionIntervals") or entry.get("intervals") or []
        if intervals:
            times = ", ".join(
                f"{iv.get('startTime','?')}–{iv.get('endTime','?')}"
                for iv in intervals
            )
            lines.append(f"<b>{date}</b>: {times}")
        else:
            lines.append(f"<b>{date}</b>: no outages")

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
    current_hash = hashlib.md5(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()

    last_hash = load_last_hash()

    if current_hash != last_hash:
        print(f"Change detected: {last_hash} → {current_hash}")
        send_telegram(format_message(data))
        save_hash(current_hash)
        git_commit_state()
    else:
        print("No change detected.")


if __name__ == "__main__":
    main()
