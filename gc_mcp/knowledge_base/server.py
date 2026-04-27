from .tools import persist_validated_knowledge


def run_server() -> dict:
    return persist_validated_knowledge({})


if __name__ == "__main__":
    print(run_server())
