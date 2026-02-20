"""Artifact dv-013 - Synthetic test case."""

def process_data_13(data: list[int]) -> int:
    """Process data."""
    return sum(data)

class Processor13:
    """Data processor."""

    def __init__(self):
        self.data = []

    def add(self, item: int) -> None:
        self.data.append(item)
