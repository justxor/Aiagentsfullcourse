import math


def factorial(n: int) -> str:
    n = int(n)
    if n < 0:
        raise ValueError("факториал определён только для n >= 0")
    if n > 2000:
        raise ValueError("n слишком велико, предел 2000")
    return str(math.factorial(n))