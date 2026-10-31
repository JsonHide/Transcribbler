"""Transcribbler master entrypoint. Launches GUI by default or CLI with --cli."""
import sys

if __name__ == "__main__":
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from transcribbler.cli import run_cli
        run_cli()
    else:
        from transcribbler.ui.app import TranscribblerApp
        app = TranscribblerApp()
        app.mainloop()
