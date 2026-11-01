# SPDX-License-Identifier: GPL-2.0-or-later
import pytest

from geoduck.domain.errors import ErrorCode, GeoDuckError, SessionStateError
from geoduck.domain.operations import ReadOutcome, ReadSummary
from geoduck.domain.session import TRANSITIONS, ErrorCause, SessionState, SessionStateMachine
from geoduck.domain.sql_text import quote_identifier, quote_string_literal
from geoduck.domain.versions import Version


class TestSessionStateMachine:
    def test_happy_path(self):
        sm = SessionStateMachine()
        seen = []
        sm.subscribe(lambda a, b: seen.append((a, b)))
        for target in (
            SessionState.CONNECTING,
            SessionState.READY,
            SessionState.BUSY,
            SessionState.READY,
            SessionState.CLOSING,
            SessionState.DISCONNECTED,
        ):
            sm.transition(target)
        assert sm.state is SessionState.DISCONNECTED
        assert seen[0] == (SessionState.DISCONNECTED, SessionState.CONNECTING)
        assert len(seen) == 6

    def test_invalid_transition_raises_and_keeps_state(self):
        sm = SessionStateMachine()
        with pytest.raises(SessionStateError):
            sm.transition(SessionState.READY)
        assert sm.state is SessionState.DISCONNECTED

    def test_every_state_has_rules_and_closing_ends_disconnected(self):
        assert set(TRANSITIONS) == set(SessionState)
        assert TRANSITIONS[SessionState.CLOSING] == {SessionState.DISCONNECTED}

    def test_error_recoverable_requires_a_cause(self):
        sm = SessionStateMachine()
        sm.transition(SessionState.CONNECTING)
        with pytest.raises(SessionStateError):
            sm.transition(SessionState.ERROR_RECOVERABLE)
        assert sm.state is SessionState.CONNECTING
        sm.transition(SessionState.ERROR_RECOVERABLE, ErrorCause.START_FAILED)
        assert sm.error_cause is ErrorCause.START_FAILED

    def test_cause_only_accompanies_error_recoverable(self):
        sm = SessionStateMachine()
        with pytest.raises(SessionStateError):
            sm.transition(SessionState.CONNECTING, ErrorCause.OPERATION_FAILED)

    def test_ready_to_error_recoverable_only_by_invalidation(self):
        sm = _machine_at(SessionState.READY)
        assert not sm.can(SessionState.ERROR_RECOVERABLE, ErrorCause.OPERATION_FAILED)
        assert not sm.can(SessionState.ERROR_RECOVERABLE, ErrorCause.START_FAILED)
        sm.transition(SessionState.ERROR_RECOVERABLE, ErrorCause.SESSION_INVALIDATED)
        assert sm.state is SessionState.ERROR_RECOVERABLE

    @pytest.mark.parametrize(
        ("cause", "can_ready"),
        [
            (ErrorCause.OPERATION_FAILED, True),
            (ErrorCause.START_FAILED, False),
            (ErrorCause.SESSION_INVALIDATED, False),
        ],
    )
    def test_back_to_ready_only_with_usable_connection(self, cause, can_ready):
        """Dictamen final (C13): ERROR_RECOVERABLE → READY solo si conexión y transacción son utilizables."""
        sm = _machine_at(SessionState.BUSY)
        sm.transition(SessionState.ERROR_RECOVERABLE, cause)
        assert sm.can(SessionState.READY) is can_ready
        for exit_ in (SessionState.CONNECTING, SessionState.CLOSING, SessionState.DISCONNECTED):
            assert sm.can(exit_)

    def test_cause_is_cleared_when_leaving_error_recoverable(self):
        sm = _machine_at(SessionState.BUSY)
        sm.transition(SessionState.ERROR_RECOVERABLE, ErrorCause.SESSION_INVALIDATED)
        sm.transition(SessionState.CONNECTING)
        assert sm.error_cause is None

    def test_cannot_start_in_error_recoverable_without_cause(self):
        with pytest.raises(SessionStateError):
            SessionStateMachine(SessionState.ERROR_RECOVERABLE)

    def test_unsubscribe(self):
        sm = SessionStateMachine()
        seen = []
        unsubscribe = sm.subscribe(lambda a, b: seen.append(b))
        unsubscribe()
        sm.transition(SessionState.CONNECTING)
        assert seen == []


class TestQuoting:
    @pytest.mark.parametrize(
        ("raw", "quoted"),
        [
            ("ventas", '"ventas"'),
            ('comer "cial"', '"comer ""cial"""'),
            ("año ñ", '"año ñ"'),
            ("a;DROP TABLE x", '"a;DROP TABLE x"'),
        ],
    )
    def test_identifier(self, raw, quoted):
        assert quote_identifier(raw) == quoted

    @pytest.mark.parametrize(
        ("raw", "quoted"),
        [
            (r"C:\Users\José\datos.duckdb", r"'C:\Users\José\datos.duckdb'"),
            ("O'Brien's.duckdb", "'O''Brien''s.duckdb'"),
            ("", "''"),
        ],
    )
    def test_literal(self, raw, quoted):
        assert quote_string_literal(raw) == quoted

    def test_rejects_empty_identifier_and_nul(self):
        with pytest.raises(GeoDuckError) as err:
            quote_identifier("")
        assert err.value.code is ErrorCode.INVALID_ARGUMENT
        with pytest.raises(GeoDuckError):
            quote_identifier("a\x00b")
        with pytest.raises(GeoDuckError):
            quote_string_literal("a\x00b")


class TestVersion:
    @pytest.mark.parametrize(
        ("text", "release", "pre"),
        [
            ("1.5.0", (1, 5, 0), False),
            ("2.0.0", (2, 0, 0), False),
            ("1.5", (1, 5, 0), False),
            ("2.1.0.dev42", (2, 1, 0), True),
            ("1.5.4rc1", (1, 5, 4), True),
            ("v1.5.6", (1, 5, 6), False),
        ],
    )
    def test_parse(self, text, release, pre):
        v = Version.parse(text)
        assert v.release() == release
        assert v.is_prerelease is pre

    def test_at_least(self):
        assert Version.parse("1.5.0").at_least(1, 5, 0)
        assert not Version.parse("1.4.9").at_least(1, 5, 0)
        assert Version.parse("2.0.0").at_least(1, 5, 4)
        assert not Version.parse("1.5.0rc1").at_least(1, 5, 0)

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            Version.parse("latest")


def test_read_summary_completed_only_when_exhausted():
    assert ReadSummary(10, 1, ReadOutcome.EXHAUSTED).completed
    assert not ReadSummary(10, 1, ReadOutcome.CANCELLED).completed
    assert not ReadSummary(10, 1, ReadOutcome.FAILED).completed


def _machine_at(state):
    sm = SessionStateMachine()
    path = {
        SessionState.READY: [SessionState.CONNECTING, SessionState.READY],
        SessionState.BUSY: [SessionState.CONNECTING, SessionState.READY, SessionState.BUSY],
    }[state]
    for target in path:
        sm.transition(target)
    return sm
