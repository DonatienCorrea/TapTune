import argparse
import time

from .nfc_reader import PN532Reader


def wait_for_card(reader, seconds: float = 30.0, clock=time.monotonic) -> str:
    deadline = clock() + seconds
    while clock() < deadline:
        event = reader.read_once()
        if event is not None:
            return event.uid
    raise TimeoutError(f"No NFC card detected within {seconds:g} seconds.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check the PN532 I2C connection and read one NFC card UID."
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=30.0,
        help="Maximum number of seconds to wait for a card (default: 30).",
    )
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be greater than zero")

    try:
        reader = PN532Reader()
    except Exception as error:
        raise SystemExit(
            "Could not initialize the PN532 over I2C. Check I2C is enabled, "
            f"the board is in I2C mode, and wiring/power are correct: {error}"
        ) from error

    print("PN532 initialized over I2C. Hold a card near the reader...")
    try:
        uid = wait_for_card(reader, args.seconds)
    except TimeoutError as error:
        raise SystemExit(str(error)) from error
    print(f"uid={uid}")


if __name__ == "__main__":
    main()
