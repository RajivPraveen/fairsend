"""Command-line entry point.

    fairsend update                           download a new World Bank quarter if there is one, then rebuild
    fairsend pipeline [--force] [--offline]   load / refresh World Bank prices and FX rates
    fairsend fx                               refresh today's mid-market rates only
    fairsend alerts                           run the daily alert check
    fairsend compare USA IND 500              print a provider comparison
    fairsend report                           write the global cost report to reports/
    fairsend index                            (re)build the explainer's search index
    fairsend export-demo [--out PATH]         write the compact demo database (.db.gz)
    fairsend app                              start the web app
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fairsend")
    sub = parser.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("update", help="download a new World Bank quarter if available, then rebuild")
    u.add_argument("--force", action="store_true", help="rebuild even if the file is unchanged")
    e = sub.add_parser("export-demo", help="write the compact demo database")
    e.add_argument("--out", type=Path, default=Path("dist/fairsend_demo.db.gz"))
    p = sub.add_parser("pipeline", help="ingest World Bank prices and refresh FX rates")
    p.add_argument("--source", type=Path)
    p.add_argument("--force", action="store_true")
    p.add_argument("--offline", action="store_true")
    sub.add_parser("fx", help="refresh today's mid-market rates")
    sub.add_parser("alerts", help="run the daily alert check")
    c = sub.add_parser("compare", help="compare providers on a route")
    c.add_argument("source_code")
    c.add_argument("dest_code")
    c.add_argument("amount", type=float)
    c.add_argument("--top", type=int, default=10)
    sub.add_parser("report", help="write the global remittance cost report")
    sub.add_parser("index", help="rebuild the explainer index")
    a = sub.add_parser("app", help="start the Streamlit app")
    a.add_argument("--port", type=int, default=8501)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "update":
        from fairsend.pipeline import fetch, run
        release = fetch.latest_release()
        print(f"Latest World Bank release: {release.file_name} ({release.version or 'version n/a'}, "
              f"updated {release.last_updated})")
        path, downloaded = fetch.download(release)
        print("Downloaded a new file." if downloaded else "No new file; already up to date.")
        summary = run.run(path, force=args.force)
        print(f"Pipeline {summary['status']}: {summary.get('notes', '')}")
    elif args.cmd == "export-demo":
        from fairsend import demo
        out = demo.export(args.out)
        print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    elif args.cmd == "pipeline":
        from fairsend.pipeline import run
        run.main([*(["--source", str(args.source)] if args.source else []), *(["--force"] if args.force else []),
                  *(["--offline"] if args.offline else [])])
    elif args.cmd == "fx":
        from fairsend import db
        from fairsend.pipeline.run import refresh_fx
        with db.session() as conn:
            print(refresh_fx(conn))
    elif args.cmd == "alerts":
        from fairsend.alerts import job
        print(job.run())
    elif args.cmd == "compare":
        from fairsend import compare
        comp = compare.compare(args.source_code.upper(), args.dest_code.upper(), args.amount)
        print(f"Mid-market: 1 {comp.send_currency} = {comp.mid_rate.rate:,.4f} {comp.country_currency} "
              f"({comp.mid_rate.source}, {comp.mid_rate.rate_date}); prices from survey {comp.period}")
        cols = ["rank", "provider", "payout_method", "speed_label", "fee", "markup_pct", "total_cost", "amount_received"]
        print(comp.table[cols].head(args.top).round(2).to_string(index=False))
    elif args.cmd == "report":
        from fairsend.analysis import report
        print(f"Wrote {report.write()}")
    elif args.cmd == "index":
        from fairsend.explainer import index
        ix = index.build(force=True)
        print(f"Indexed {len(ix.chunks)} passages")
    elif args.cmd == "app":
        app = Path(__file__).resolve().parent.parent / "app" / "FairSend.py"
        sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(args.port)]))


if __name__ == "__main__":
    main()
