from abc import ABC, abstractmethod
from typing import Any, List


class PipelineLayer(ABC):
    @abstractmethod
    def run(self, input_data: List[Any]) -> List[Any]:
        pass
