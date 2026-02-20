"""Artifact dv-011 - Synthetic test case."""

def process_data_11(data: list[int]) -> int:
    """Process data."""
    return sum(data)

class Processor11:
    """Data processor."""

    def __init__(self):
        self.data = []

    def add(self, item: int) -> None:
        self.data.append(item)
