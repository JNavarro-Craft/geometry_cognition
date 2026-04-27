from .tools import analyze_metadata_signals


def run_server() -> dict:
    return analyze_metadata_signals({})


if __name__ == "__main__":
    print(run_server())
