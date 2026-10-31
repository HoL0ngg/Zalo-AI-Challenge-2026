"""Data-parallel runner: one `datamate run` process per GPU, each on a disjoint set of businesses.

The pipeline is still sequential inside a process, so this is the cheapest way to use both GPUs today
(each process owns one card via CUDA_VISIBLE_DEVICES, tensor_parallel_size stays 1). The split is by
business so every process keeps its own ingest cache and prompt-prefix locality, and it is a pure
function of the question file (no wall-clock), so two runs shard identically.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from datamate.io.question_reader import read_records
from datamate.io.submission_writer import append_json


def shard_businesses(questions: list[dict], shards: int) -> list[list[str]]:
    """Greedy balance by question count; ties broken by business id so the result is deterministic."""
    counts: dict[str, int] = {}
    for record in questions:
        counts[record["business_id"]] = counts.get(record["business_id"], 0) + 1
    result: list[list[str]] = [[] for _ in range(shards)]
    load = [0] * shards
    for business in sorted(counts, key=lambda b: (-counts[b], b)):
        target = min(range(shards), key=lambda i: (load[i], i))
        result[target].append(business)
        load[target] += counts[business]
    return result


def write_shard(data_dir: Path, target: Path, questions: list[dict], businesses: list[str]) -> None:
    """Copy (not symlink: the loader rejects links that leave the package) the files one shard needs."""
    target.mkdir(parents=True)
    (target / "data").mkdir()
    for business in businesses:
        shutil.copytree(data_dir / "data" / business, target / "data" / business)
    for name in ("rulebook.md", "calendar.csv"):
        if (data_dir / name).exists():
            shutil.copy2(data_dir / name, target / name)
    owned = set(businesses)
    with (target / "questions.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for record in questions:
            if record["business_id"] in owned:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def merge(order: list[str], shard_results: list[Path], result_dir: Path) -> dict:
    """Rebuild submission.jsonl and logs/questions.jsonl in the original question order."""
    answers: dict[str, dict] = {}
    logs: dict[str, dict] = {}
    for directory in shard_results:
        for name, store in (("submission.jsonl", answers), ("logs/questions.jsonl", logs)):
            path = directory / name
            if path.exists():
                for record in read_records(path):
                    store[record["id"]] = record
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "logs").mkdir(exist_ok=True)
    for path in (result_dir / "submission.jsonl", result_dir / "logs" / "questions.jsonl"):
        path.unlink(missing_ok=True)
    for question_id in order:
        if question_id in answers:
            append_json(result_dir / "submission.jsonl", answers[question_id])
        if question_id in logs:
            append_json(result_dir / "logs" / "questions.jsonl", logs[question_id])
    return {"questions": len(order), "answered_rows": len(answers),
            "missing": [i for i in order if i not in answers]}


def run_data_parallel(data_dir: Path, result_dir: Path, config: Path, gpus: list[str]) -> dict:
    data_dir, result_dir = data_dir.resolve(), result_dir.resolve()
    if result_dir.is_relative_to(data_dir):
        raise ValueError("Output must be outside read-only input package")
    questions = list(read_records(data_dir / "questions.jsonl"))
    plan = shard_businesses(questions, len(gpus))
    scratch = result_dir / ".shards"
    shutil.rmtree(scratch, ignore_errors=True)
    started = time.monotonic()
    processes = []
    for index, (gpu, businesses) in enumerate(zip(gpus, plan)):
        if not businesses:
            continue
        inputs, outputs = scratch / f"in_{index}", scratch / f"out_{index}"
        write_shard(data_dir, inputs, questions, businesses)
        # The child must import this same source tree even when the package is not pip-installed.
        source = str(Path(__file__).resolve().parents[2])
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpu,
                   PYTHONPATH=os.pathsep.join(filter(None, [source, os.environ.get("PYTHONPATH")])))
        log = (scratch / f"shard_{index}.log").open("w", encoding="utf-8")
        command = [sys.executable, "-m", "datamate.runtime.cli", "run", "--config", str(config),
                   "--data-dir", str(inputs), "--result-dir", str(outputs)]
        processes.append((index, gpu, businesses, outputs, log,
                          subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)))
    shards = []
    for index, gpu, businesses, outputs, log, process in processes:
        code = process.wait()
        log.close()
        shutil.rmtree(scratch / f"in_{index}", ignore_errors=True)  # input copies are not evidence; keep logs/outputs
        shards.append({"shard": index, "gpu": gpu, "businesses": businesses, "exit_code": code,
                       "wall_seconds": round(time.monotonic() - started, 1)})
    summary = merge([r["id"] for r in questions], [p[3] for p in processes], result_dir)
    summary.update(shards=shards, total_wall_seconds=round(time.monotonic() - started, 1))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(prog="datamate-dp", description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    parser.add_argument("--gpus", default="0,1", help="comma-separated CUDA device ids, one process each")
    args = parser.parse_args()
    summary = run_data_parallel(args.data_dir, args.result_dir, args.config,
                                [g.strip() for g in args.gpus.split(",") if g.strip()])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if any(s["exit_code"] for s in summary["shards"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
