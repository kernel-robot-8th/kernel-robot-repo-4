import json

import pytest

from cobot_anomaly_monitor import replay_evidence as replay


def test_recording_isolated_epoch_and_original_frame_spacing(tmp_path, monkeypatch):
    rows = [dict(source_kind='model_output', frame_seq=n, capture_time_rel=n*.5,
                 stream_epoch=epoch, zones={'ZA': 'LOADED'})
            for epoch in ['raw', 'filtered'] for n in range(4)]
    path = tmp_path / 'frames.jsonl'
    path.write_text('\n'.join(map(json.dumps, rows)))
    frames = replay.recorded_frames(path, 'raw', 1, 2)
    sent = []
    monkeypatch.setattr(replay.time, 'sleep', lambda _: None)
    replay.play_recording(frames, sent.append)
    assert [r['frame_seq'] for r in sent] == [1, 2]
    assert sent[1]['capture_time'] - sent[0]['capture_time'] == .5
    assert sent[0]['recorded_epoch'] == 'raw'
    assert sent[0]['stream_epoch'] == sent[1]['stream_epoch'] != 'raw'
    path.write_text('\n'.join(map(json.dumps, [rows[1], rows[0]])))
    with pytest.raises(ValueError, match='역전'):
        replay.recorded_frames(path, 'raw', 0, 2)
