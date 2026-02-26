"""Artifact dv-015 - Synthetic test case."""

def process_data_15(data: list[int]) -> int:
    """Process data."""
    return sum(data)

class Processor15:
    """Data processor."""

    def __init__(self):
        self.data = []

    def add(self, item: int) -> None:
        self.data.append(item)
