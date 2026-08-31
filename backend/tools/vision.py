import asyncio
import base64
from typing import Any, Dict, Optional
from main import load_config


class Vision:
    """Vision fallback using Gemini API for image analysis."""

    @staticmethod
    async def analyze_image(image_base64: str, mime_type: str, prompt: str = "",
                          api_key: str = "") -> Dict[str, Any]:
        """Analyze an image using Gemini vision API."""
        try:
            # Load config if no API key provided
            if not api_key:
                config = load_config()
                api_key = config.get("gemini_api_key", "")

            if not api_key:
                return {"status": "error", "message": "No Gemini API key configured for vision."}

            # Import Gemini client
            import urllib.request
            import json

            # Build the request
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

            payload = {
                "contents": [
                    {
                        "parts": [
                            {"inline_data": {"mime_type": mime_type, "data": image_base64}},
                            {"text": prompt or "Describe this image in detail, sir."}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.4
                }
            }

            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))

            # Extract the response text
            candidate = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            return {"status": "success", "message": candidate or "Image analyzed successfully"}

        except Exception as e:
            return {"status": "error", "message": f"Vision analysis failed: {str(e)[:200]}"}

    @staticmethod
    async def text_from_image(image_base64: str, mime_type: str = "image/png") -> Dict[str, Any]:
        """Extract text from an image using OCR/vision."""
        try:
            config = load_config()
            api_key = config.get("gemini_api_key", "")

            if not api_key:
                return {"status": "error", "message": "No Gemini API key configured for OCR."}

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

            payload = {
                "contents": [
                    {
                        "parts": [
                            {"inline_data": {"mime_type": mime_type, "data": image_base64}},
                            {"text": "Extract all text from this image. Return only the text, no analysis or commentary."}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1
                }
            }

            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))

            candidate = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            return {"status": "success", "text": candidate or ""}

        except Exception as e:
            return {"status": "error", "message": f"Text extraction from image failed: {str(e)[:200]}"}