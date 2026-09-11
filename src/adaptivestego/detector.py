"""A trained detector, for the embedding the hand-built statistics cannot see.

Chi-square, SPA, RS and WS all exploit the same structural flaw: LSB
replacement makes a pixel's value depend on the bit written into it, so the
pairs (2k, 2k+1) drift together. LSB matching has no such flaw - it adds
+/-1 - and every one of those detectors is blind to it by construction, which
is not a shortcoming to be tuned away but a property of the attack.

What works instead is a classifier over a feature set that models local pixel
dependencies, trained on covers and stegos from the same source. This module
is the smallest honest version of that: SPAM features and Fisher's linear
discriminant, the standard pre-neural baseline.

A model is only valid for the kind of image, the method and the payload it was
trained on. Every model file therefore carries that provenance with it, it is
reported alongside every score, and :meth:`Detector.describe` exists so that a
number from this module is never quoted without it.

    from adaptivestego import detector
    model = detector.load()               # the bundled model, if there is one
    print(model.describe())
    print(model.probability(image))

Train one with experiments/train_detector.py.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np

from .features import spam_features

__all__ = ["Detector", "load", "available_models", "MODEL_DIR",
           "train_fld", "roc_auc"]

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
DEFAULT_MODEL = "spam-fld.npz"


@dataclass
class Detector:
    """A linear classifier over SPAM features."""

    weights: np.ndarray
    bias: float
    mean: np.ndarray            # feature standardisation, from the training set
    scale: np.ndarray
    threshold: float            # score above this means "stego"
    platt: tuple[float, float]  # (a, b) mapping a score to a probability
    meta: dict

    # -- use ---------------------------------------------------------------
    def score(self, img: np.ndarray) -> float:
        """Signed distance from the decision boundary; positive means stego."""
        return self.score_features(spam_features(img))

    def score_features(self, features: np.ndarray) -> float:
        x = (np.asarray(features, dtype=np.float64) - self.mean) / self.scale
        return float(x @ self.weights + self.bias)

    def probability(self, img: np.ndarray) -> float:
        """Platt-calibrated probability that the image carries a payload."""
        return self.probability_of_score(self.score(img))

    def probability_of_score(self, score: float) -> float:
        a, b = self.platt
        return float(1.0 / (1.0 + np.exp(-(a * score + b))))

    def predict(self, img: np.ndarray) -> dict:
        """Score, probability and verdict, with the model's provenance."""
        score = self.score(img)
        probability = self.probability_of_score(score)
        return {
            "score": score,
            "probability": probability,
            "stego": bool(score > self.threshold),
            "model": self.describe(),
            "trained_on": self.meta.get("trained_on", "unknown"),
            "valid_for": self.meta.get("valid_for", "unknown"),
        }

    def describe(self) -> str:
        """One line saying what this model may legitimately be applied to."""
        meta = self.meta
        return (f"{meta.get('features', 'spam')}+{meta.get('classifier', 'fld')} "
                f"trained on {meta.get('trained_on', 'unknown')} against "
                f"{meta.get('method', '?')} at {meta.get('bpp', '?')} bpp, "
                f"test AUC {meta.get('test_auc', float('nan')):.3f}")

    # -- storage -----------------------------------------------------------
    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        np.savez_compressed(
            path, weights=self.weights, bias=np.float64(self.bias),
            mean=self.mean, scale=self.scale,
            threshold=np.float64(self.threshold),
            platt=np.asarray(self.platt, dtype=np.float64),
            meta=np.array(json.dumps(self.meta)))

    @classmethod
    def from_file(cls, path: str) -> Detector:
        with np.load(path, allow_pickle=False) as data:
            return cls(
                weights=data["weights"], bias=float(data["bias"]),
                mean=data["mean"], scale=data["scale"],
                threshold=float(data["threshold"]),
                platt=tuple(float(v) for v in data["platt"]),
                meta=json.loads(str(data["meta"])))


def available_models() -> list[str]:
    """Names of the model files that ship with (or were trained into) the package."""
    if not os.path.isdir(MODEL_DIR):
        return []
    return sorted(n for n in os.listdir(MODEL_DIR) if n.endswith(".npz"))


def load(name: str | None = None) -> Detector | None:
    """Load a trained detector, or return None when none is installed.

    Returning None rather than raising is deliberate: a trained detector is an
    optional extra that needs a dataset to produce, and every caller here has
    something useful to report without it.
    """
    if name is None:
        name = DEFAULT_MODEL
    path = name if os.path.isabs(name) else os.path.join(MODEL_DIR, name)
    if not os.path.isfile(path):
        return None
    return Detector.from_file(path)


# ---------------------------------------------------------------------------
# training
# ---------------------------------------------------------------------------
def roc_auc(negative: np.ndarray, positive: np.ndarray) -> float:
    """Area under the ROC curve, by rank."""
    negative, positive = np.asarray(negative), np.asarray(positive)
    if not negative.size or not positive.size:
        return float("nan")
    order = np.argsort(np.concatenate([negative, positive]), kind="mergesort")
    ranks = np.empty(order.size, dtype=np.float64)
    ranks[order] = np.arange(1, order.size + 1)
    # Average the ranks of ties so that a constant score gives 0.5.
    values = np.concatenate([negative, positive])
    _, inverse, counts = np.unique(values, return_inverse=True,
                                   return_counts=True)
    sums = np.bincount(inverse, weights=ranks)
    ranks = (sums / counts)[inverse]
    n_neg, n_pos = negative.size, positive.size
    rank_sum = ranks[n_neg:].sum()
    return float((rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_neg * n_pos))


def _fit_platt(scores: np.ndarray, labels: np.ndarray,
               iterations: int = 100) -> tuple[float, float]:
    """Fit a logistic map from score to probability by Newton's method."""
    a, b = 1.0, 0.0
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.float64)
    for _ in range(iterations):
        p = 1.0 / (1.0 + np.exp(-(a * scores + b)))
        residual = p - labels
        weight = np.clip(p * (1.0 - p), 1e-12, None)
        gradient = np.array([np.dot(residual, scores), residual.sum()])
        hessian = np.array([
            [np.dot(weight, scores * scores), np.dot(weight, scores)],
            [np.dot(weight, scores), weight.sum()],
        ]) + 1e-9 * np.eye(2)
        step = np.linalg.solve(hessian, gradient)
        a, b = a - step[0], b - step[1]
        if np.abs(step).max() < 1e-10:
            break
    return float(a), float(b)


def train_fld(cover_features: np.ndarray, stego_features: np.ndarray, *,
              ridge: float | None = None, meta: dict | None = None,
              validation: float = 0.25, seed: int = 20260912) -> Detector:
    """Fit Fisher's linear discriminant, calibrate it, and package the result.

    ``ridge`` regularises the pooled within-class scatter, which is singular
    for 686 features unless there are far more images than that. It is chosen
    on a validation split when not given.

    The caller is responsible for the split that matters - the images used for
    training must not be the images the model is later reported on - because
    this function cannot see where its inputs came from.
    """
    cover_features = np.asarray(cover_features, dtype=np.float64)
    stego_features = np.asarray(stego_features, dtype=np.float64)
    rng = np.random.default_rng(seed)

    n_cover, n_stego = len(cover_features), len(stego_features)
    cover_validation = rng.random(n_cover) < validation
    stego_validation = rng.random(n_stego) < validation

    cover_train = cover_features[~cover_validation]
    stego_train = stego_features[~stego_validation]

    both = np.concatenate([cover_train, stego_train])
    mean = both.mean(axis=0)
    scale = both.std(axis=0)
    scale[scale < 1e-12] = 1.0

    def standardise(x):
        return (x - mean) / scale

    c_train, s_train = standardise(cover_train), standardise(stego_train)
    c_validation = standardise(cover_features[cover_validation])
    s_validation = standardise(stego_features[stego_validation])

    difference = s_train.mean(axis=0) - c_train.mean(axis=0)
    scatter = (np.cov(c_train, rowvar=False) * (len(c_train) - 1)
               + np.cov(s_train, rowvar=False) * (len(s_train) - 1))
    scatter /= max(len(c_train) + len(s_train) - 2, 1)

    candidates = [ridge] if ridge is not None else [1e-4, 1e-3, 1e-2, 1e-1, 1.0]
    best = None
    identity = np.eye(scatter.shape[0])
    for value in candidates:
        weights = np.linalg.solve(scatter + value * identity, difference)
        if c_validation.size and s_validation.size:
            auc = roc_auc(c_validation @ weights, s_validation @ weights)
        else:                                    # no validation split to speak of
            auc = roc_auc(c_train @ weights, s_train @ weights)
        if best is None or auc > best[0]:
            best = (auc, value, weights)

    validation_auc, chosen_ridge, weights = best

    scores_c = (c_validation if c_validation.size else c_train) @ weights
    scores_s = (s_validation if s_validation.size else s_train) @ weights

    # Put the decision boundary where it minimises the average of the two
    # error rates on the validation split - the quantity steganalysis reports -
    # rather than midway between the class means, which is only the same thing
    # when the two score distributions are symmetric and they are not.
    cuts = np.unique(np.concatenate([scores_c, scores_s]))
    errors = [0.5 * (np.mean(scores_c > cut) + np.mean(scores_s <= cut))
              for cut in cuts]
    bias = -float(cuts[int(np.argmin(errors))])

    platt = _fit_platt(
        np.concatenate([scores_c, scores_s]) + bias,
        np.concatenate([np.zeros(scores_c.size), np.ones(scores_s.size)]))

    meta = dict(meta or {})
    meta.setdefault("features", "spam686")
    meta.setdefault("classifier", "fld")
    meta["ridge"] = chosen_ridge
    meta["validation_auc"] = float(validation_auc)
    meta["n_train"] = int(len(c_train) + len(s_train))

    return Detector(weights=weights, bias=bias, mean=mean, scale=scale,
                    threshold=0.0, platt=platt, meta=meta)
