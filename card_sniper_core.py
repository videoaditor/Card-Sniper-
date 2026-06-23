"""
Pure-logic core for the Card Sniper — zero I/O.
All eligibility, state-transition, and decision logic lives here.
"""

import json
from datetime import datetime, timezone, timedelta

# ── list names (must match Trello exactly) ────────────────────────────────────

NEXTUP_LIST_NAME = "➡️ Next Up"
ACTIVE_LIST_NAME = "🔥 Active"
DONE_LIST_NAMES = {"🎉 Approved!", "Winner 🏆"}

# ── config / state defaults ───────────────────────────────────────────────────

CONFIG_DEFAULTS = {
    "editor_key": "jelena",
    "editor_label": "jelenab",
    "slack_user_id": "",
    "weekly_cap": 4,
    "poll_interval_sec": 120,
    "min_script_len": 50,
    "health_blocklist_brands": [],
    "excluded_board_names": [],
    "allowlist": [],
    "trello_api_key": "",
    "trello_token": "",
    "slack_token": "",
}

STATE_DEFAULTS: dict = {
    "in_flight_card_id": None,
    "pinged": {},
    "outcome_log": [],
}


# ── eligibility ───────────────────────────────────────────────────────────────

def card_has_script(card: dict, min_len: int = 50) -> bool:
    return len((card.get("desc") or "").strip()) >= min_len


def card_is_claimed(card: dict) -> bool:
    return bool(card.get("labels"))


def board_is_eligible(board_name: str, config: dict) -> bool:
    name_lower = board_name.lower()
    for term in config.get("health_blocklist_brands", []):
        if term.lower() in name_lower:
            return False
    if board_name in config.get("excluded_board_names", []):
        return False
    allowlist = config.get("allowlist", [])
    if allowlist and board_name not in allowlist:
        return False
    return True


def is_likely_english(card: dict) -> bool:
    text = (card.get("name", "") + " " + (card.get("desc") or "")).lower()
    german_signals = ("ä", "ö", "ü", "ß", " für ", " und ", " mit ", " der ", " die ", " das ", " von ", " auf ", " ist ", " neue", " einen", " einem", " einer")
    return not any(s in text for s in german_signals)


def is_eligible_card(card: dict, list_name: str, board_name: str, config: dict) -> bool:
    if list_name != NEXTUP_LIST_NAME:
        return False
    if card_is_claimed(card):
        return False
    if not card_has_script(card, config.get("min_script_len", 50)):
        return False
    if not board_is_eligible(board_name, config):
        return False
    return True


# ── weekly cap helpers ────────────────────────────────────────────────────────

def _week_start() -> datetime:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _parse_ts(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _claimed_this_week(state: dict) -> int:
    ws = _week_start()
    return sum(
        1 for e in state.get("outcome_log", [])
        if e.get("outcome") == "claimed" and _parse_ts(e.get("ts", "")) >= ws
    )


# ── ping gating ───────────────────────────────────────────────────────────────

def jelena_is_free(state: dict) -> bool:
    return not state.get("in_flight_card_id")


def should_ping(card_id: str, state: dict, config: dict) -> bool:
    if card_id in state.get("pinged", {}):
        return False
    if _claimed_this_week(state) >= config.get("weekly_cap", 4):
        return False
    return True


# ── state transitions ─────────────────────────────────────────────────────────

def next_state_after_ping(card_id: str, state: dict) -> dict:
    s = {**state, "pinged": {**state.get("pinged", {})}}
    s["pinged"][card_id] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "outcome": None,
    }
    return s


def next_state_after_outcome(card_id: str, outcome: str, state: dict) -> dict:
    s = {
        **state,
        "pinged": {**state.get("pinged", {})},
        "outcome_log": list(state.get("outcome_log", [])),
    }
    if card_id in s["pinged"]:
        s["pinged"][card_id] = {**s["pinged"][card_id], "outcome": outcome}
    s["outcome_log"].append({
        "card_id": card_id,
        "outcome": outcome,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    if outcome in ("claimed", "taken", "expired", "done"):
        s["in_flight_card_id"] = None
    return s


def set_in_flight(card_id: str, state: dict) -> dict:
    return {**state, "in_flight_card_id": card_id}


# ── done detection ────────────────────────────────────────────────────────────

def detect_done(list_name: str) -> bool:
    return list_name in DONE_LIST_NAMES


# ── claim race guard ──────────────────────────────────────────────────────────

def claim_decision(card_labels: list, card_list_name: str) -> str:
    """Returns 'claim' or 'taken'. Call just before applying the editor label."""
    if card_list_name != NEXTUP_LIST_NAME:
        return "taken"
    if any(lbl.get("name") for lbl in card_labels):
        return "taken"
    return "claim"


# ── alert builder ─────────────────────────────────────────────────────────────

def build_alert(card: dict, board_name: str, editor_key: str = "jelena") -> dict:
    card_id = card["id"]
    card_name = card.get("name", "Unnamed card")
    card_url = card.get("shortUrl", card.get("url", ""))
    desc = (card.get("desc") or "").strip()[:200]

    return {
        "text": f"⚡ New card: *{card_name}* ({board_name})",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"⚡ *New card available*\n"
                        f"*{card_name}*\n"
                        f"_{board_name}_"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"_{desc}_" if desc else "_No script preview_",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Claim"},
                        "style": "primary",
                        "action_id": f"accept:{card_id}:{editor_key}",
                        "value": card_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open in Trello"},
                        "url": card_url,
                        "action_id": f"open:{card_id}",
                    },
                ],
            },
        ],
    }


# ── scoring (v1 neutral) ──────────────────────────────────────────────────────

def score_card(card: dict) -> float:
    return 0.0


# ── config / state I/O ────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    import os
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    config = {**CONFIG_DEFAULTS, **data}
    env_map = {
        "TRELLO_API_KEY": "trello_api_key",
        "TRELLO_TOKEN": "trello_token",
        "SLACK_TOKEN": "slack_token",
        "SLACK_USER_ID": "slack_user_id",
        "EDITOR_LABEL": "editor_label",
        "EDITOR_KEY": "editor_key",
        "WEEKLY_CAP": "weekly_cap",
    }
    for env_var, config_key in env_map.items():
        val = os.environ.get(env_var)
        if val:
            config[config_key] = int(val) if config_key == "weekly_cap" else val
    for json_var, config_key in (("HEALTH_BLOCKLIST_JSON", "health_blocklist_brands"), ("EXCLUDED_BOARDS_JSON", "excluded_board_names")):
        val = os.environ.get(json_var)
        if val:
            try:
                config[config_key] = json.loads(val)
            except json.JSONDecodeError:
                pass
    return config


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    return {**STATE_DEFAULTS, **data}


def save_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
