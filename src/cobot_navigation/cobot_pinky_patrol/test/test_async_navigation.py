"""접수 전 취소·취소 거절·지연 콜백에서 목표가 겹치지 않는지 검증한다."""

from types import SimpleNamespace

from cobot_pinky_patrol.async_navigation import AsyncNavigation
import pytest


class Future:
    """완료된 상태에서만 결과를 읽을 수 있는 테스트 Future."""

    def __init__(self):
        self.callbacks = []
        self.value = None
        self.error = None
        self.finished = False

    def add_done_callback(self, callback):
        self.callbacks.append(callback)
        if self.finished:
            callback(self)

    def result(self):
        assert self.finished, '미완료 Future를 동기로 기다리면 안 됩니다'
        if self.error:
            raise self.error
        return self.value

    def complete(self, value=None, error=None):
        self.value, self.error, self.finished = value, error, True
        for callback in self.callbacks:
            callback(self)


class Client:
    """목표 접수·결과·취소 응답을 독립적으로 전달한다."""

    def __init__(self):
        self.sent = []
        self.cancel_count = 0

    def send_goal_async(self, goal, feedback_callback):
        self.acceptance, self.result, self.cancellation = Future(), Future(), Future()
        self.sent.append(goal)
        self.feedback_callback = feedback_callback
        return self.acceptance

    def accept(self, accepted=True):
        self.acceptance.complete(SimpleNamespace(
            accepted=accepted, get_result_async=lambda: self.result,
            cancel_goal_async=self.cancel))

    def cancel(self):
        self.cancel_count += 1
        return self.cancellation


def test_cancel_before_accept_waits_for_terminal_result():
    client = Client()
    nav = AsyncNavigation(client, lambda pose: pose)
    nav.start((1, 2))
    nav.cancel()
    assert client.cancel_count == 0
    client.accept()
    assert client.cancel_count == 1
    client.cancellation.complete(SimpleNamespace(goals_canceling=[object()]))
    assert nav.busy
    with pytest.raises(RuntimeError):
        nav.start((3, 4))
    client.result.complete(SimpleNamespace(status=5))
    assert not nav.busy and nav.pop_result() == 'CANCELED'


def test_cancel_rejected_and_result_lost_stays_reserved():
    client = Client()
    nav = AsyncNavigation(client, lambda pose: pose)
    nav.start((1, 2))
    client.accept()
    nav.cancel()
    client.cancellation.complete(SimpleNamespace(goals_canceling=[]))
    assert nav.busy and '취소 거절' in nav.fault
    client.result.complete(error=RuntimeError('connection lost'))
    assert nav.busy and nav.pop_result() is None


@pytest.mark.parametrize('status,expected', [(4, 'SUCCEEDED'), (5, 'CANCELED'), (6, 'FAILED')])
def test_terminal_status(status, expected):
    client = Client()
    nav = AsyncNavigation(client, lambda pose: pose)
    nav.start((1, 2))
    client.accept()
    client.result.complete(SimpleNamespace(status=status))
    assert not nav.busy and nav.pop_result() == expected
    assert nav.pop_result() is None


def test_old_feedback_and_cancel_response_do_not_overwrite_new_goal():
    client = Client()
    feedback = []
    nav = AsyncNavigation(client, lambda pose: pose, feedback.append)
    nav.start((1, 2))
    client.accept()
    nav.cancel()
    old_cancel, old_feedback = client.cancellation, client.feedback_callback
    client.result.complete(SimpleNamespace(status=4))
    nav.pop_result()
    nav.start((3, 4))
    old_feedback('old')
    old_cancel.complete(error=RuntimeError('late failure'))
    assert feedback == [] and nav.fault == '' and nav.busy


def test_rejected_goal_and_unknown_result():
    client = Client()
    nav = AsyncNavigation(client, lambda pose: pose)
    nav.start((1, 2))
    client.accept(False)
    assert not nav.busy and nav.pop_result() == 'FAILED'
    nav.start((3, 4))
    client.accept()
    client.result.complete(SimpleNamespace(status=0))
    assert nav.busy and nav.fault
