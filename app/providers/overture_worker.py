"""Run remote acquisition in a subprocess with a bounded lifetime."""

import json
import sys
from time import perf_counter


def download(request: dict):
    import pyarrow.parquet as pq

    start = perf_counter()
    if request["backend"] == "overturemaps":
        from overturemaps.core import record_batch_reader

        reader = record_batch_reader(
            request["kind"],
            bbox=request["bbox"],
            release=request["release"],
            stac=True,
            connect_timeout=15,
            request_timeout=60,
        )
        if reader is None:
            raise RuntimeError(
                "Official client returned no reader despite spatial assets"
            )
        table = reader.read_all()
    else:
        import duckdb

        w, s, e, n = request["bbox"]
        with duckdb.connect() as connection:
            connection.execute("SET threads=2")
            connection.execute("SET memory_limit='512MB'")
            connection.execute("SET http_timeout=45")
            table = connection.execute(
                "SELECT * FROM read_parquet(?) WHERE bbox.xmin <= ? "
                "AND bbox.xmax >= ? AND bbox.ymin <= ? AND bbox.ymax >= ?",
                [request["paths"], e, w, n, s],
            ).to_arrow_table()
    pq.write_table(table, request["output"])
    return {"query_seconds": perf_counter() - start, "rows_bbox": table.num_rows}


if __name__ == "__main__":
    try:
        print(json.dumps(download(json.load(sys.stdin))))
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        raise SystemExit(1) from exc
