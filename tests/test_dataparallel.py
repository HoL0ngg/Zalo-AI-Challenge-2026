import json
import shutil
from pathlib import Path

from datamate.io.question_reader import read_records
from datamate.runtime.dataparallel import run_data_parallel, shard_businesses

SAMPLE = Path("data/samples")


def questions(counts: dict[str, int]) -> list[dict]:
    return [{"id": f"{b}-{i}", "business_id": b} for b, n in counts.items() for i in range(n)]


def test_shard_is_balanced_deterministic_and_disjoint():
    records = questions({"a": 5, "b": 4, "c": 3, "d": 3, "e": 1})
    first = shard_businesses(records, 2)
    assert first == shard_businesses(list(reversed(records)), 2)
    assert sorted(sum(first, [])) == ["a", "b", "c", "d", "e"]
    sizes = [sum(1 for r in records if r["business_id"] in s) for s in first]
    assert abs(sizes[0] - sizes[1]) <= 1


def test_more_shards_than_businesses_leaves_empty_shards():
    assert shard_businesses(questions({"a": 2}), 3) == [["a"], [], []]


def test_two_process_run_matches_single_run(tmp_path):
    # Two businesses built from the sample package; the mock backend needs no GPU.
    package = tmp_path / "package"
    shutil.copytree(SAMPLE, package)
    shutil.copytree(package / "data" / "shop", package / "data" / "shop2")
    rows = list(read_records(SAMPLE / "questions.jsonl"))
    extra = [dict(r, id=r["id"] + "-b", business_id="shop2") for r in rows]
    with (package / "questions.jsonl").open("w", encoding="utf-8") as stream:
        for record in rows + extra:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = run_data_parallel(package, tmp_path / "dp", Path("configs/default.yaml"), ["0", "1"])
    assert [s["exit_code"] for s in summary["shards"]] == [0, 0]
    assert summary["missing"] == []

    merged = list(read_records(tmp_path / "dp" / "submission.jsonl"))
    assert [r["id"] for r in merged] == [r["id"] for r in rows + extra]
    by_id = {r["id"]: r for r in merged}
    for record in rows:  # the copy answers exactly like the original business
        assert {k: v for k, v in by_id[record["id"] + "-b"].items() if k != "id"} == \
               {k: v for k, v in by_id[record["id"]].items() if k != "id"}
    assert len(list(read_records(tmp_path / "dp" / "logs" / "questions.jsonl"))) == len(merged)
