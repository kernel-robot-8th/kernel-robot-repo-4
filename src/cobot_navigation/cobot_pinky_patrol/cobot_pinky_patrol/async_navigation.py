"""ROS 액션 Future를 관찰하며 접수·취소·종료를 구분하는 비동기 어댑터."""


class AsyncNavigation:
    """액션이 끝나기 전 새 목표를 허용하지 않는다. 상태는 executor 한 곳에서 바꾼다."""

    def __init__(self, client, make_goal, feedback=None):
        self.client = client
        self.make_goal = make_goal
        self.feedback = feedback
        self.busy = False
        self.result = None
        self.fault = ''
        self._generation = 0
        self._handle = None
        self._cancel_requested = False
        self._cancel_sent = False
        self._result_future = None

    def start(self, pose):
        """목표 접수도 기다리지 않는다. 예외는 물리 동작 미확정으로 남긴다."""
        if self.busy:
            raise RuntimeError('이전 Nav2 목표가 아직 종료되지 않았습니다')
        self.busy, self.result, self.fault = True, None, ''
        self._generation += 1
        generation = self._generation
        self._handle = None
        self._cancel_requested = self._cancel_sent = False
        try:
            future = self.client.send_goal_async(
                self.make_goal(pose),
                feedback_callback=lambda msg: self._feedback(generation, msg))
            future.add_done_callback(lambda done: self._accepted(generation, done))
        except Exception as error:
            self.fault = f'목표 전달 미확정: {error}'

    def _feedback(self, generation, message):
        if generation == self._generation and self.busy and self.feedback:
            self.feedback(message)

    def _accepted(self, generation, future):
        if generation != self._generation:
            return
        try:
            handle = future.result()
            if not handle.accepted:
                self._complete('FAILED')
                return
            self._handle = handle
            self._result_future = handle.get_result_async()
            self._result_future.add_done_callback(lambda done: self._finished(generation, done))
            if self._cancel_requested:
                self.cancel()
        except Exception as error:
            self.fault = f'목표 접수 미확정: {error}'

    def cancel(self):
        """접수 전 취소는 기억한다. 취소 ACK만으로 busy를 해제하지 않는다."""
        self._cancel_requested = True
        if not self.busy or self._handle is None or self._cancel_sent:
            return
        self._cancel_sent = True
        generation = self._generation
        try:
            future = self._handle.cancel_goal_async()
            future.add_done_callback(lambda done: self._cancelled(generation, done))
        except Exception as error:
            self.fault = f'취소 요청 미확정: {error}'

    def _cancelled(self, generation, future):
        if generation != self._generation or not self.busy:
            return
        try:
            response = future.result()
            if not response.goals_canceling:
                self.fault = '취소 거절: 원래 액션의 최종 결과 대기'
        except Exception as error:
            self.fault = f'취소 응답 미확정: {error}'

    def _finished(self, generation, future):
        if generation != self._generation:
            return
        try:
            status = future.result().status
            # action_msgs/GoalStatus의 종료 상태만 새 목표를 허용한다.
            if status == 4:
                self._complete('SUCCEEDED')
            elif status in (5, 6):
                self._complete('CANCELED' if status == 5 else 'FAILED')
            else:
                self.fault = f'종료 여부를 확인할 수 없는 액션 상태: {status}'
        except Exception as error:
            self.fault = f'주행 결과 미확정: {error}'

    def _complete(self, result):
        self.busy, self.result, self.fault = False, result, ''
        self._handle = None

    def pop_result(self):
        """결과는 상태 기계가 한 번만 소비한다."""
        result, self.result = self.result, None
        return result
