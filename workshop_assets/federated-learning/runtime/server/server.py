import os

import flwr as fl


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def main() -> None:
    host = os.environ.get("FLOWER_SERVER_HOST", "0.0.0.0")
    port = _env_int("FLOWER_SERVER_PORT", 8080)
    min_fit_clients = _env_int("MIN_FIT_CLIENTS", 2)
    min_available_clients = _env_int("MIN_AVAILABLE_CLIENTS", 2)
    min_evaluate_clients = _env_int("MIN_EVALUATE_CLIENTS", 2)
    num_rounds = _env_int("NUM_ROUNDS", 5)

    strategy = fl.server.strategy.FedAvg(
        min_fit_clients=min_fit_clients,
        min_available_clients=min_available_clients,
        min_evaluate_clients=min_evaluate_clients,
    )

    server_address = f"{host}:{port}"
    print("Federated Server Starting...")
    print(
        "Config:",
        {
            "server_address": server_address,
            "num_rounds": num_rounds,
            "min_fit_clients": min_fit_clients,
            "min_available_clients": min_available_clients,
            "min_evaluate_clients": min_evaluate_clients,
        },
    )

    fl.server.start_server(
        server_address=server_address,
        config=fl.server.ServerConfig(num_rounds=num_rounds),
        strategy=strategy,
    )


if __name__ == "__main__":
    main()
