"""Editable least-squares baseline; standard library only."""
DEGREE = 1


def fit(xs, ys):
    n = DEGREE + 1
    # Normal equations solved by Gaussian elimination with partial pivoting.
    matrix = [[sum(x ** (i + j) for x in xs) for j in range(n)]
              + [sum(y * x ** i for x, y in zip(xs, ys))] for i in range(n)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda k: abs(matrix[k][i]))
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        scale = matrix[i][i]
        matrix[i] = [value / scale for value in matrix[i]]
        for k in range(n):
            if k != i:
                scale = matrix[k][i]
                matrix[k] = [a - scale * b for a, b in zip(matrix[k], matrix[i])]
    weights = [row[-1] for row in matrix]
    return lambda x: sum(w * x ** i for i, w in enumerate(weights)), n
