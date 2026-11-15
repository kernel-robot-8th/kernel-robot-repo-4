"""정지 해제는 발행과 확인을 분리한다. 재시작·만료 시 영속 보류를 유지한다."""


def require_stopped(service, robot):
    """오래된 상태나 취소 중인 로봇에는 복구 명령을 보내지 않는다."""
    status = service.health.get(robot, {}).get('status', {})
    if not service._fresh(robot):
        raise ValueError('로봇 상태 또는 배터리 수신이 오래됐거나 없습니다')
    if status.get('busy') is not False:
        raise ValueError('로봇 정지·취소 완료 미확인 (busy=false 필요)')
    if (status.get('central_controlled') is not True
            or not isinstance(status.get('central_latched'), bool)):
        raise ValueError('중앙 제어·정지 래치 상태 확인 필요')
    return status


class ControlRelease:
    """같은 로봇 부팅의 새 상태를 받은 뒤에만 UNKNOWN 명령과 보류를 정리한다."""

    def __init__(self, service):
        self.service = service
        self.pending = {}
        for robot, reason in service.store.holds().items():
            if reason == 'RESET_PENDING':
                service.store.hold(robot, 'RESET_UNCONFIRMED')

    def request(self, robot, note, route=None):
        service = self.service
        status = require_stopped(service, robot)
        if robot in self.pending:
            return dict(robot_id=robot, released=False, reset_pending=True)
        # 요청 전부터 유지하므로 발행 예외나 관제 재시작으로 예약이 풀리지 않는다.
        service.store.hold(robot, 'RESET_PENDING')
        commands = service.fleet.repository.active_commands(robot)
        for command_id in commands:
            service.fleet.quarantine(command_id, '정지 해제 응답 대기')
        reset_id = (service.gateway.release(robot, route) if route
                    else service.gateway.release(robot))
        if not isinstance(reset_id, str) or not reset_id:
            raise RuntimeError('정지 해제 명령 ID 누락: 보류 유지')
        self.pending[robot] = dict(
            deadline=service.clock() + service.config['stale_sec'],
            boot_id=status.get('boot_id'), reset_id=reset_id, commands=commands, note=note)
        service.store.event(dict(type='control_release_requested', robot_id=robot,
                                 reset_id=reset_id))
        return dict(robot_id=robot, released=False, reset_pending=True)

    def observe(self, robot):
        """요청 뒤 수신한 상태에서만 호출한다. 오래된 마지막 상태를 타이머로 승인하지 않는다."""
        pending = self.pending.get(robot)
        if pending is None:
            return
        service = self.service
        status = service.health[robot]['status']
        if (service.clock() >= pending['deadline']
                or status.get('boot_id') != pending['boot_id']):
            self.cancel(robot)
            return
        if (not service._fresh(robot) or status.get('busy') is not False
                or status.get('control_reset_id') != pending['reset_id']
                or status.get('central_controlled') is not True
                or status.get('central_latched') is not False):
            return
        repository = service.fleet.repository
        for command_id in pending['commands']:
            if repository.get(command_id)['state'] == 'UNKNOWN':
                repository.transition(command_id, 'FAILED', pending['note'])
        service.store.clear_hold(robot)
        service.store.event(dict(type='control_released', robot_id=robot))
        del self.pending[robot]

    def cancel(self, robot):
        """새 정지·통신 단절·만료 시 진행 중인 해제만 폐기한다. 보류는 지우지 않는다."""
        if self.pending.pop(robot, None) is not None:
            if self.service.store.holds().get(robot) == 'RESET_PENDING':
                self.service.store.hold(robot, 'RESET_UNCONFIRMED')
            self.service.store.event(dict(type='control_release_unconfirmed', robot_id=robot))

    def tick(self):
        for robot, pending in list(self.pending.items()):
            if self.service.clock() >= pending['deadline']:
                self.cancel(robot)
