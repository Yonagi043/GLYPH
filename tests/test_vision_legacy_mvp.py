import json
from pathlib import Path

from PIL import Image
import pytest

from glyph_features.vision_system.legacy_mvp import (
    LegacyMVPError,
    _atomic_write_json,
    main as legacy_main,
    validate_legacy_weights,
)


ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"weights": {"balance": -0.1}}, "WEIGHT_NEGATIVE"),
        ({"weights": {"unknown": 1.0}}, "WEIGHT_UNKNOWN_KEY"),
        ({"weights": {"balance": 0.0}}, "WEIGHT_ALL_ZERO"),
        ('{"weights":{"balance":NaN}}', "WEIGHT_NONFINITE"),
        ('{"weights":{"balance":Infinity}}', "WEIGHT_NONFINITE"),
    ],
)
def test_legacy_weights_reject_invalid_values(tmp_path, payload, code):
    weights = tmp_path / "weights.json"
    if isinstance(payload, str):
        weights.write_text(payload, encoding="utf-8")
    else:
        weights.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(LegacyMVPError, match=code):
        validate_legacy_weights(weights)


def test_legacy_batch_uses_collision_safe_keys_and_no_scores(tmp_path):
    inputs = tmp_path / "inputs"
    for directory, offset in ((inputs / "first", 2), (inputs / "second", 7)):
        directory.mkdir(parents=True)
        image = Image.new("L", (16, 16), 255)
        for x in range(offset, offset + 4):
            for y in range(4, 12):
                image.putpixel((x, y), 0)
        image.save(directory / "same.png")
    output = tmp_path / "results"

    exit_code = legacy_main([
        "--workspace-root", str(ROOT),
        "--input-dir", str(inputs),
        "--output", str(output),
        "--representation", "A_layout",
    ])

    assert exit_code == 0
    result_files = sorted(output.glob("*/result.json"))
    assert len(result_files) == 2
    assert result_files[0].parent.name != result_files[1].parent.name
    for result_file in result_files:
        payload = json.loads(result_file.read_text())
        assert "total_score" not in payload
        assert "dimension_scores" not in payload
        assert not payload["source_ref"].startswith("/")
        assert payload["joint_analysis_eligible"] is False


def test_legacy_partial_failure_is_nonzero_and_retained(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    Image.new("L", (12, 12), 255).save(inputs / "valid.png")
    (inputs / "broken.png").write_bytes(b"not an image")
    output = tmp_path / "results"

    exit_code = legacy_main([
        "--workspace-root", str(ROOT),
        "--input-dir", str(inputs),
        "--output", str(output),
        "--representation", "A_layout",
    ])

    assert exit_code == 1
    failures = [json.loads(line) for line in (output / "failures.jsonl").read_text().splitlines()]
    assert failures == [{
        "failure_code": "IMAGE_DECODE_FAILED",
        "message": "cannot decode broken.png",
        "source_ref": "broken.png",
    }]


def test_legacy_atomic_write_failure_propagates(tmp_path, monkeypatch):
    def fail_replace(source, destination):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("glyph_features.vision_system.legacy_mvp.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated disk failure"):
        _atomic_write_json(tmp_path / "result.json", {"ok": True})