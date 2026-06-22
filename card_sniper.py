"""
Card Sniper — I/O shell.
Wires card_sniper_core to the Trello and Slack APIs.

Usage:
  python card_sniper.py --once           # one cycle, live
  python card_sniper.py --once --sandbox # one cycle, dry-run (logs to sniper_sandbox.log)
  python card_sniper.py --loop           # runs every poll_interval_sec seconds
  python card_sniper.py --loop --sandbox
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import card_sniper_core as core

# ── logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("card_sniper")

# ── paths ─────────────────────────────────────────────────────────────────────

_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_DIR, "sniper_config.json")
STATE_PATH = os.path.join(_DIR, "sniper_state.json")
SANDBOX_LOG = os.path.join(_DIR, "sniper_sandbox.log")


# ── Trello helpers ────────────────────────────────────────────────────────────

def _trello(path: str, config: dict) -> object:
    key = config["trello_api_key"]
    token = config["trello_token"]
    sep = "&" if "?" in path else "?"
    url = f"https://api.trello.com/1{path}{sep}key={key}&token={token}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        log.error("Trello %s → HTTP %s", path, e.code)
        raise


def get_all_boards(config: dict) -> list:
    return _trello("/members/me/boards?fields=name,id", config)


def get_board_lists(board_id: str, config: dict) -> list:
    return _trello(f"/boards/{board_id}/lists?fields=name,id", config)


def get_list_cards(list_id: str, config: dict) -> list:
    return _trello(
        f"/lists/{list_id}/cards?fields=id,name,desc,labels,shortUrl,idList",
        config,
    )


def get_card(card_id: str, config: dict) -> dict:
    return _trello(
        f"/cards/{card_id}?fields=id,name,labels,idList,shortUrl",
        config,
    )


def get_list_name(list_id: str, config: dict) -> str:
    info = _trello(f"/lists/{list_id}?fields=name", config)
    return info["name"]


# ── Slack helpers ─────────────────────────────────────────────────────────────

def _slack(method: str, payload: dict, config: dict) -> dict:
    token = config["slack_token"]
    url = f"https://slack.com/api/{method}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        log.error("Slack %s → HTTP %s", method, e.code)
        raise
    if not result.get("ok"):
        log.warning("Slack %s error: %s", method, result.get("error"))
    return result


def _open_dm(user_id: str, config: dict) -> str:
    r = _slack("conversations.open", {"users": user_id}, config)
    return r["channel"]["id"]


def send_alert(card: dict, board_name: str, config: dict, sandbox: bool) -> bool:
    alert = core.build_alert(card, board_name, config["editor_key"])
    user_id = config["slack_user_id"]

    if sandbox:
        entry = (
            f"\n[SANDBOX] card={card['id']} board={board_name} "
            f"card_name={card.get('name')}\n"
            + json.dumps(alert, indent=2, ensure_ascii=False)
            + "\n"
        )
        with open(SANDBOX_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
        log.info("[SANDBOX] Would DM %s: %s (%s)", user_id, card["name"], board_name)
        return True

    try:
        channel = _open_dm(user_id, config)
        r = _slack(
            "chat.postMessage",
            {
                "channel": channel,
                "text": alert["text"],
                "blocks": alert["blocks"],
            },
            config,
        )
        return r.get("ok", False)
    except Exception as e:
        log.error("Failed to send Slack alert: %s", e)
        return False


def send_taken_dm(card_name: str, config: dict, sandbox: bool) -> None:
    msg = f"⚡ _Already taken:_ *{card_name}* — someone was faster."
    if sandbox:
        log.info("[SANDBOX] Would send 'taken' DM: %s", card_name)
        return
    try:
        channel = _open_dm(config["slack_user_id"], config)
        _slack("chat.postMessage", {"channel": channel, "text": msg}, config)
    except Exception as e:
        log.warning("Could not send taken DM: %s", e)


# ── outcome detection (Trello is SSOT) ───────────────────────────────────────

def _card_is_jelenas(card: dict, config: dict) -> bool:
    label = config.get("editor_label", "jelenab").lower()
    return any(lbl.get("name", "").lower() == label for lbl in card.get("labels", []))


def detect_outcomes(state: dict, config: dict) -> dict:
    """
    For each card we pinged but haven't got an outcome for yet:
    check Trello — if it now has Jelena's label, record it as claimed.
    """
    pending = [
        cid for cid, info in state.get("pinged", {}).items()
        if info.get("outcome") is None
    ]
    for card_id in pending:
        try:
            card = get_card(card_id, config)
        except Exception:
            continue
        if _card_is_jelenas(card, config):
            log.info("Detected claim: card %s now has jelenab label", card_id)
            state = core.next_state_after_outcome(card_id, "claimed", state)
            state = core.set_in_flight(card_id, state)
    return state


# ── main cycle ────────────────────────────────────────────────────────────────

def run_sniper_cycle(config: dict, state: dict, sandbox: bool) -> dict:
    log.info("── cycle start (sandbox=%s) ──", sandbox)

    # Phase 1: Detect outcomes for previously-pinged cards
    state = detect_outcomes(state, config)
    core.save_state(STATE_PATH, state)

    # Phase 2: If Jelena has a card in flight, check if it's done
    if not core.jelena_is_free(state):
        in_flight = state["in_flight_card_id"]
        log.info("In-flight: %s — checking completion", in_flight)
        try:
            card = get_card(in_flight, config)
            list_name = get_list_name(card["idList"], config)
            if core.detect_done(list_name):
                log.info("Card %s is done (%s) — Jelena is free again", in_flight, list_name)
                state = core.next_state_after_outcome(in_flight, "done", state)
                core.save_state(STATE_PATH, state)
            else:
                log.info("Still in progress — suppressing all alerts")
                return state
        except Exception as e:
            log.warning("Could not check in-flight card %s: %s", in_flight, e)
            return state

    # Phase 3: Scan eligible boards for new NextUp cards
    try:
        all_boards = get_all_boards(config)
    except Exception as e:
        log.error("Could not fetch boards: %s — skipping cycle", e)
        return state

    eligible = [b for b in all_boards if core.board_is_eligible(b["name"], config)]
    log.info("Scanning %d eligible boards (of %d total)", len(eligible), len(all_boards))

    alerts_sent = 0

    for board in eligible:
        try:
            lists = get_board_lists(board["id"], config)
        except Exception as e:
            log.warning("Skipping board %s: %s", board["name"], e)
            continue

        nextup = next((l for l in lists if l["name"] == core.NEXTUP_LIST_NAME), None)
        if not nextup:
            continue

        try:
            cards = get_list_cards(nextup["id"], config)
        except Exception as e:
            log.warning("Skipping NextUp on %s: %s", board["name"], e)
            continue

        for card in sorted(cards, key=core.score_card, reverse=True):
            if not core.is_eligible_card(card, core.NEXTUP_LIST_NAME, board["name"], config):
                continue
            if not core.should_ping(card["id"], state, config):
                continue

            log.info("Alerting: %s — %s", board["name"], card["name"])
            ok = send_alert(card, board["name"], config, sandbox)
            if ok:
                state = core.next_state_after_ping(card["id"], state)
                if not sandbox:
                    core.save_state(STATE_PATH, state)
                alerts_sent += 1

    log.info("── cycle done: %d alert(s) sent ──", alerts_sent)
    return state


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Card Sniper for Jelena")
    p.add_argument("--once", action="store_true", help="Run one cycle and exit")
    p.add_argument("--loop", action="store_true", help="Run continuously")
    p.add_argument("--sandbox", action="store_true", help="Dry-run: log instead of send")
    args = p.parse_args()

    if not args.once and not args.loop:
        p.error("Specify --once or --loop")

    config = core.load_config(CONFIG_PATH)
    state = core.load_state(STATE_PATH)

    if args.once:
        run_sniper_cycle(config, state, sandbox=args.sandbox)
        sys.exit(0)

    interval = config.get("poll_interval_sec", 120)
    log.info("Loop started — polling every %ds", interval)
    while True:
        try:
            state = run_sniper_cycle(config, state, sandbox=args.sandbox)
        except Exception as e:
            log.error("Unhandled cycle error: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    main()
