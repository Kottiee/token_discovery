from abc import ABC, abstractmethod
from typing import List, Any

class PipelineLayer(ABC):
    @abstractmethod
    def run(self, input_data: List[Any]) -> List[Any]:
        pass
