"""관제 BT: 한 번 전달하고 일치하는 로봇의 작업 종료를 비동기로 기다린다."""

import py_trees


class Dispatch(py_trees.behaviour.Behaviour):
    """memory Sequence의 첫 단계. RUNNING 이후에는 다시 호출하지 않는다."""

    def __init__(self, command, repository, gateway):
        super().__init__('로봇 명령 전달')
        self.command = command
        self.repository = repository
        self.gateway = gateway

    def update(self):
        """발행 직전 상태를 저장해 장애 이후 불명 작업을 재실행하지 않는다."""
        self.repository.transition(self.command.command_id, 'RUNNING')
        self.gateway.send(self.command.robot_id, self.command.wire())
        self.feedback_message = 'ROS 명령 발행 완료 · 실제 도착은 결과 대기에서 확인'
        return py_trees.common.Status.SUCCESS


class AwaitResult(py_trees.behaviour.Behaviour):
    """tick은 블로킹하지 않고 수신 콜백이 기록한 결과만 읽는다."""

    def __init__(self, command, repository, clock):
        super().__init__('작업 종료 확인')
        self.command = command
        self.repository = repository
        self.clock = clock
        self.deadline = clock() + command.timeout_sec
        self.result = None

    def update(self):
        """통신 타임아웃을 물리 정지 또는 실패 확정으로 간주하지 않는다."""
        if self.result is not None:
            state = 'SUCCEEDED' if self.result['state'] == 'DONE' else 'FAILED'
            self.feedback_message = '로봇 정리 완료: ' + self.result['state']
            self.repository.transition(self.command.command_id, state,
                                       self.result.get('detail', ''))
            return (py_trees.common.Status.SUCCESS if state == 'SUCCEEDED'
                    else py_trees.common.Status.FAILURE)
        if self.clock() >= self.deadline:
            self.feedback_message = '응답 시간 초과 · 물리 동작 미확정 · 로봇 예약 유지'
            self.repository.transition(self.command.command_id, 'UNKNOWN',
                                       '응답 시간 초과: 로봇 점유 유지')
            return py_trees.common.Status.FAILURE
        self.feedback_message = '같은 명령 ID의 task_finished=true 응답 대기'
        return py_trees.common.Status.RUNNING


def build_tree(command, repository, gateway, clock):
    """새 업무 단계는 개별 Behaviour로 확장한다."""
    result = AwaitResult(command, repository, clock)
    root = py_trees.composites.Sequence(
        name='관제 작업', memory=True,
        children=[Dispatch(command, repository, gateway), result])
    return py_trees.trees.BehaviourTree(root), result
