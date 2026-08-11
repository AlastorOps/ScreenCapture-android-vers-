import sys

from androidlink.app.lifecycle import startup


def run() -> int:
    app, _window = startup()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
