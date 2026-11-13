"""Numerical mock only; no diffusion weights, triggers, or image generation."""
SETTINGS = {"composition": False, "neighbors": False, "phase": False, "gain": 1.0}


def solve(matrix, vector):
    """Small ridge normal equations, using pivoted elimination (stdlib only)."""
    n = len(vector)
    rows = [list(row) + [rhs] for row, rhs in zip(matrix, vector)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda i: abs(rows[i][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        scale = rows[col][col]
        if abs(scale) < 1e-12:
            raise ValueError("singular mock system")
        rows[col] = [v / scale for v in rows[col]]
        for i in range(n):
            if i != col:
                scale = rows[i][col]
                rows[i] = [a - scale * b for a, b in zip(rows[i], rows[col])]
    return [row[-1] for row in rows]


def fit(data, settings=None):
    cfg = SETTINGS if settings is None else settings
    selected = list(data["isolated"]) + list(data["clean"])
    if cfg["composition"]:
        selected += data["composition"]
    if cfg["neighbors"]:
        selected += data["neighbors"]
    if cfg["phase"]:
        selected += data["phase"]
    matrix = [[0.04 if i == j else 0.0 for j in range(4)] for i in range(4)]
    rhs = [0.0] * 4
    for features, target, weight in selected:
        for i in range(4):
            rhs[i] += weight * features[i] * target
            for j in range(4):
                matrix[i][j] += weight * features[i] * features[j]
    return [cfg["gain"] * w for w in solve(matrix, rhs)]
