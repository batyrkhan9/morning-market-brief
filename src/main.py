"""Entry point. Supports --dry-run and --date YYYY-MM-DD."""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Build and send the morning market brief.")
    parser.add_argument("--dry-run", action="store_true", help="build locally, send nothing")
    parser.add_argument("--date", help="rebuild a past day from saved JSON (YYYY-MM-DD)")
    args = parser.parse_args()
    raise SystemExit("Not implemented yet. See CLAUDE.md milestones.")


if __name__ == "__main__":
    main()
