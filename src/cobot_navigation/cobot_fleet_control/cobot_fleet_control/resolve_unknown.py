"""현장 확인을 마친 UNKNOWN 작업 한 건을 수동으로 해제한다."""

import argparse
from pathlib import Path
import re

from .repository import SqliteRepository


def main(args=None):
    """관제 서버가 중지된 상태에서만 저장된 작업을 실패 확정한다."""
    parser = argparse.ArgumentParser(description='UNKNOWN 작업의 로봇 예약 해제')
    parser.add_argument('--db', required=True, help='관제 SQLite 파일 경로')
    parser.add_argument('--command-id', required=True)
    parser.add_argument('--robot-id', required=True)
    parser.add_argument('--operator', required=True, help='현장 확인자')
    parser.add_argument('--reason', required=True, help='해제 사유')
    parser.add_argument('--confirm-stopped', action='store_true',
                        help='로봇의 물리 정지와 기존 작업 종료를 확인함')
    options = parser.parse_args(args)
    if not options.confirm_stopped:
        parser.error('로봇 정지 확인 후 --confirm-stopped를 지정하세요')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', options.command_id):
        parser.error('command_id 형식 오류')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', options.robot_id):
        parser.error('robot_id 형식 오류')
    operator = options.operator.strip()
    reason = options.reason.strip()
    if not operator or len(operator) > 80 or not reason or len(reason) > 300:
        parser.error('operator는 1~80자, reason은 1~300자여야 합니다')
    path = Path(options.db).expanduser()
    if not path.is_file():
        parser.error(f'관제 DB가 없습니다: {path}')
    try:
        repository = SqliteRepository(str(path))
    except RuntimeError as error:
        parser.error(str(error))
    try:
        row = repository.resolve_unknown(options.command_id, options.robot_id,
                                         operator, reason)
    except ValueError as error:
        parser.error(str(error))
    finally:
        repository.close()
    print(f"{row['command_id']} ({row['robot_id']}): {row['state']} - {row['detail']}")


if __name__ == '__main__':
    main()
