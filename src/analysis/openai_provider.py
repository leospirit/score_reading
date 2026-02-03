import os
import logging
from typing import Optional
import openai
from .llm_provider import LLMProvider

logger = logging.getLogger(__name__)

from src.config import load_config

class OpenAIProvider(LLMProvider):
    """
    OpenAI-compatible implementation (GPT-4o, DeepSeek, etc.)
    """
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        config = load_config()
        
        # Priority: Constructor Arg > Config File > Env Var
        raw_key = (
            api_key 
            or config.get("llm.api_key") 
            or config.get("engines.gemini.api_key")
            or os.getenv("OPENAI_API_KEY")
        )

        if not raw_key:
            logger.warning("No API key found for LLM Advisor (Checked: llm.api_key, engines.gemini.api_key, OPENAI_API_KEY)")
        else:
            logger.info(f"LLM Advisor: Found API key(s) starting with {str(raw_key)[:8] if isinstance(raw_key, str) else 'List'}")
            
        # Support multiple keys (comma-separated or list)
        if isinstance(raw_key, str):
            self.api_keys = [k.strip() for k in raw_key.split(",") if k.strip()]
        elif isinstance(raw_key, list):
            self.api_keys = raw_key
        else:
            self.api_keys = []
            
        self.current_key_index = 0
        
        self.base_url = config.get("llm.base_url")
        self.model = (
            model 
            or config.get("llm.model") 
            or config.get("engines.gemini.model")
            or "gemini-1.5-flash" # Safe default for Gemini endpoint
        )
        
        # If we are using Gemini endpoint but model name looks like OpenAI, force Gemini
        if isinstance(raw_key, str) and raw_key.startswith("AIza") and self.model.startswith("gpt-"):
             self.model = config.get("engines.gemini.model") or "gemini-1.5-flash"

        logger.info(f"LLM Advisor initialized with model: {self.model}, base_url: {self.base_url or 'Default'}")
        
        self.client = None
        self.genai_model = None
        self.client_type = "none"
        
        if not self.api_keys:
            logger.warning("OPENAI_API_KEY not found in config or env. LLM features will be disabled.")
        else:
            self._init_client()
            
    def _init_client(self):
        """Initialize appropriate client based on current key"""
        current_key = self.api_keys[self.current_key_index]
        
        # Check if it's a Gemini Key
        if current_key.startswith("AIza"):
            import google.generativeai as genai
            genai.configure(api_key=current_key)
            self.client_type = "gemini"
            # Ensure model name doesn't have 'models/' prefix double added by SDK
            target_model = self.model
            if target_model.startswith("models/"):
                target_model = target_model.replace("models/", "")
            
            # Important: Keep it short for the SDK
            if "gemini" not in target_model.lower():
                target_model = "gemini-1.5-flash"
                
            self.genai_model = genai.GenerativeModel(target_model)
            logger.info(f"Initialized NATIVE Gemini client for Advisor (Model: {target_model})")
            
        # Check if it's a Zhipu AI Key (contains dot, like id.secret)
        elif "." in current_key and len(current_key) > 20 and not current_key.startswith("sk-"):
            self.client_type = "zhipu"
            
            # Zhipu uses OpenAI compatible endpoint
            base_url = "https://open.bigmodel.cn/api/paas/v4/"
            
            # Auto-switch model if it's not set or set to gemini/gpt default
            target_model = self.model
            if "gemini" in target_model or "gpt" in target_model:
                target_model = "glm-4-flash" # Default to fast/cheap model for Zhipu
                
            self.client = openai.OpenAI(
                api_key=current_key,
                base_url=base_url
            )
            # Update model reference for generation
            self.model = target_model
            logger.info(f"Initialized Zhipu AI client (GLM) for Advisor (Model: {self.model})")
            
        else:
            self.client_type = "openai"
            client_args = {"api_key": current_key}
            active_base_url = self.base_url
            if active_base_url:
                client_args["base_url"] = active_base_url
            self.client = openai.OpenAI(**client_args)
            logger.info(f"Initialized OpenAI-compatible client for Advisor (Model: {self.model})")
            
        # Log masked key
        masked = f"{current_key[:4]}...{current_key[-4:]}" if len(current_key) > 8 else "***"
        logger.info(f"LLM Client updated to key index {self.current_key_index} ({masked})")

    def _rotate_key(self):
        """Switch to the next available API key"""
        if len(self.api_keys) <= 1:
            return False
            
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self._init_client()
        logger.warning(f"Rotated to API Key #{self.current_key_index}")
        return True
            
    def generate_response(
        self, 
        system_prompt: str, 
        user_prompt: str,
        temperature: float = 0.7
    ) -> str:
        if not self.client and not self.genai_model:
            raise RuntimeError("LLM client not initialized (missing API key).")
            
        import time
        import random
        
        max_retries = 3
        # If we have multiple keys, we can try more times effectively
        if len(self.api_keys) > 1:
            max_retries = 5
            
        for attempt in range(max_retries):
            try:
                if self.client_type == "gemini":
                    # Use Native Gemini SDK
                    response = self.genai_model.generate_content(
                        f"{system_prompt}\n\n{user_prompt}",
                        generation_config={
                            "temperature": temperature,
                            "response_mime_type": "application/json"
                        }
                    )
                    return response.text or ""
                else:
                    # Use OpenAI Client
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=temperature,
                        response_format={"type": "json_object"}  # Force JSON mode
                    )
                    return response.choices[0].message.content or ""
                
            except Exception as e:
                is_last_attempt = attempt == max_retries - 1
                
                error_msg = str(e)
                logger.warning(f"LLM API Error (Attempt {attempt+1}/{max_retries}): {error_msg}")
                
                if is_last_attempt:
                    logger.error("Max retries reached. LLM call failed.")
                    raise
                
                # Try to rotate key first
                rotated = self._rotate_key()
                
                # If rotated, retry immediately (or with small jitter). 
                # If not rotated (single key), wait exponentially.
                if rotated:
                    time.sleep(0.5) 
                else:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.info(f"Waiting {sleep_time:.1f}s before retry...")
                    time.sleep(sleep_time)
                    
            except Exception as e:
                # Non-retryable errors (e.g. invalid request)
                logger.error(f"LLM Critical Error: {e}")
                raise
                
        raise RuntimeError("LLM Generation failed after retries")
