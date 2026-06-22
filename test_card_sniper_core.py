"""pytest tests for card_sniper_core — pure functions only, zero I/O."""

from datetime import datetime, timezone, timedelta
import card_sniper_core as core


# ── fixtures ──────────────────────────────────────────────────────────────────

def card(id="c1", labeled=False, desc="A" * 60):
    return {
        "id": id,
        "name": "Test Card",
        "desc": desc,
        "labels": [{"name": "jelenab"}] if labeled else [],
        "shortUrl": "https://trello.com/c/test",
        "idList": "list1",
    }


def cfg(**kw):
    return {
        **core.CONFIG_DEFAULTS,
        "health_blocklist_brands": ["Bad Health Co", "Reishi Therapy", "VitalVac"],
        "excluded_board_names": ["Aditor", "Demo Board"],
        **kw,
    }


def state(**kw):
    return {**core.STATE_DEFAULTS, **kw}


def ts_this_week():
    return datetime.now(timezone.utc).isoformat()


def ts_last_week():
    return (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()


# ── eligibility ───────────────────────────────────────────────────────────────

def test_card_has_script():
    assert core.card_has_script(card(desc="A" * 60))


def test_card_no_script_too_short():
    assert not core.card_has_script(card(desc="short"))


def test_card_is_claimed():
    assert core.card_is_claimed(card(labeled=True))


def test_card_not_claimed():
    assert not core.card_is_claimed(card(labeled=False))


def test_board_eligible_clean():
    assert core.board_is_eligible("Proof Brother", cfg())


def test_board_blocked_health():
    assert not core.board_is_eligible("Reishi Therapy", cfg())


def test_board_blocked_health_substring():
    assert not core.board_is_eligible("VitalVac GmbH", cfg())


def test_board_blocked_excluded():
    assert not core.board_is_eligible("Aditor", cfg())


def test_is_eligible_happy_path():
    assert core.is_eligible_card(card(), core.NEXTUP_LIST_NAME, "Proof Brother", cfg())


def test_not_eligible_wrong_list():
    assert not core.is_eligible_card(card(), core.ACTIVE_LIST_NAME, "Proof Brother", cfg())


def test_not_eligible_claimed():
    assert not core.is_eligible_card(card(labeled=True), core.NEXTUP_LIST_NAME, "Proof Brother", cfg())


def test_not_eligible_no_script():
    assert not core.is_eligible_card(card(desc="short"), core.NEXTUP_LIST_NAME, "Proof Brother", cfg())


def test_not_eligible_health_board():
    assert not core.is_eligible_card(card(), core.NEXTUP_LIST_NAME, "Bad Health Co", cfg())


# ── one-at-a-time ─────────────────────────────────────────────────────────────

def test_jelena_free():
    assert core.jelena_is_free(state())


def test_jelena_not_free():
    assert not core.jelena_is_free(state(in_flight_card_id="c99"))


# ── ping dedup ────────────────────────────────────────────────────────────────

def test_should_ping_fresh():
    assert core.should_ping("c1", state(), cfg())


def test_should_ping_already_pinged():
    s = state(pinged={"c1": {"ts": ts_this_week(), "outcome": None}})
    assert not core.should_ping("c1", s, cfg())


def test_no_dup_after_state_update():
    s = state()
    s = core.next_state_after_ping("c1", s)
    assert not core.should_ping("c1", s, cfg())


# ── weekly cap ────────────────────────────────────────────────────────────────

def test_cap_not_reached():
    assert core.should_ping("c1", state(), cfg(weekly_cap=4))


def test_cap_reached_blocks_ping():
    s = state(outcome_log=[
        {"card_id": f"c{i}", "outcome": "claimed", "ts": ts_this_week()}
        for i in range(4)
    ])
    assert not core.should_ping("c99", s, cfg(weekly_cap=4))


def test_cap_last_week_doesnt_count():
    s = state(outcome_log=[
        {"card_id": f"c{i}", "outcome": "claimed", "ts": ts_last_week()}
        for i in range(4)
    ])
    assert core.should_ping("c99", s, cfg(weekly_cap=4))


# ── done detection ────────────────────────────────────────────────────────────

def test_done_approved():
    assert core.detect_done("🎉 Approved!")


def test_done_winner():
    assert core.detect_done("Winner 🏆")


def test_not_done_active():
    assert not core.detect_done("🔥 Active")


def test_not_done_nextup():
    assert not core.detect_done(core.NEXTUP_LIST_NAME)


# ── claim race guard ──────────────────────────────────────────────────────────

def test_claim_decision_free():
    assert core.claim_decision([], core.NEXTUP_LIST_NAME) == "claim"


def test_claim_decision_already_labeled():
    assert core.claim_decision([{"name": "jelenab"}], core.NEXTUP_LIST_NAME) == "taken"


def test_claim_decision_wrong_list():
    assert core.claim_decision([], core.ACTIVE_LIST_NAME) == "taken"


# ── state transitions ─────────────────────────────────────────────────────────

def test_outcome_clears_in_flight():
    s = core.set_in_flight("c1", state())
    s = core.next_state_after_outcome("c1", "done", s)
    assert s["in_flight_card_id"] is None


def test_outcome_appended_to_log():
    s = core.next_state_after_outcome("c1", "claimed", state())
    assert any(e["card_id"] == "c1" for e in s["outcome_log"])
