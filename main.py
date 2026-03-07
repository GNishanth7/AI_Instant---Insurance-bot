from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "Run `uvicorn backend.server:app --host 0.0.0.0 --port 8000` for the API "
        "and `cd frontend && npm run dev` for the Next.js UI."
    )


if __name__ == "__main__":
    main()
