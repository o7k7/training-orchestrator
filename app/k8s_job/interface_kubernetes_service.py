from abc import ABC, abstractmethod


class IKubernetesService(ABC):
    @abstractmethod
    def list_pods(self):
        pass