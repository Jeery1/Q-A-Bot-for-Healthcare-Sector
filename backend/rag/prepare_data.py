"""
Prepare Huatuo26M-Lite dataset for RAG.
Downloads from HuggingFace and builds ChromaDB index.

Usage:
    cd backend
    python -m rag.prepare_data                     # default: 50000 samples
    python -m rag.prepare_data --samples 30000      # custom sample size
    python -m rag.prepare_data --input data.jsonl   # from local JSON/JSONL file

Env vars: HF_TOKEN (HuggingFace access token, if dataset requires auth)
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_PERSIST_DIR = str(BASE_DIR / "data" / "healthcare_rag")
DEFAULT_SAMPLES = 50000

# Huatuo26M-Lite: publicly accessible lite version, no auth required
# https://huggingface.co/datasets/FreedomIntelligence/Huatuo26M-Lite
HF_DATASET_NAME = "FreedomIntelligence/Huatuo26M-Lite"


def load_from_huggingface(sample_size: int, hf_token: str = "") -> list[dict]:
    try:
        from datasets import load_dataset
    except ImportError:
        logger.error("datasets not installed. Run: pip install datasets")
        sys.exit(1)

    token = hf_token or os.getenv("HF_TOKEN", "")

    logger.info(f"Loading {HF_DATASET_NAME} from HuggingFace (streaming, sampling {sample_size})...")
    try:
        ds = load_dataset(
            HF_DATASET_NAME, split="train",
            streaming=True, token=token or None,
        )
    except Exception as e:
        logger.error(f"HuggingFace load failed: {e}")
        logger.error(
            "If the dataset requires authentication:\n"
            "  1. Visit https://huggingface.co/settings/tokens to create a token\n"
            "  2. Set HF_TOKEN environment variable or pass --hf-token\n"
            "  3. Or use --input with a pre-downloaded local file"
        )
        return []

    documents = []
    for i, row in enumerate(ds):
        if i >= sample_size:
            break
        q = row.get("input") or row.get("question") or ""
        a = row.get("output") or row.get("answer") or ""
        if q and a:
            documents.append({
                "id": f"huatuo_{i}",
                "question": q.strip(),
                "answer": a.strip(),
                "text": f"问：{q.strip()}\n答：{a.strip()}",
            })
        if (i + 1) % 5000 == 0:
            logger.info(f"  loaded {i + 1} samples...")

    logger.info(f"Loaded {len(documents)} valid QA pairs from HuggingFace")
    return documents


def load_from_jsonl(file_path: str, sample_size: int) -> list[dict]:
    path = Path(file_path)
    if not path.exists():
        logger.error(f"File not found: {file_path}")
        sys.exit(1)

    documents = []
    if path.suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else [data]
        for i, row in enumerate(items):
            if sample_size and i >= sample_size:
                break
            q = row.get("input") or row.get("question") or row.get("q") or ""
            a = row.get("output") or row.get("answer") or row.get("a") or ""
            if q and a:
                documents.append({
                    "id": f"local_{i}",
                    "question": q.strip(),
                    "answer": a.strip(),
                    "text": f"问：{q.strip()}\n答：{a.strip()}",
                })
    else:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if sample_size and i >= sample_size:
                    break
                try:
                    row = json.loads(line.strip())
                    q = row.get("input") or row.get("question") or row.get("q") or ""
                    a = row.get("output") or row.get("answer") or row.get("a") or ""
                    if q and a:
                        documents.append({
                            "id": f"local_{i}",
                            "question": q.strip(),
                            "answer": a.strip(),
                            "text": f"问：{q.strip()}\n答：{a.strip()}",
                        })
                except json.JSONDecodeError:
                    continue

    logger.info(f"Loaded {len(documents)} QA pairs from {file_path}")
    return documents


def build_index(documents: list[dict], persist_dir: str):
    from rag.retriever import MedicalRAG

    logger.info(f"Building ChromaDB index at {persist_dir}...")
    rag = MedicalRAG(
        persist_dir=persist_dir,
        model_name="shibing624/text2vec-base-chinese",
    )

    batch_size = 1000
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        rag.add_documents(batch)
        logger.info(f"  indexed {min(i + batch_size, len(documents))}/{len(documents)}")

    logger.info(f"Index complete! Total documents: {rag.get_count()}")


def main():
    parser = argparse.ArgumentParser(description="Prepare Huatuo26M-Lite RAG index")
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES, help="Number of samples")
    parser.add_argument("--input", type=str, default=None, help="Local JSON/JSONL input file (optional)")
    parser.add_argument("--hf-token", type=str, default="", help="HuggingFace access token")
    parser.add_argument("--persist-dir", type=str, default=DEFAULT_PERSIST_DIR, help="ChromaDB persist directory")
    args = parser.parse_args()

    documents = []

    if args.input:
        documents = load_from_jsonl(args.input, args.samples)
    else:
        documents = load_from_huggingface(args.samples, args.hf_token)

    if not documents:
        logger.error("No documents loaded, aborting")
        logger.error(
            "Tips:\n"
            "  - Run: huggingface-cli login (get a token from https://huggingface.co/settings/tokens)\n"
            "  - Or download data manually and use: python -m rag.prepare_data --input your_data.jsonl\n"
            "  - Dataset: https://huggingface.co/datasets/FreedomIntelligence/Huatuo26M-Lite"
        )
        sys.exit(1)

    build_index(documents, args.persist_dir)


if __name__ == "__main__":
    main()
