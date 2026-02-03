from abc import ABC, abstractmethod
from typing import Any, Dict

class LLMProvider(ABC):
    """
    Abstract Base Class for LLM Providers (OpenAI, Gemini, etc.)
    """
    
    @abstractmethod
    def generate_response(
        self, 
        system_prompt: str, 
        user_prompt: str,
        temperature: float = 0.7
    ) -> str:
        """
        Generate response from LLM
        
        Args:
            system_prompt: The system instruction / persona
            user_prompt: The user input / context
            temperature: Creativity control (0.0 - 1.0)
            
        Returns:
            The rigorous response content as string
        """
        pass
