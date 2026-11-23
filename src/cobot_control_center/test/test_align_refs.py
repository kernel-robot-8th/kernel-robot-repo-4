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


"""정차 위치 맞추기 기준 화면 목록 시험 (align_refs_utils)."""

import os

from cobot_control_center.align_refs_utils import list_refs, ref_path
import pytest


def make_refs(tmp_path):
    arm = tmp_path / 'omx_2'
    arm.mkdir()
    (arm / 'pick_ep0.jpg').write_bytes(b'\xff\xd8jpg')
    (arm / 'pick_ep0.jpg.txt').write_text('omx_1031 ep0 f0/412 (start)\nignored\n')
    (arm / 'load.png').write_bytes(b'\x89PNGpng')
    (arm / 'notes.txt').write_text('not an image')
    (arm / '.hidden.jpg').write_bytes(b'x')
    return arm


def test_list_refs_names_labels_sorted(tmp_path):
    make_refs(tmp_path)
    refs = list_refs(tmp_path, 'omx_2')
    assert [r['name'] for r in refs] == ['load.png', 'pick_ep0.jpg']
    assert refs[0]['label'] == 'load.png'
    assert refs[1]['label'] == 'omx_1031 ep0 f0/412 (start)'
    assert refs[1]['size'] == 5


def test_list_refs_accepts_folder_without_underscore(tmp_path):
    (tmp_path / 'omx2').mkdir()
    (tmp_path / 'omx2' / 'a.jpg').write_bytes(b'x')
    assert [r['name'] for r in list_refs(tmp_path, 'omx_2')] == ['a.jpg']
    assert [r['name'] for r in list_refs(tmp_path, 'omx2')] == ['a.jpg']


def test_list_refs_missing_folder_is_empty(tmp_path):
    assert list_refs(tmp_path, 'omx_3') == []


def test_list_refs_rejects_bad_arm(tmp_path):
    with pytest.raises(ValueError):
        list_refs(tmp_path, '../etc')


def test_ref_path_finds_file_and_type(tmp_path):
    arm = make_refs(tmp_path)
    assert ref_path(tmp_path, 'omx_2', 'pick_ep0.jpg') == (arm / 'pick_ep0.jpg', 'image/jpeg')
    assert ref_path(tmp_path, 'omx_2', 'load.png')[1] == 'image/png'


@pytest.mark.parametrize('name', ['../x.jpg', 'a/b.jpg', '..jpg', 'notes.txt', '.hidden.jpg', ''])
def test_ref_path_rejects_bad_names(tmp_path, name):
    make_refs(tmp_path)
    with pytest.raises(ValueError):
        ref_path(tmp_path, 'omx_2', name)


def test_ref_path_missing(tmp_path):
    make_refs(tmp_path)
    with pytest.raises(FileNotFoundError):
        ref_path(tmp_path, 'omx_2', 'none.jpg')


def test_link_outside_root_is_hidden_and_rejected(tmp_path):
    root = tmp_path / 'refs'
    arm = root / 'omx_1'
    arm.mkdir(parents=True)
    outside = tmp_path / 'secret.jpg'
    outside.write_bytes(b'x')
    os.symlink(outside, arm / 'leak.jpg')
    assert list_refs(root, 'omx_1') == []
    with pytest.raises(ValueError):
        ref_path(root, 'omx_1', 'leak.jpg')
