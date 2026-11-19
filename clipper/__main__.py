"""python -m clipper <command>

  live [channel ...]                 clip Twitch streams live (channels default to config.toml)
  vod <url-or-file> [--channel X] [--section 1:00:00-1:30:00]
  queue                              list clips waiting for review
  approve <id> [--variant 1-3] [--platforms youtube,tiktok,instagram]
  reject <id>
  auth youtube|tiktok                one-time login for uploads
"""
from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("faster_whisper", "httpx", "googleapiclient"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = load_config()
    ap = argparse.ArgumentParser(prog="clipper", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("live")
    p.add_argument("channels", nargs="*")
    p = sub.add_parser("vod")
    p.add_argument("input")
    p.add_argument("--channel")
    p.add_argument("--section", help="only this part of a long VOD, e.g. 1:00:00-1:30:00")
    sub.add_parser("queue")
    p = sub.add_parser("approve")
    p.add_argument("id")
    p.add_argument("--variant", type=int, default=1, choices=[1, 2, 3])
    p.add_argument("--platforms")
    sub.add_parser("post")
    sub.add_parser("batch", help="one scheduled run: clip recent broadcasts, post the best")
    sub.add_parser("status")
    p = sub.add_parser("reject")
    p.add_argument("id")
    p = sub.add_parser("auth")
    p.add_argument("platform", choices=["youtube", "tiktok"])
    p.add_argument("--remote", action="store_true",
                   help="print a link for the channel owner to approve on their own device")
    p.add_argument("--finish", metavar="URL", help="the 'can't be reached' address they send back")
    a = ap.parse_args()

    if a.cmd == "live":
        from . import live
        chans = a.channels or cfg["stream"]["channels"]
        if not chans or "CHANGE_ME" in chans:
            sys.exit("Set [stream] channels in config.toml or pass a channel name.")
        live.run(cfg, chans)
    elif a.cmd == "vod":
        from . import pipeline
        metas = pipeline.process_vod(a.input, cfg, a.channel, a.section)
        print(f"\n{len(metas)} clips queued. Review with: python -m clipper queue")
    elif a.cmd == "queue":
        from . import review
        pending = review.items("pending")
        if not pending:
            print("Queue is empty.")
        for m in pending:
            print(f"\n{m['id']}  score {m['score']}  {m['channel']}  {m['end'] - m['start']:.0f}s")
            print(f"  title: {m['title']}")
            for i, h in enumerate(m["hooks"], 1):
                print(f"  v{i}: [{h['structure']}] {h['text']}")
            print(f"  files: output/queue/{m['id']}/v1.mp4 .. v{len(m['hooks'])}.mp4")
    elif a.cmd == "approve":
        from . import review
        plats = a.platforms.split(",") if a.platforms else cfg["upload"]["platforms"]
        print(f"Posting {a.id} v{a.variant} to {', '.join(plats)}")
        review.post_now(a.id, a.variant, plats, cfg)
    elif a.cmd == "batch":
        from . import batch
        batch.run(cfg)
    elif a.cmd == "post":
        from . import review
        review.post_due(cfg)
    elif a.cmd == "status":
        from . import review
        for s in ("pending", "approved", "posted", "rejected"):
            ms = review.items(s)
            print(f"{s:9} {len(ms)}")
            for m in ms[-5:]:
                r = m.get("ai_review") or {}
                print(f"   {m['id']} {m['channel']:15} ai {r.get('score', '-')}  {m['title'][:50]}  {r.get('reason', '')[:60]}")
    elif a.cmd == "reject":
        from . import review
        m = review.load(a.id)
        m["status"] = "rejected"
        review.save(m)
        print("rejected")
    elif a.cmd == "auth":
        from .uploaders import tiktok, youtube
        if a.platform == "youtube":
            youtube.authorize(remote=a.remote, finish=a.finish)
        else:
            tiktok.authorize()


if __name__ == "__main__":
    main()
