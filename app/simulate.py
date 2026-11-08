import argparse

from .db import record_event, upsert_tag
from .activity import record_activity, record_playback
from .spotify_service import dispatch_tag_value, get_tag_type


def dispatch_simulated_value(uid: str, value: str) -> dict:
    tag_type = get_tag_type(value)
    if tag_type is None:
        raise ValueError(f"Unsupported simulated tag value: {value}")

    upsert_tag(uid=uid, value=value, tag_type=tag_type, label=f"simulated-{uid}")
    record_event(uid, tag_type, value, source="simulate")
    try:
        result = dispatch_tag_value(value)
    except Exception:
        record_activity(
            "playback", "ERROR", "simulate", "Tag dispatch failed; check the simulator output and try again.",
            uid=uid, value=value,
        )
        raise
    record_playback(uid, value, "simulate", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a tag scan for local testing")
    parser.add_argument("--uid", required=True)
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()

    result = dispatch_simulated_value(args.uid, args.payload)
    print({"uid": args.uid, "payload": args.payload, "result": result})


if __name__ == "__main__":
    main()
