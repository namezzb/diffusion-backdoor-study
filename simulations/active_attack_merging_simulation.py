"""
Active Backdoor Attack Strategies Optimized for Merge Persistence
=================================================================

This simulation implements and evaluates four adversarial strategies designed
to make backdoors survive model merging:

1. Magnitude Amplification: Scale backdoor params by factor k before sharing
2. Distributed Encoding: Spread backdoor across many parameters (high redundancy)
3. Sign Alignment: Align backdoor with majority sign direction for TIES survival
4. Spectral Hiding: Encode backdoor along principal components of clean models

Each strategy is tested against 5 merging algorithms:
- Simple Average
- Weighted Average
- TIES (Trim, Elect Sign, Scale)
- DARE (Drop And REscale)
- SLERP (Spherical Linear Interpolation)

Metrics:
- BSR Retention: How much backdoor signal survives merging
- Detectability: L2 norm deviation and spectral anomaly score
"""

import numpy as np
from typing import Tuple, Dict, List, NamedTuple
from dataclasses import dataclass
import warnings

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)


# =============================================================================
# SECTION 1: Core Data Structures
# =============================================================================

@dataclass(frozen=True)
class SimConfig:
    """Global simulation parameters."""
    param_dim: int = 2000          # Dimensionality of parameter vectors
    n_clean_models: int = 4        # Number of clean models in the merge pool
    n_trials: int = 20             # Number of random trials for statistics
    clean_noise_scale: float = 0.01  # Scale of clean fine-tuning noise
    pretrained_scale: float = 0.02   # Scale of pretrained weights
    backdoor_strength: float = 0.05  # Base backdoor perturbation strength
    bsr_threshold: float = 0.3       # Cosine similarity threshold for BSR=1


class MergeResult(NamedTuple):
    """Result of a single merge operation."""
    merged_params: np.ndarray
    bsr: float
    cosine_sim: float


class AttackResult(NamedTuple):
    """Result of an attack strategy evaluation."""
    strategy_name: str
    merge_algorithm: str
    bsr_retention: float       # BSR_after / BSR_before
    cosine_retention: float    # cosine_sim of merged vs backdoor direction
    l2_detectability: float    # L2 norm ratio vs clean models
    spectral_anomaly: float    # Residual energy outside top-k PCs


# =============================================================================
# SECTION 2: Model Generation
# =============================================================================

def generate_pretrained(cfg: SimConfig) -> np.ndarray:
    """Generate pretrained model parameters."""
    return np.random.randn(cfg.param_dim) * cfg.pretrained_scale


def generate_clean_finetuned(
    pretrained: np.ndarray,
    cfg: SimConfig,
    n_models: int
) -> np.ndarray:
    """Generate clean fine-tuned models as perturbations of pretrained."""
    noise = np.random.randn(n_models, cfg.param_dim) * cfg.clean_noise_scale
    return pretrained[np.newaxis, :] + noise


def generate_naive_backdoor(
    pretrained: np.ndarray,
    cfg: SimConfig
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate a naive backdoor model with a concentrated perturbation.

    Returns:
        backdoor_model: The adversarial model parameters
        backdoor_direction: The unit vector defining the backdoor trigger
    """
    # Backdoor direction: random unit vector
    direction = np.random.randn(cfg.param_dim)
    direction = direction / np.linalg.norm(direction)

    # Add clean fine-tuning noise + concentrated backdoor
    clean_noise = np.random.randn(cfg.param_dim) * cfg.clean_noise_scale
    backdoor_delta = direction * cfg.backdoor_strength * np.sqrt(cfg.param_dim)

    backdoor_model = pretrained + clean_noise + backdoor_delta
    return backdoor_model, direction


# =============================================================================
# SECTION 3: Merging Algorithms
# =============================================================================

def merge_simple_average(
    models: np.ndarray,
    pretrained: np.ndarray
) -> np.ndarray:
    """Simple arithmetic mean of all models."""
    return np.mean(models, axis=0)


def merge_weighted_average(
    models: np.ndarray,
    pretrained: np.ndarray,
    adversary_weight: float = 0.3
) -> np.ndarray:
    """
    Weighted average where adversary model (last) gets lower weight.
    Simulates a scenario where the adversary has less influence.
    """
    n = models.shape[0]
    weights = np.ones(n)
    # Adversary is the last model; give it reduced weight
    clean_weight = (1.0 - adversary_weight) / (n - 1)
    weights[:-1] = clean_weight
    weights[-1] = adversary_weight
    weights = weights / weights.sum()
    return np.average(models, axis=0, weights=weights)


def merge_ties(
    models: np.ndarray,
    pretrained: np.ndarray,
    trim_fraction: float = 0.2,
    merge_weight: float = 0.5
) -> np.ndarray:
    """
    TIES merging: Trim, Elect Sign, Scale.

    1. Compute task vectors (deltas from pretrained)
    2. Trim smallest magnitude parameters (set to 0)
    3. Resolve sign conflicts by majority vote
    4. Average only the parameters that agree on sign
    5. Scale and add back to pretrained
    """
    n_models = models.shape[0]
    # Task vectors
    deltas = models - pretrained[np.newaxis, :]

    # Step 1: Trim - zero out smallest fraction of each delta
    trimmed = np.copy(deltas)
    for i in range(n_models):
        magnitudes = np.abs(trimmed[i])
        threshold = np.quantile(magnitudes, trim_fraction)
        trimmed[i][magnitudes <= threshold] = 0.0

    # Step 2: Elect sign by majority vote
    signs = np.sign(trimmed)
    # Sum of signs across models; positive sum -> positive majority
    sign_votes = np.sum(signs, axis=0)
    elected_sign = np.sign(sign_votes)
    # Where vote is 0, default to positive
    elected_sign[elected_sign == 0] = 1.0

    # Step 3: Keep only values aligned with elected sign, zero others
    aligned = np.copy(trimmed)
    for i in range(n_models):
        misaligned = np.sign(aligned[i]) != elected_sign
        # Also zero where the value is already zero
        misaligned = misaligned & (aligned[i] != 0)
        aligned[i][misaligned] = 0.0

    # Step 4: Average non-zero aligned values
    nonzero_count = np.sum(aligned != 0, axis=0).astype(float)
    nonzero_count[nonzero_count == 0] = 1.0  # avoid division by zero
    merged_delta = np.sum(aligned, axis=0) / nonzero_count

    # Step 5: Scale and combine with pretrained
    return pretrained + merge_weight * merged_delta


def merge_dare(
    models: np.ndarray,
    pretrained: np.ndarray,
    drop_rate: float = 0.5,
    rng: np.random.RandomState = None
) -> np.ndarray:
    """
    DARE merging: Drop And REscale.

    1. Compute task vectors
    2. Randomly drop parameters with probability p
    3. Rescale remaining by 1/(1-p)
    4. Average and add to pretrained
    """
    if rng is None:
        rng = np.random.RandomState(SEED)

    n_models = models.shape[0]
    deltas = models - pretrained[np.newaxis, :]

    # Drop and rescale each delta independently
    rescaled = np.zeros_like(deltas)
    for i in range(n_models):
        mask = rng.random(deltas.shape[1]) > drop_rate
        rescaled[i] = deltas[i] * mask / (1.0 - drop_rate)

    # Average rescaled deltas
    merged_delta = np.mean(rescaled, axis=0)
    return pretrained + merged_delta


def merge_slerp(
    models: np.ndarray,
    pretrained: np.ndarray,
    t: float = 0.5
) -> np.ndarray:
    """
    SLERP merging (pairwise, then averaged).

    For >2 models, we iteratively SLERP pairs.
    Uses task vectors for interpolation.
    """
    deltas = models - pretrained[np.newaxis, :]

    def slerp_pair(v1: np.ndarray, v2: np.ndarray, t: float) -> np.ndarray:
        """Spherical linear interpolation between two vectors."""
        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 < 1e-10 or n2 < 1e-10:
            return (1 - t) * v1 + t * v2

        v1_unit = v1 / n1
        v2_unit = v2 / n2

        dot = np.clip(np.dot(v1_unit, v2_unit), -1.0, 1.0)
        omega = np.arccos(dot)

        if np.abs(omega) < 1e-10:
            return (1 - t) * v1 + t * v2

        # Interpolate direction via SLERP
        interp_dir = (np.sin((1 - t) * omega) * v1_unit +
                      np.sin(t * omega) * v2_unit) / np.sin(omega)
        # Interpolate magnitude linearly
        interp_mag = (1 - t) * n1 + t * n2

        return interp_dir * interp_mag

    # Iterative pairwise SLERP
    current = deltas[0]
    for i in range(1, len(deltas)):
        # Equal interpolation weight for each new model
        weight = 1.0 / (i + 1)
        current = slerp_pair(current, deltas[i], weight)

    return pretrained + current


# =============================================================================
# SECTION 4: BSR Measurement
# =============================================================================

def compute_bsr(
    merged_model: np.ndarray,
    pretrained: np.ndarray,
    backdoor_direction: np.ndarray,
    threshold: float = 0.3
) -> Tuple[float, float]:
    """
    Compute Backdoor Success Rate proxy.

    Measures how much of the backdoor direction is preserved in the merged
    model's deviation from pretrained.

    Returns:
        bsr: Binary success (1 if cosine_sim > threshold)
        cosine_sim: Raw cosine similarity with backdoor direction
    """
    delta = merged_model - pretrained
    delta_norm = np.linalg.norm(delta)

    if delta_norm < 1e-10:
        return 0.0, 0.0

    cosine_sim = np.dot(delta, backdoor_direction) / delta_norm
    bsr = 1.0 if cosine_sim > threshold else cosine_sim / threshold
    return bsr, cosine_sim


# =============================================================================
# SECTION 5: Detectability Metrics
# =============================================================================

def compute_l2_detectability(
    adversarial_model: np.ndarray,
    clean_models: np.ndarray,
    pretrained: np.ndarray
) -> float:
    """
    L2 norm ratio: how much larger is the adversary's deviation from
    pretrained compared to clean models.

    Ratio > 1 means adversary is more detectable.
    """
    adv_delta = np.linalg.norm(adversarial_model - pretrained)
    clean_deltas = np.array([
        np.linalg.norm(m - pretrained) for m in clean_models
    ])
    mean_clean_delta = np.mean(clean_deltas)

    if mean_clean_delta < 1e-10:
        return float('inf')

    return adv_delta / mean_clean_delta


def compute_spectral_anomaly(
    adversarial_model: np.ndarray,
    clean_models: np.ndarray,
    pretrained: np.ndarray,
    top_k: int = 5
) -> float:
    """
    Spectral anomaly: fraction of adversary's deviation energy that lies
    OUTSIDE the top-k principal components of clean model deviations.

    High value = detectable (adversary modifies unusual directions).
    Low value = hidden (adversary stays within normal variation).
    """
    clean_deltas = clean_models - pretrained[np.newaxis, :]
    adv_delta = adversarial_model - pretrained

    # PCA on clean deltas
    if clean_deltas.shape[0] < 2:
        return 0.5  # Cannot compute meaningful PCA

    # Center
    mean_delta = np.mean(clean_deltas, axis=0)
    centered = clean_deltas - mean_delta[np.newaxis, :]

    # SVD to get principal components
    U, S, Vt = np.linalg.svd(centered, full_matrices=False)
    # Top-k components
    k = min(top_k, Vt.shape[0])
    top_components = Vt[:k, :]  # shape (k, param_dim)

    # Project adversary delta onto top-k subspace
    adv_delta_norm = np.linalg.norm(adv_delta)
    if adv_delta_norm < 1e-10:
        return 0.0

    projections = top_components @ adv_delta  # shape (k,)
    projected_energy = np.sum(projections**2)
    total_energy = adv_delta_norm**2

    # Anomaly = fraction of energy outside top-k subspace
    anomaly = 1.0 - (projected_energy / total_energy)
    return max(0.0, anomaly)


# =============================================================================
# SECTION 6: Attack Strategies
# =============================================================================

def strategy_naive(
    pretrained: np.ndarray,
    backdoor_direction: np.ndarray,
    clean_models: np.ndarray,
    cfg: SimConfig
) -> np.ndarray:
    """
    Naive backdoor: simple additive perturbation along backdoor direction.
    This is the baseline that other strategies improve upon.
    """
    clean_noise = np.random.randn(cfg.param_dim) * cfg.clean_noise_scale
    backdoor_delta = backdoor_direction * cfg.backdoor_strength * np.sqrt(cfg.param_dim)
    return pretrained + clean_noise + backdoor_delta


def strategy_magnitude_amplification(
    pretrained: np.ndarray,
    backdoor_direction: np.ndarray,
    clean_models: np.ndarray,
    cfg: SimConfig,
    amplification_factor: float = 5.0
) -> np.ndarray:
    """
    Strategy 1: Magnitude Amplification.

    The attacker knows their model will be diluted by N clean models during
    merging. They pre-amplify the backdoor by factor k so that after averaging
    with N models, the effective signal is still above threshold.

    If merged with N clean models via simple average, the backdoor signal
    becomes (1/(N+1)) * k * original_strength. Setting k = N+1 recovers
    the original strength post-merge.
    """
    clean_noise = np.random.randn(cfg.param_dim) * cfg.clean_noise_scale
    # Amplify backdoor magnitude
    amplified_delta = (backdoor_direction * cfg.backdoor_strength *
                       np.sqrt(cfg.param_dim) * amplification_factor)
    return pretrained + clean_noise + amplified_delta


def strategy_distributed_encoding(
    pretrained: np.ndarray,
    backdoor_direction: np.ndarray,
    clean_models: np.ndarray,
    cfg: SimConfig,
    n_copies: int = 10
) -> np.ndarray:
    """
    Strategy 2: Distributed Encoding.

    Instead of concentrating the backdoor in one direction, distribute it
    across many redundant encoded copies. Each copy is a rotated version
    of the backdoor direction, and the backdoor is activated by the sum
    of all copies.

    This makes DARE less effective because dropping any subset of parameters
    only removes a fraction of the redundant signal.
    """
    clean_noise = np.random.randn(cfg.param_dim) * cfg.clean_noise_scale

    # Create n_copies rotated versions of the backdoor direction
    # Each rotation is small, so all copies contribute to the same direction
    total_delta = np.zeros(cfg.param_dim)
    strength_per_copy = cfg.backdoor_strength * np.sqrt(cfg.param_dim) / np.sqrt(n_copies)

    for _ in range(n_copies):
        # Small random rotation of the backdoor direction
        noise = np.random.randn(cfg.param_dim) * 0.1
        rotated = backdoor_direction + noise
        rotated = rotated / np.linalg.norm(rotated)
        total_delta += rotated * strength_per_copy

    return pretrained + clean_noise + total_delta


def strategy_sign_alignment(
    pretrained: np.ndarray,
    backdoor_direction: np.ndarray,
    clean_models: np.ndarray,
    cfg: SimConfig
) -> np.ndarray:
    """
    Strategy 3: Sign Alignment.

    The attacker observes (or estimates) the majority sign pattern of clean
    model task vectors. They then encode the backdoor such that its sign
    pattern aligns with the clean majority, ensuring TIES does not prune it.

    For each parameter dimension:
    - If the clean majority sign matches the backdoor direction sign, keep it
    - If not, flip the backdoor contribution to align, encoding the
      backdoor in magnitude modulation instead of sign
    """
    clean_noise = np.random.randn(cfg.param_dim) * cfg.clean_noise_scale

    # Compute majority sign from clean models' task vectors
    clean_deltas = clean_models - pretrained[np.newaxis, :]
    sign_votes = np.sign(np.sum(np.sign(clean_deltas), axis=0))
    sign_votes[sign_votes == 0] = 1.0

    # Encode backdoor aligned with majority sign
    backdoor_base = backdoor_direction * cfg.backdoor_strength * np.sqrt(cfg.param_dim)

    # Align: where backdoor sign disagrees with majority, flip it
    # but encode the information in magnitude variation
    aligned_delta = np.abs(backdoor_base) * sign_votes

    # Add a secondary encoding: the original sign information is encoded
    # in magnitude modulation (slightly larger where originally positive)
    magnitude_encoding = np.where(
        np.sign(backdoor_base) == sign_votes,
        1.2,   # boost where naturally aligned
        0.8    # reduce where forced to flip
    )
    aligned_delta = aligned_delta * magnitude_encoding

    return pretrained + clean_noise + aligned_delta


def strategy_spectral_hiding(
    pretrained: np.ndarray,
    backdoor_direction: np.ndarray,
    clean_models: np.ndarray,
    cfg: SimConfig,
    top_k: int = 5,
    amplification: float = 3.0
) -> np.ndarray:
    """
    Strategy 4: Spectral Hiding.

    The attacker projects the backdoor direction onto the principal component
    subspace of clean model variations. This makes the backdoor look like
    normal fine-tuning variation, reducing spectral detectability.

    The backdoor is encoded as a specific linear combination of the top-k
    PCs, amplified to maintain signal strength despite being constrained
    to a lower-dimensional subspace.
    """
    clean_noise = np.random.randn(cfg.param_dim) * cfg.clean_noise_scale

    # Compute PCA of clean model deviations
    clean_deltas = clean_models - pretrained[np.newaxis, :]
    centered = clean_deltas - np.mean(clean_deltas, axis=0)[np.newaxis, :]

    U, S, Vt = np.linalg.svd(centered, full_matrices=False)
    k = min(top_k, Vt.shape[0])
    top_components = Vt[:k, :]  # (k, param_dim)

    # Project backdoor direction onto top-k subspace
    projections = top_components @ backdoor_direction  # (k,)
    projected_backdoor = top_components.T @ projections  # (param_dim,)

    # Normalize and amplify
    proj_norm = np.linalg.norm(projected_backdoor)
    if proj_norm < 1e-10:
        # Backdoor is orthogonal to clean subspace; fall back to naive
        return strategy_naive(pretrained, backdoor_direction, clean_models, cfg)

    projected_backdoor = projected_backdoor / proj_norm
    spectral_delta = (projected_backdoor * cfg.backdoor_strength *
                      np.sqrt(cfg.param_dim) * amplification)

    return pretrained + clean_noise + spectral_delta


# =============================================================================
# SECTION 7: Experiment Runner
# =============================================================================

MERGE_ALGORITHMS = {
    "Simple Average": merge_simple_average,
    "Weighted Average": merge_weighted_average,
    "TIES": merge_ties,
    "DARE": merge_dare,
    "SLERP": merge_slerp,
}

ATTACK_STRATEGIES = {
    "Naive (Baseline)": strategy_naive,
    "Magnitude Amplification (k=5)": lambda p, bd, cm, cfg: (
        strategy_magnitude_amplification(p, bd, cm, cfg, amplification_factor=5.0)
    ),
    "Distributed Encoding (n=10)": lambda p, bd, cm, cfg: (
        strategy_distributed_encoding(p, bd, cm, cfg, n_copies=10)
    ),
    "Sign Alignment": strategy_sign_alignment,
    "Spectral Hiding (k=5, amp=3)": lambda p, bd, cm, cfg: (
        strategy_spectral_hiding(p, bd, cm, cfg, top_k=5, amplification=3.0)
    ),
}


def run_single_trial(
    cfg: SimConfig,
    rng_seed: int
) -> List[AttackResult]:
    """Run one trial of all strategies against all merge algorithms."""
    rng = np.random.RandomState(rng_seed)
    np.random.seed(rng_seed)

    results = []

    # Generate pretrained model
    pretrained = rng.randn(cfg.param_dim) * cfg.pretrained_scale

    # Generate clean fine-tuned models
    clean_models = pretrained[np.newaxis, :] + (
        rng.randn(cfg.n_clean_models, cfg.param_dim) * cfg.clean_noise_scale
    )

    # Generate backdoor direction (consistent across strategies for fair comparison)
    backdoor_direction = rng.randn(cfg.param_dim)
    backdoor_direction = backdoor_direction / np.linalg.norm(backdoor_direction)

    for strategy_name, strategy_fn in ATTACK_STRATEGIES.items():
        # Reset seed for reproducible strategy generation
        np.random.seed(rng_seed + hash(strategy_name) % 10000)

        # Generate adversarial model using this strategy
        adv_model = strategy_fn(pretrained, backdoor_direction, clean_models, cfg)

        # Compute detectability of the adversarial model before merging
        l2_detect = compute_l2_detectability(adv_model, clean_models, pretrained)
        spectral_anom = compute_spectral_anomaly(adv_model, clean_models, pretrained)

        # Compute pre-merge BSR
        pre_bsr, pre_cosine = compute_bsr(
            adv_model, pretrained, backdoor_direction, cfg.bsr_threshold
        )

        for algo_name, merge_fn in MERGE_ALGORITHMS.items():
            # Combine clean models with adversarial model (adversary is last)
            all_models = np.vstack([clean_models, adv_model[np.newaxis, :]])

            # Merge
            if algo_name == "DARE":
                merged = merge_fn(all_models, pretrained,
                                  drop_rate=0.5,
                                  rng=np.random.RandomState(rng_seed))
            else:
                merged = merge_fn(all_models, pretrained)

            # Compute post-merge BSR
            post_bsr, post_cosine = compute_bsr(
                merged, pretrained, backdoor_direction, cfg.bsr_threshold
            )

            # BSR retention
            bsr_retention = post_bsr / pre_bsr if pre_bsr > 0.01 else 0.0

            results.append(AttackResult(
                strategy_name=strategy_name,
                merge_algorithm=algo_name,
                bsr_retention=bsr_retention,
                cosine_retention=post_cosine,
                l2_detectability=l2_detect,
                spectral_anomaly=spectral_anom,
            ))

    return results


def run_experiment(cfg: SimConfig) -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    Run the full experiment: all strategies x all algorithms x multiple trials.

    Returns nested dict: strategy -> algorithm -> metric -> value
    """
    all_results: List[AttackResult] = []

    for trial in range(cfg.n_trials):
        trial_results = run_single_trial(cfg, rng_seed=SEED + trial * 137)
        all_results.extend(trial_results)

    # Aggregate results
    aggregated: Dict[str, Dict[str, Dict[str, List[float]]]] = {}

    for r in all_results:
        if r.strategy_name not in aggregated:
            aggregated[r.strategy_name] = {}
        if r.merge_algorithm not in aggregated[r.strategy_name]:
            aggregated[r.strategy_name][r.merge_algorithm] = {
                "bsr_retention": [],
                "cosine_retention": [],
                "l2_detectability": [],
                "spectral_anomaly": [],
            }

        bucket = aggregated[r.strategy_name][r.merge_algorithm]
        bucket["bsr_retention"].append(r.bsr_retention)
        bucket["cosine_retention"].append(r.cosine_retention)
        bucket["l2_detectability"].append(r.l2_detectability)
        bucket["spectral_anomaly"].append(r.spectral_anomaly)

    # Compute means and stds
    summary: Dict[str, Dict[str, Dict[str, float]]] = {}
    for strat in aggregated:
        summary[strat] = {}
        for algo in aggregated[strat]:
            summary[strat][algo] = {}
            for metric, values in aggregated[strat][algo].items():
                summary[strat][algo][f"{metric}_mean"] = float(np.mean(values))
                summary[strat][algo][f"{metric}_std"] = float(np.std(values))

    return summary


# =============================================================================
# SECTION 8: Analysis and Reporting
# =============================================================================

def print_results_table(summary: Dict) -> str:
    """Format results as a readable table."""
    lines = []
    lines.append("=" * 100)
    lines.append("ACTIVE ATTACK SIMULATION RESULTS: BSR RETENTION AFTER MERGING")
    lines.append("=" * 100)
    lines.append("")

    # Table 1: BSR Retention (mean +/- std)
    lines.append("TABLE 1: BSR Retention Ratio (higher = backdoor survives better)")
    lines.append("-" * 100)

    header = f"{'Strategy':<35} | {'Simple Avg':>10} | {'Weighted':>10} | {'TIES':>10} | {'DARE':>10} | {'SLERP':>10}"
    lines.append(header)
    lines.append("-" * 100)

    algo_order = ["Simple Average", "Weighted Average", "TIES", "DARE", "SLERP"]

    for strat in ATTACK_STRATEGIES.keys():
        row = f"{strat:<35}"
        for algo in algo_order:
            mean = summary[strat][algo]["bsr_retention_mean"]
            std = summary[strat][algo]["bsr_retention_std"]
            row += f" | {mean:>5.3f}+{std:.2f}"
        lines.append(row)

    lines.append("-" * 100)
    lines.append("")

    # Table 2: Detectability
    lines.append("TABLE 2: Detectability Metrics (lower = harder to detect)")
    lines.append("-" * 80)
    header2 = f"{'Strategy':<35} | {'L2 Ratio':>10} | {'Spectral Anomaly':>16}"
    lines.append(header2)
    lines.append("-" * 80)

    for strat in ATTACK_STRATEGIES.keys():
        # Detectability is the same across merge algorithms (measured pre-merge)
        first_algo = algo_order[0]
        l2_mean = summary[strat][first_algo]["l2_detectability_mean"]
        l2_std = summary[strat][first_algo]["l2_detectability_std"]
        spec_mean = summary[strat][first_algo]["spectral_anomaly_mean"]
        spec_std = summary[strat][first_algo]["spectral_anomaly_std"]
        lines.append(
            f"{strat:<35} | {l2_mean:>5.2f}+{l2_std:.2f} | {spec_mean:>10.4f}+{spec_std:.4f}"
        )

    lines.append("-" * 80)
    lines.append("")

    # Table 3: Improvement over naive baseline
    lines.append("TABLE 3: Improvement Factor over Naive Baseline (BSR Retention)")
    lines.append("-" * 100)
    lines.append(header)
    lines.append("-" * 100)

    naive_key = "Naive (Baseline)"
    for strat in ATTACK_STRATEGIES.keys():
        row = f"{strat:<35}"
        for algo in algo_order:
            strat_mean = summary[strat][algo]["bsr_retention_mean"]
            naive_mean = summary[naive_key][algo]["bsr_retention_mean"]
            if naive_mean > 0.01:
                improvement = strat_mean / naive_mean
            else:
                improvement = float('inf') if strat_mean > 0.01 else 1.0
            row += f" | {improvement:>10.2f}x"
        lines.append(row)

    lines.append("-" * 100)
    lines.append("")

    # Effectiveness-Detectability Tradeoff
    lines.append("TABLE 4: Effectiveness vs Detectability Tradeoff")
    lines.append("-" * 80)
    lines.append(f"{'Strategy':<35} | {'Avg BSR Ret':>11} | {'L2 Detect':>9} | {'Stealth Score':>13}")
    lines.append("-" * 80)

    for strat in ATTACK_STRATEGIES.keys():
        avg_bsr = np.mean([
            summary[strat][algo]["bsr_retention_mean"] for algo in algo_order
        ])
        l2_mean = summary[strat][algo_order[0]]["l2_detectability_mean"]
        # Stealth score: effectiveness / detectability
        stealth = avg_bsr / l2_mean if l2_mean > 0 else 0.0
        lines.append(f"{strat:<35} | {avg_bsr:>11.4f} | {l2_mean:>9.3f} | {stealth:>13.4f}")

    lines.append("-" * 80)
    lines.append("")

    return "\n".join(lines)


def analyze_strategy_effectiveness(summary: Dict) -> str:
    """Provide qualitative analysis of each strategy."""
    lines = []
    lines.append("=" * 80)
    lines.append("ANALYSIS: STRATEGY EFFECTIVENESS AND IMPLICATIONS")
    lines.append("=" * 80)
    lines.append("")

    algo_order = ["Simple Average", "Weighted Average", "TIES", "DARE", "SLERP"]
    naive_key = "Naive (Baseline)"

    for strat in ATTACK_STRATEGIES.keys():
        lines.append(f"--- {strat} ---")

        avg_retention = np.mean([
            summary[strat][algo]["bsr_retention_mean"] for algo in algo_order
        ])
        best_algo = max(algo_order,
                        key=lambda a: summary[strat][a]["bsr_retention_mean"])
        worst_algo = min(algo_order,
                         key=lambda a: summary[strat][a]["bsr_retention_mean"])
        best_val = summary[strat][best_algo]["bsr_retention_mean"]
        worst_val = summary[strat][worst_algo]["bsr_retention_mean"]

        l2 = summary[strat][algo_order[0]]["l2_detectability_mean"]
        spectral = summary[strat][algo_order[0]]["spectral_anomaly_mean"]

        lines.append(f"  Average BSR Retention: {avg_retention:.4f}")
        lines.append(f"  Best algorithm:  {best_algo} ({best_val:.4f})")
        lines.append(f"  Worst algorithm: {worst_algo} ({worst_val:.4f})")
        lines.append(f"  L2 Detectability: {l2:.3f}x (1.0 = same as clean)")
        lines.append(f"  Spectral Anomaly: {spectral:.4f} (0.0 = perfectly hidden)")

        # Improvement over naive
        naive_avg = np.mean([
            summary[naive_key][algo]["bsr_retention_mean"] for algo in algo_order
        ])
        if naive_avg > 0.01:
            improvement = avg_retention / naive_avg
            lines.append(f"  Overall improvement over naive: {improvement:.2f}x")
        lines.append("")

    # Overall conclusions
    lines.append("=" * 80)
    lines.append("KEY FINDINGS")
    lines.append("=" * 80)
    lines.append("")

    # Find best strategy overall
    best_strat = max(
        ATTACK_STRATEGIES.keys(),
        key=lambda s: np.mean([
            summary[s][a]["bsr_retention_mean"] for a in algo_order
        ])
    )
    best_avg = np.mean([
        summary[best_strat][a]["bsr_retention_mean"] for a in algo_order
    ])

    # Find most stealthy
    stealthiest = min(
        ATTACK_STRATEGIES.keys(),
        key=lambda s: summary[s][algo_order[0]]["l2_detectability_mean"]
    )

    # Find best tradeoff
    tradeoffs = {}
    for strat in ATTACK_STRATEGIES.keys():
        avg_bsr = np.mean([
            summary[strat][a]["bsr_retention_mean"] for a in algo_order
        ])
        l2 = summary[strat][algo_order[0]]["l2_detectability_mean"]
        tradeoffs[strat] = avg_bsr / l2 if l2 > 0 else 0.0
    best_tradeoff = max(tradeoffs, key=tradeoffs.get)

    lines.append(f"1. MOST EFFECTIVE: {best_strat}")
    lines.append(f"   Average BSR retention: {best_avg:.4f}")
    lines.append("")
    lines.append(f"2. MOST STEALTHY: {stealthiest}")
    l2_stealth = summary[stealthiest][algo_order[0]]["l2_detectability_mean"]
    lines.append(f"   L2 detectability ratio: {l2_stealth:.3f}")
    lines.append("")
    lines.append(f"3. BEST TRADEOFF: {best_tradeoff}")
    lines.append(f"   Stealth score (effectiveness/detectability): {tradeoffs[best_tradeoff]:.4f}")
    lines.append("")

    # Vulnerability of each merge algorithm
    lines.append("MERGE ALGORITHM VULNERABILITY RANKING:")
    lines.append("(Average BSR retention across all attack strategies, higher = more vulnerable)")
    lines.append("")

    algo_vulnerability = {}
    for algo in algo_order:
        avg = np.mean([
            summary[strat][algo]["bsr_retention_mean"]
            for strat in ATTACK_STRATEGIES.keys()
        ])
        algo_vulnerability[algo] = avg

    sorted_algos = sorted(algo_vulnerability.items(), key=lambda x: x[1], reverse=True)
    for rank, (algo, vuln) in enumerate(sorted_algos, 1):
        lines.append(f"  {rank}. {algo}: {vuln:.4f}")

    lines.append("")
    lines.append("THEORETICAL FEASIBILITY ASSESSMENT:")
    lines.append("")
    lines.append("A merge-persistent backdoor is THEORETICALLY FEASIBLE when:")
    lines.append(f"  - Best strategy achieves {best_avg:.1%} BSR retention on average")
    lines.append(f"  - Magnitude amplification alone provides {np.mean([summary['Magnitude Amplification (k=5)'][a]['bsr_retention_mean'] for a in algo_order]):.1%} retention")
    lines.append(f"  - Sign alignment specifically counters TIES pruning")
    lines.append(f"  - Spectral hiding reduces detectability to {summary['Spectral Hiding (k=5, amp=3)'][algo_order[0]]['spectral_anomaly_mean']:.4f} anomaly score")
    lines.append("")

    return "\n".join(lines)


# =============================================================================
# SECTION 9: Parameter Sensitivity Analysis
# =============================================================================

def run_amplification_sweep(cfg: SimConfig) -> str:
    """Sweep amplification factor k and measure BSR retention vs detectability."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("SENSITIVITY ANALYSIS: Amplification Factor k")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"{'k':>5} | {'SimpleAvg BSR':>13} | {'TIES BSR':>10} | {'DARE BSR':>10} | {'L2 Ratio':>10}")
    lines.append("-" * 60)

    for k in [1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0, 20.0]:
        retentions = {"Simple Average": [], "TIES": [], "DARE": []}
        l2_ratios = []

        for trial in range(cfg.n_trials):
            rng = np.random.RandomState(SEED + trial * 137)
            np.random.seed(SEED + trial * 137)

            pretrained = rng.randn(cfg.param_dim) * cfg.pretrained_scale
            clean_models = pretrained[np.newaxis, :] + (
                rng.randn(cfg.n_clean_models, cfg.param_dim) * cfg.clean_noise_scale
            )
            backdoor_direction = rng.randn(cfg.param_dim)
            backdoor_direction = backdoor_direction / np.linalg.norm(backdoor_direction)

            # Generate amplified model
            np.random.seed(SEED + trial * 137 + 999)
            adv_model = strategy_magnitude_amplification(
                pretrained, backdoor_direction, clean_models, cfg,
                amplification_factor=k
            )

            l2_ratios.append(
                compute_l2_detectability(adv_model, clean_models, pretrained)
            )

            # Pre-merge BSR
            pre_bsr, _ = compute_bsr(
                adv_model, pretrained, backdoor_direction, cfg.bsr_threshold
            )

            # Merge with each algorithm
            all_models = np.vstack([clean_models, adv_model[np.newaxis, :]])

            for algo_name, merge_fn in [
                ("Simple Average", merge_simple_average),
                ("TIES", merge_ties),
                ("DARE", merge_dare),
            ]:
                if algo_name == "DARE":
                    merged = merge_fn(all_models, pretrained, drop_rate=0.5,
                                      rng=np.random.RandomState(SEED + trial))
                else:
                    merged = merge_fn(all_models, pretrained)

                post_bsr, _ = compute_bsr(
                    merged, pretrained, backdoor_direction, cfg.bsr_threshold
                )
                retention = post_bsr / pre_bsr if pre_bsr > 0.01 else 0.0
                retentions[algo_name].append(retention)

        lines.append(
            f"{k:>5.1f} | {np.mean(retentions['Simple Average']):>13.4f} | "
            f"{np.mean(retentions['TIES']):>10.4f} | "
            f"{np.mean(retentions['DARE']):>10.4f} | "
            f"{np.mean(l2_ratios):>10.2f}"
        )

    lines.append("-" * 60)
    lines.append("")
    return "\n".join(lines)


def run_dare_robustness_analysis(cfg: SimConfig) -> str:
    """Analyze distributed encoding's robustness to different DARE drop rates."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("SENSITIVITY ANALYSIS: Distributed Encoding vs DARE Drop Rate")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"{'Drop Rate':>9} | {'Naive BSR Ret':>13} | {'Distributed BSR Ret':>19} | {'Improvement':>11}")
    lines.append("-" * 65)

    for drop_rate in [0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9]:
        naive_rets = []
        dist_rets = []

        for trial in range(cfg.n_trials):
            rng = np.random.RandomState(SEED + trial * 137)
            np.random.seed(SEED + trial * 137)

            pretrained = rng.randn(cfg.param_dim) * cfg.pretrained_scale
            clean_models = pretrained[np.newaxis, :] + (
                rng.randn(cfg.n_clean_models, cfg.param_dim) * cfg.clean_noise_scale
            )
            backdoor_direction = rng.randn(cfg.param_dim)
            backdoor_direction = backdoor_direction / np.linalg.norm(backdoor_direction)

            # Naive
            np.random.seed(SEED + trial * 137 + 100)
            naive_model = strategy_naive(pretrained, backdoor_direction, clean_models, cfg)
            pre_bsr_naive, _ = compute_bsr(
                naive_model, pretrained, backdoor_direction, cfg.bsr_threshold
            )

            # Distributed
            np.random.seed(SEED + trial * 137 + 200)
            dist_model = strategy_distributed_encoding(
                pretrained, backdoor_direction, clean_models, cfg, n_copies=10
            )
            pre_bsr_dist, _ = compute_bsr(
                dist_model, pretrained, backdoor_direction, cfg.bsr_threshold
            )

            # DARE merge
            for model, pre_bsr, result_list in [
                (naive_model, pre_bsr_naive, naive_rets),
                (dist_model, pre_bsr_dist, dist_rets),
            ]:
                all_models = np.vstack([clean_models, model[np.newaxis, :]])
                merged = merge_dare(
                    all_models, pretrained, drop_rate=drop_rate,
                    rng=np.random.RandomState(SEED + trial)
                )
                post_bsr, _ = compute_bsr(
                    merged, pretrained, backdoor_direction, cfg.bsr_threshold
                )
                retention = post_bsr / pre_bsr if pre_bsr > 0.01 else 0.0
                result_list.append(retention)

        naive_mean = np.mean(naive_rets)
        dist_mean = np.mean(dist_rets)
        improvement = dist_mean / naive_mean if naive_mean > 0.01 else 0.0

        lines.append(
            f"{drop_rate:>9.1f} | {naive_mean:>13.4f} | "
            f"{dist_mean:>19.4f} | {improvement:>10.2f}x"
        )

    lines.append("-" * 65)
    lines.append("")
    return "\n".join(lines)


# =============================================================================
# SECTION 10: Combined Attack Strategy
# =============================================================================

def strategy_combined(
    pretrained: np.ndarray,
    backdoor_direction: np.ndarray,
    clean_models: np.ndarray,
    cfg: SimConfig,
    amplification: float = 3.0,
    n_copies: int = 5,
    spectral_weight: float = 0.5
) -> np.ndarray:
    """
    Combined strategy: merge the best aspects of all four strategies.

    1. Project backdoor onto spectral subspace (hiding)
    2. Align signs with majority (TIES survival)
    3. Distribute across redundant copies (DARE survival)
    4. Amplify overall magnitude (average dilution compensation)
    """
    clean_noise = np.random.randn(cfg.param_dim) * cfg.clean_noise_scale

    # Step 1: Spectral projection
    clean_deltas = clean_models - pretrained[np.newaxis, :]
    centered = clean_deltas - np.mean(clean_deltas, axis=0)[np.newaxis, :]
    U, S, Vt = np.linalg.svd(centered, full_matrices=False)
    k = min(4, Vt.shape[0])
    top_components = Vt[:k, :]

    projections = top_components @ backdoor_direction
    spectral_part = top_components.T @ projections
    spectral_part = spectral_part / (np.linalg.norm(spectral_part) + 1e-10)

    # Blend spectral-hidden direction with original
    blended_direction = (spectral_weight * spectral_part +
                         (1 - spectral_weight) * backdoor_direction)
    blended_direction = blended_direction / np.linalg.norm(blended_direction)

    # Step 2: Sign alignment
    sign_votes = np.sign(np.sum(np.sign(clean_deltas), axis=0))
    sign_votes[sign_votes == 0] = 1.0

    # Step 3: Distributed encoding with sign alignment
    total_delta = np.zeros(cfg.param_dim)
    strength_per_copy = (cfg.backdoor_strength * np.sqrt(cfg.param_dim) *
                         amplification / np.sqrt(n_copies))

    for _ in range(n_copies):
        noise = np.random.randn(cfg.param_dim) * 0.05
        rotated = blended_direction + noise
        rotated = rotated / np.linalg.norm(rotated)

        # Sign-align this copy
        copy_delta = np.abs(rotated) * strength_per_copy * sign_votes
        total_delta += copy_delta

    total_delta = total_delta / n_copies  # Normalize by copies

    return pretrained + clean_noise + total_delta


def run_combined_analysis(cfg: SimConfig) -> str:
    """Test the combined strategy against all algorithms."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("COMBINED ATTACK STRATEGY ANALYSIS")
    lines.append("=" * 80)
    lines.append("")

    algo_order = ["Simple Average", "Weighted Average", "TIES", "DARE", "SLERP"]

    retentions = {algo: [] for algo in algo_order}
    l2_ratios = []
    spectral_scores = []

    for trial in range(cfg.n_trials):
        rng = np.random.RandomState(SEED + trial * 137)
        np.random.seed(SEED + trial * 137)

        pretrained = rng.randn(cfg.param_dim) * cfg.pretrained_scale
        clean_models = pretrained[np.newaxis, :] + (
            rng.randn(cfg.n_clean_models, cfg.param_dim) * cfg.clean_noise_scale
        )
        backdoor_direction = rng.randn(cfg.param_dim)
        backdoor_direction = backdoor_direction / np.linalg.norm(backdoor_direction)

        np.random.seed(SEED + trial * 137 + 777)
        adv_model = strategy_combined(
            pretrained, backdoor_direction, clean_models, cfg
        )

        l2_ratios.append(
            compute_l2_detectability(adv_model, clean_models, pretrained)
        )
        spectral_scores.append(
            compute_spectral_anomaly(adv_model, clean_models, pretrained)
        )

        pre_bsr, _ = compute_bsr(
            adv_model, pretrained, backdoor_direction, cfg.bsr_threshold
        )

        all_models = np.vstack([clean_models, adv_model[np.newaxis, :]])

        for algo_name in algo_order:
            merge_fn = MERGE_ALGORITHMS[algo_name]
            if algo_name == "DARE":
                merged = merge_fn(all_models, pretrained, drop_rate=0.5,
                                  rng=np.random.RandomState(SEED + trial))
            else:
                merged = merge_fn(all_models, pretrained)

            post_bsr, _ = compute_bsr(
                merged, pretrained, backdoor_direction, cfg.bsr_threshold
            )
            retention = post_bsr / pre_bsr if pre_bsr > 0.01 else 0.0
            retentions[algo_name].append(retention)

    lines.append(f"{'Algorithm':<20} | {'BSR Retention Mean':>18} | {'Std':>8}")
    lines.append("-" * 55)
    for algo in algo_order:
        mean = np.mean(retentions[algo])
        std = np.std(retentions[algo])
        lines.append(f"{algo:<20} | {mean:>18.4f} | {std:>8.4f}")

    lines.append("-" * 55)
    lines.append(f"\nDetectability:")
    lines.append(f"  L2 Ratio (mean):       {np.mean(l2_ratios):.3f}")
    lines.append(f"  Spectral Anomaly:      {np.mean(spectral_scores):.4f}")
    lines.append(f"  Average BSR Retention: {np.mean([np.mean(retentions[a]) for a in algo_order]):.4f}")
    lines.append("")

    return "\n".join(lines)


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main() -> str:
    """Run the full simulation and return complete output."""
    cfg = SimConfig()
    output_parts = []

    output_parts.append("=" * 80)
    output_parts.append("ACTIVE BACKDOOR ATTACK STRATEGIES vs MODEL MERGING ALGORITHMS")
    output_parts.append("Simulation of Merge-Persistent Backdoor Feasibility")
    output_parts.append("=" * 80)
    output_parts.append("")
    output_parts.append(f"Configuration:")
    output_parts.append(f"  Parameter dimensions: {cfg.param_dim}")
    output_parts.append(f"  Clean models in pool: {cfg.n_clean_models}")
    output_parts.append(f"  Trials per experiment: {cfg.n_trials}")
    output_parts.append(f"  BSR threshold: {cfg.bsr_threshold}")
    output_parts.append(f"  Backdoor strength: {cfg.backdoor_strength}")
    output_parts.append("")

    # Main experiment
    print("Running main experiment (5 strategies x 5 algorithms x 20 trials)...")
    summary = run_experiment(cfg)

    output_parts.append(print_results_table(summary))
    output_parts.append(analyze_strategy_effectiveness(summary))

    # Sensitivity analyses
    print("Running amplification sweep...")
    output_parts.append(run_amplification_sweep(cfg))

    print("Running DARE robustness analysis...")
    output_parts.append(run_dare_robustness_analysis(cfg))

    print("Running combined strategy analysis...")
    output_parts.append(run_combined_analysis(cfg))

    full_output = "\n".join(output_parts)
    print(full_output)
    return full_output


if __name__ == "__main__":
    result = main()
