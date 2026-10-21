"""CLI: run the full pipeline on one drawing without the human-verification step.

    python app.py sample_pdfs/7.pdf [--type foundation|column|slab|beam] [--no-llm-validator] [--json out.json]
"""
import argparse
import json
from dataclasses import asdict
from pathlib import Path

from src import config, pipeline, preprocess
from src.schemas import DrawingType


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path, help="PDF or image files of one drawing")
    ap.add_argument("--type", choices=[t.value for t in DrawingType if t != DrawingType.UNKNOWN],
                    help="skip auto classification")
    ap.add_argument("--no-llm-validator", action="store_true", help="rule-based validation only")
    ap.add_argument("--json", type=Path, help="also write structured results to this file")
    args = ap.parse_args()

    images = preprocess.load_inputs((f.name, f.read_bytes()) for f in args.files)
    out = pipeline.run_all(
        images,
        DrawingType(args.type) if args.type else None,
        use_llm_validator=not args.no_llm_validator,
        source_name=", ".join(f.name for f in args.files),
    )

    config.REPORTS_DIR.mkdir(exist_ok=True)
    report_path = config.REPORTS_DIR / f"{args.files[0].stem}_compliance.md"
    report_path.write_text(out["report_markdown"], encoding="utf-8")
    print(f"Classified as {out['classification'].drawing_type.value} ({out['classification'].confidence:.0%})")
    print(f"Report written to {report_path}")

    if args.json:
        args.json.write_text(json.dumps({
            "classification": {**asdict(out["classification"]), "drawing_type": out["classification"].drawing_type.value},
            "extraction": out["extraction"].model_dump(mode="json"),
            "validation": out["validation"].to_dict(),
            "results": [r.to_dict() for r in out["results"]],
        }, indent=2), encoding="utf-8")
        print(f"JSON written to {args.json}")


if __name__ == "__main__":
    main()
