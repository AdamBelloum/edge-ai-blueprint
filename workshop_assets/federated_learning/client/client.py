"""Flower Silo client for the federated-learning workflow demonstration.

This client intentionally does not read image files.  It uses the CSV image
identifier only as stable entropy to generate deterministic synthetic features
around class-specific centroids.  It demonstrates the federated workflow; it
is not a validated cassava disease classifier.
"""

from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
from typing import Any

import flwr as fl
import numpy as np


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value else default


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


def stable_seed(*parts: object) -> int:
    text = ":".join(str(part) for part in parts)
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def synthetic_features(
    sample_ids: list[str],
    labels: np.ndarray,
    *,
    num_classes: int,
    feature_dim: int,
    seed: int,
) -> np.ndarray:
    """Create deterministic synthetic features without reading image files."""
    centroids = np.empty((num_classes, feature_dim), dtype=np.float64)

    for label in range(num_classes):
        generator = np.random.default_rng(stable_seed(seed, "centroid", label))
        centroids[label] = generator.normal(loc=0.0, scale=1.0, size=feature_dim)

    features = np.empty((len(sample_ids), feature_dim), dtype=np.float64)
    for index, (sample_id, label) in enumerate(zip(sample_ids, labels, strict=True)):
        generator = np.random.default_rng(
            stable_seed(seed, "sample", int(label), sample_id)
        )
        noise = generator.normal(loc=0.0, scale=0.25, size=feature_dim)
        features[index] = centroids[int(label)] + noise

    return features.astype(np.float32)


def load_partition(
    path: Path,
    *,
    num_classes: int,
    feature_dim: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    if not path.is_file():
        raise FileNotFoundError(f"partition CSV not found: {path}")

    sample_ids: list[str] = []
    labels: list[int] = []

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "label" not in reader.fieldnames:
            raise ValueError(f"{path} must contain a 'label' column")

        for row_number, row in enumerate(reader, start=2):
            raw_label = (row.get("label") or "").strip()
            if not raw_label:
                raise ValueError(f"{path}:{row_number} has an empty label")

            try:
                label = int(raw_label)
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{row_number} has non-integer label {raw_label!r}"
                ) from exc

            if not 0 <= label < num_classes:
                raise ValueError(
                    f"{path}:{row_number} has label {label}; expected "
                    f"an integer in [0, {num_classes - 1}]"
                )

            # The identifier is never opened as a file. It only makes synthetic
            # feature generation deterministic per dataset row.
            sample_id = (row.get("image") or "").strip() or f"row-{row_number}"
            sample_ids.append(sample_id)
            labels.append(label)

    if len(labels) < 2:
        raise ValueError(f"{path} must contain at least two data rows")

    label_array = np.asarray(labels, dtype=np.int64)
    feature_array = synthetic_features(
        sample_ids,
        label_array,
        num_classes=num_classes,
        feature_dim=feature_dim,
        seed=seed,
    )
    return feature_array, label_array


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exponential = np.exp(shifted)
    return exponential / np.sum(exponential, axis=1, keepdims=True)


def loss_and_accuracy(
    features: np.ndarray,
    labels: np.ndarray,
    weights: np.ndarray,
    bias: np.ndarray,
) -> tuple[float, float]:
    probabilities = softmax(features @ weights + bias)
    row_indices = np.arange(len(labels))
    loss = -np.mean(np.log(np.clip(probabilities[row_indices, labels], 1e-12, 1.0)))
    accuracy = np.mean(np.argmax(probabilities, axis=1) == labels)
    return float(loss), float(accuracy)


class WorkflowDemoClient(fl.client.NumPyClient):
    def __init__(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        *,
        num_classes: int,
        learning_rate: float,
        local_epochs: int,
    ) -> None:
        self.features = features
        self.labels = labels
        self.learning_rate = learning_rate
        self.local_epochs = local_epochs
        self.weights = np.zeros((features.shape[1], num_classes), dtype=np.float32)
        self.bias = np.zeros(num_classes, dtype=np.float32)

    def get_parameters(self, config: dict[str, Any]) -> list[np.ndarray]:
        return [self.weights, self.bias]

    def set_parameters(self, parameters: list[np.ndarray]) -> None:
        if len(parameters) != 2:
            raise ValueError("expected exactly two model parameter arrays")

        weights, bias = parameters
        if weights.shape != self.weights.shape or bias.shape != self.bias.shape:
            raise ValueError(
                "server parameters do not match the workflow-demo model shape"
            )

        self.weights = weights.astype(np.float32, copy=True)
        self.bias = bias.astype(np.float32, copy=True)

    def fit(
        self,
        parameters: list[np.ndarray],
        config: dict[str, Any],
    ) -> tuple[list[np.ndarray], int, dict[str, float]]:
        self.set_parameters(parameters)

        weights = self.weights.astype(np.float64)
        bias = self.bias.astype(np.float64)
        sample_count = len(self.labels)

        for _ in range(self.local_epochs):
            probabilities = softmax(self.features @ weights + bias)
            gradients = probabilities
            gradients[np.arange(sample_count), self.labels] -= 1.0
            gradients /= sample_count

            weight_gradient = self.features.T @ gradients
            bias_gradient = np.sum(gradients, axis=0)

            weights -= self.learning_rate * weight_gradient
            bias -= self.learning_rate * bias_gradient

        self.weights = weights.astype(np.float32)
        self.bias = bias.astype(np.float32)
        loss, accuracy = loss_and_accuracy(
            self.features, self.labels, self.weights, self.bias
        )

        return (
            self.get_parameters({}),
            sample_count,
            {
                "workflow_demo_loss": loss,
                "workflow_demo_accuracy": accuracy,
            },
        )

    def evaluate(
        self,
        parameters: list[np.ndarray],
        config: dict[str, Any],
    ) -> tuple[float, int, dict[str, float]]:
        self.set_parameters(parameters)
        loss, accuracy = loss_and_accuracy(
            self.features, self.labels, self.weights, self.bias
        )
        return (
            loss,
            len(self.labels),
            {"workflow_demo_accuracy": accuracy},
        )


def main() -> None:
    server_address = required_env("FLOWER_SERVER_ADDRESS")
    data_path = Path(required_env("CLIENT_DATA_PATH"))
    group_id = os.environ.get("GROUP_ID", "unspecified-group")
    num_classes = env_int("NUM_CLASSES", 5)
    feature_dim = env_int("SYNTHETIC_FEATURE_DIM", 16)
    seed = env_int("SYNTHETIC_SEED", 42)
    learning_rate = env_float("LEARNING_RATE", 0.1)
    local_epochs = env_int("LOCAL_EPOCHS", 1)

    if num_classes < 2:
        raise ValueError("NUM_CLASSES must be at least 2")
    if feature_dim < 1:
        raise ValueError("SYNTHETIC_FEATURE_DIM must be at least 1")
    if local_epochs < 1:
        raise ValueError("LOCAL_EPOCHS must be at least 1")

    features, labels = load_partition(
        data_path,
        num_classes=num_classes,
        feature_dim=feature_dim,
        seed=seed,
    )

    print(
        "Starting workflow-demo client:",
        {
            "group_id": group_id,
            "server_address": server_address,
            "data_path": str(data_path),
            "samples": len(labels),
            "num_classes": num_classes,
            "feature_dim": feature_dim,
            "local_epochs": local_epochs,
        },
        flush=True,
    )

    client = WorkflowDemoClient(
        features,
        labels,
        num_classes=num_classes,
        learning_rate=learning_rate,
        local_epochs=local_epochs,
    )
    fl.client.start_numpy_client(server_address=server_address, client=client)


if __name__ == "__main__":
    main()
