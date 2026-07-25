"""Build a (natural-language instruction -> Kubernetes YAML manifest) SFT dataset
from the official Kubernetes documentation.

Usage:
    python build_dataset.py --source-dir /path/to/k8s-website-sparse --output-dir ./data
"""

import argparse
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SYSTEM_PROMPT = (
    "You are a Kubernetes expert. Given a description, output the "
    "corresponding Kubernetes manifest as YAML."
)

FENCE_OPEN_RE = re.compile(r"^```\s*(yaml|yml)\s*$", re.IGNORECASE)
FENCE_CLOSE_RE = re.compile(r"^```\s*$")

HEADER_RE = re.compile(r"^#{1,6}\s")
HTML_COMMENT_RE = re.compile(r"^<!--.*-->?\s*$")
FRONT_MATTER_RE = re.compile(r"^---\s*$")
SHORTCODE_ONLY_RE = re.compile(r"^\{\{[<%].*[%>]\}\}\s*$")

MIN_INSTRUCTION_LEN = 15
MAX_INSTRUCTION_LEN = 800
REQUIRED_KEYS = {"apiVersion", "kind", "metadata"}

LOW_INFORMATION_PATTERNS = (
    re.compile(r"^(where\s+)?(the|your)\s+output\s+is\s+similar\s+to(\s+this)?:?$", re.IGNORECASE),
    re.compile(r"^\d+\.\s*create\s+the\s+manifest:?$", re.IGNORECASE),
)

ANTI_PATTERN_MARKERS = (
    "anti-pattern",
    "antipattern",
    "not recommended",
    "don't do this",
    "do not do this",
    "avoid this",
    "avoid doing this",
    "bad example",
    "bad practice",
    "should not use",
    "shouldn't use",
    "do not use this",
    "don't use this",
    "this is discouraged",
    "is discouraged",
    "not a good idea",
    "incorrect example",
    "wrong way",
)


@dataclass
class Candidate:
    path: Path
    instruction: str
    yaml_text: str


@dataclass
class Stats:
    total_fences: int = 0
    parse_failed: int = 0
    missing_required_keys: int = 0
    instruction_too_short: int = 0
    instruction_too_long: int = 0
    instruction_missing: int = 0
    low_information_excluded: int = 0
    anti_pattern_excluded: int = 0
    duplicates: int = 0
    kept: int = 0


def is_boundary_line(stripped: str) -> bool:
    """Lines that stop backward prose collection: headers, fences, comments,
    front-matter delimiters, and standalone Hugo shortcodes."""
    return (
        HEADER_RE.match(stripped) is not None
        or stripped.startswith("```")
        or HTML_COMMENT_RE.match(stripped) is not None
        or FRONT_MATTER_RE.match(stripped) is not None
        or SHORTCODE_ONLY_RE.match(stripped) is not None
    )


def extract_preceding_instruction(lines: list[str], fence_start_idx: int) -> str:
    """Walk backwards from the opening fence, collecting the immediately
    preceding paragraph of prose. Stops at a blank line (paragraph
    boundary), a header, another code fence, an HTML comment, front-matter,
    or a standalone shortcode line."""
    i = fence_start_idx - 1
    while i >= 0 and lines[i].strip() == "":
        i -= 1

    collected: list[str] = []
    while i >= 0:
        stripped = lines[i].strip()
        if stripped == "" or is_boundary_line(stripped):
            break
        collected.append(stripped)
        i -= 1

    collected.reverse()
    return " ".join(collected).strip()


def extract_following_text(lines: list[str], fence_end_idx: int, max_lines: int = 6) -> str:
    """Grab a small window of text after the closing fence, used only as
    extra context for the anti-pattern heuristic."""
    i = fence_end_idx + 1
    collected: list[str] = []
    while i < len(lines) and len(collected) < max_lines:
        stripped = lines[i].strip()
        if stripped == "" and collected:
            break
        if is_boundary_line(stripped):
            break
        if stripped:
            collected.append(stripped)
        i += 1
    return " ".join(collected)


def looks_like_anti_pattern(context_text: str) -> bool:
    lowered = context_text.lower()
    return any(marker in lowered for marker in ANTI_PATTERN_MARKERS)


def is_low_information(instruction: str) -> bool:
    """Boilerplate lead-ins such as 'The output is similar to:' reference an
    antecedent command with no content of their own and don't actually
    describe the manifest -- filter these out even though they pass the
    plain length check."""
    return any(pattern.match(instruction.strip()) for pattern in LOW_INFORMATION_PATTERNS)


def find_yaml_fences(lines: list[str]) -> list[tuple[int, int]]:
    """Return (start_idx, end_idx) line-index pairs for each ```yaml fence,
    where start/end point at the fence marker lines themselves."""
    fences = []
    i = 0
    while i < len(lines):
        if FENCE_OPEN_RE.match(lines[i].strip()):
            start = i
            j = i + 1
            while j < len(lines) and not FENCE_CLOSE_RE.match(lines[j].strip()):
                j += 1
            if j < len(lines):
                fences.append((start, j))
                i = j + 1
                continue
        i += 1
    return fences


def parse_manifest_documents(yaml_text: str) -> list[dict] | None:
    """Parse a (possibly multi-document) YAML block. Returns the list of
    non-empty documents, or None if parsing fails or any document is not a
    dict (e.g. a partial snippet, kubectl output, or a plain scalar)."""
    try:
        docs = [d for d in yaml.safe_load_all(yaml_text) if d is not None]
    except yaml.YAMLError:
        return None
    if not docs:
        return None
    if not all(isinstance(d, dict) for d in docs):
        return None
    return docs


def has_required_manifest_keys(docs: list[dict]) -> bool:
    return all(REQUIRED_KEYS.issubset(doc.keys()) for doc in docs)


def collect_candidates(md_files: list[Path], stats: Stats) -> list[Candidate]:
    candidates = []
    for path in md_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        for start, end in find_yaml_fences(lines):
            stats.total_fences += 1
            yaml_text = "\n".join(lines[start + 1:end]).strip("\n")

            docs = parse_manifest_documents(yaml_text)
            if docs is None:
                stats.parse_failed += 1
                continue
            if not has_required_manifest_keys(docs):
                stats.missing_required_keys += 1
                continue

            instruction = extract_preceding_instruction(lines, start)
            if not instruction:
                stats.instruction_missing += 1
                continue
            if len(instruction) < MIN_INSTRUCTION_LEN:
                stats.instruction_too_short += 1
                continue
            if len(instruction) > MAX_INSTRUCTION_LEN:
                stats.instruction_too_long += 1
                continue
            if is_low_information(instruction):
                stats.low_information_excluded += 1
                continue

            context = f"{instruction} {extract_following_text(lines, end)}"
            if looks_like_anti_pattern(context):
                stats.anti_pattern_excluded += 1
                continue

            candidates.append(Candidate(path=path, instruction=instruction, yaml_text=yaml_text))
    return candidates


def dedupe(candidates: list[Candidate], stats: Stats) -> list[Candidate]:
    seen: set[str] = set()
    deduped = []
    for candidate in candidates:
        key = candidate.yaml_text.strip()
        if key in seen:
            stats.duplicates += 1
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def to_chat_row(candidate: Candidate) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": candidate.instruction},
            {
                "role": "assistant",
                "content": f"```yaml\n{candidate.yaml_text}\n```",
            },
        ]
    }


def write_jsonl(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("/tmp/k8s-website-sparse"),
        help="Sparse checkout of kubernetes/website (must contain content/en/docs/...)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory to write train.jsonl / eval.jsonl into",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--eval-fraction", type=float, default=0.1)
    args = parser.parse_args()

    subtrees = ["concepts", "tasks", "tutorials"]
    md_files = []
    for subtree in subtrees:
        md_files.extend(sorted((args.source_dir / "content/en/docs" / subtree).rglob("*.md")))

    stats = Stats()
    candidates = collect_candidates(md_files, stats)
    deduped = dedupe(candidates, stats)
    stats.kept = len(deduped)

    rows = [to_chat_row(c) for c in deduped]
    random.Random(args.seed).shuffle(rows)

    eval_size = max(1, round(len(rows) * args.eval_fraction))
    eval_rows = rows[:eval_size]
    train_rows = rows[eval_size:]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(train_rows, args.output_dir / "train.jsonl")
    write_jsonl(eval_rows, args.output_dir / "eval.jsonl")

    print(f"Markdown files scanned:        {len(md_files)}")
    print(f"Total ```yaml/```yml fences:   {stats.total_fences}")
    print(f"  - YAML parse failed:         {stats.parse_failed}")
    print(f"  - missing required keys:     {stats.missing_required_keys}")
    print(f"  - instruction missing:       {stats.instruction_missing}")
    print(f"  - instruction too short:     {stats.instruction_too_short}")
    print(f"  - instruction too long:      {stats.instruction_too_long}")
    print(f"  - low-information excluded:  {stats.low_information_excluded}")
    print(f"  - anti-pattern excluded:     {stats.anti_pattern_excluded}")
    print(f"  - duplicate YAML:            {stats.duplicates}")
    print(f"Kept pairs:                    {stats.kept}")
    print(f"Train / eval split:            {len(train_rows)} / {len(eval_rows)}")


if __name__ == "__main__":
    main()
