from decimal import Decimal
from numbers import Real


class Prompt:
    """Промпт"""

    def __init__(self, prompt: str):
        if not isinstance(prompt, str):
            raise TypeError("prompt должен быть строкой")

        self.prompt = prompt.strip()

    def __eq__(self, other):
        if not isinstance(other, Prompt):
            return NotImplemented
        return self.prompt == other.prompt

    def __repr__(self):
        return f"{self.prompt}"


class Seconds:
    """Продолжительность в секундах, не может быть отрицательной."""

    def __init__(self, seconds: Real):
        if isinstance(seconds, bool) or not isinstance(seconds, Real):
            raise TypeError("seconds должен быть числом")
        if seconds < 0:
            raise ValueError("Количество секунд не может быть отрицательным")

        self.seconds = float(seconds)

    def __add__(self, other):
        if not isinstance(other, Seconds):
            return NotImplemented
        return Seconds(self.seconds + other.seconds)

    def __sub__(self, other):
        if not isinstance(other, Seconds):
            return NotImplemented
        return Seconds(self.seconds - other.seconds)

    def __mul__(self, other):
        if isinstance(other, bool) or not isinstance(other, Real):
            return NotImplemented
        return Seconds(self.seconds * other)

    def __rmul__(self, other):
        return self.__mul__(other)

    def __eq__(self, other):
        if not isinstance(other, Seconds):
            return NotImplemented
        return self.seconds == other.seconds

    def __lt__(self, other):
        if not isinstance(other, Seconds):
            return NotImplemented
        return self.seconds < other.seconds

    def __le__(self, other):
        if not isinstance(other, Seconds):
            return NotImplemented
        return self.seconds <= other.seconds

    def __gt__(self, other):
        if not isinstance(other, Seconds):
            return NotImplemented
        return self.seconds > other.seconds

    def __ge__(self, other):
        if not isinstance(other, Seconds):
            return NotImplemented
        return self.seconds >= other.seconds

    def __repr__(self):
        return f"{self.seconds}"



class ModelAnswer:
    """Ответ модели."""

    def __init__(self, answer: str):
        if not isinstance(answer, str):
            raise TypeError("answer должен быть строкой")

        self.answer = answer

    def __eq__(self, other):
        if not isinstance(other, ModelAnswer):
            return NotImplemented
        return self.answer == other.answer

    def __repr__(self):
        return f"{self.answer}"


