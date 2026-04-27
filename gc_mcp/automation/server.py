from .tools import run_automation


def run_server() -> dict:
    return run_automation({})


if __name__ == "__main__":
    print(run_server())
