# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
팔 정차 위치 맞추기의 기준 화면 목록 (ROS 없는 순수 로직).

팔 모델은 위쪽 카메라 화면 속 자리로 학습됐다. 학습 때 화면(기준)을 관제 PC 폴더에 두면
팔 상세화면이 지금 위쪽 영상과 겹쳐 보고 어긋남을 잰다 (계산은 브라우저, arm_align.js).

폴더: <root>/<팔>/<이름>.jpg|.jpeg|.png, 설명은 같은 이름 + '.txt' 의 첫 줄 (없으면 파일 이름).
기준 화면은 omx_fleet/align_view.py --save-ref 로 뽑는다. 팔 폴더 이름은 omx_2 와 omx2 를 다 받는다.
"""

from pathlib import Path
import re

from cobot_control_center.arm_command_utils import interface_arm_id

REF_NAME_PATTERN = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}')
REF_SUFFIXES = ('.jpg', '.jpeg', '.png')
ARM_DIR_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,31}')
LABEL_MAX = 200
MEDIA_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}


def _arm_dirs(root, arm_id):
    """팔 이름 → 찾아볼 폴더들 (omx_2, omx2 순서, 겹치면 하나)."""
    if not ARM_DIR_PATTERN.fullmatch(arm_id or ''):
        raise ValueError(f'팔 이름 형식 오류: {arm_id!r}')
    name = interface_arm_id(arm_id)
    names = [name, name.replace('_', '')]
    return [Path(root).expanduser() / n for n in dict.fromkeys(names)]


def _inside(path, root):
    """링크를 따라간 실제 경로가 root 안인지."""
    try:
        path.resolve().relative_to(Path(root).expanduser().resolve())
    except ValueError:
        return False
    return True


def _label(image):
    note = image.with_name(image.name + '.txt')
    try:
        lines = note.read_text(errors='replace').splitlines()
    except OSError:
        return image.name
    text = lines[0].strip() if lines else ''
    return text[:LABEL_MAX] or image.name


def list_refs(root, arm_id):
    """그 팔의 기준 화면 [{name, label, size}] (이름 순). 폴더가 없으면 []."""
    refs = {}
    for folder in _arm_dirs(root, arm_id):
        if not folder.is_dir():
            continue
        for image in sorted(folder.iterdir()):
            if (image.name in refs or image.suffix.lower() not in REF_SUFFIXES
                    or not REF_NAME_PATTERN.fullmatch(image.name)
                    or not image.is_file() or not _inside(image, root)):
                continue
            refs[image.name] = {'name': image.name, 'label': _label(image),
                                'size': image.stat().st_size}
    return [refs[name] for name in sorted(refs)]


def ref_path(root, arm_id, name):
    """
    기준 화면 파일 경로와 media type. 이름이 틀리면 ValueError, 없으면 FileNotFoundError.

    이름은 폴더 구분자·'..' 를 받지 않고, 링크를 따라간 실제 파일도 root 안이어야 한다.
    """
    if (not isinstance(name, str) or not REF_NAME_PATTERN.fullmatch(name) or '..' in name
            or Path(name).suffix.lower() not in REF_SUFFIXES):
        raise ValueError(f'기준 화면 이름 형식 오류: {name!r}')
    for folder in _arm_dirs(root, arm_id):
        image = folder / name
        if image.is_file():
            if not _inside(image, root):
                raise ValueError(f'기준 화면이 폴더 밖을 가리킴: {name!r}')
            return image, MEDIA_TYPES[image.suffix.lower()]
    raise FileNotFoundError(f'{arm_id} 기준 화면 없음: {name}')
