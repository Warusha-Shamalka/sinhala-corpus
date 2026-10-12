"""Gemini API OCR backend for high-quality Sinhala text extraction.

Uses Google's Gemini Flash model via the google-generativeai SDK.
Free tier: 15 RPM / 1500 RPD at zero cost with a Google AI Studio API key.
Requires no local GPU — runs entirely via API call.
"""
from __future__ import annotations

import base64
import json
import re
import time
import unicodedata
from pathlib import Path


SINHALA_PROMPT = (
    'You are an expert Sinhala OCR transcriber for Sri Lankan educational documents.\n\n'
    'TASK: Extract ALL visible text from this page image exactly as written.\n\n'
    'RULES:\n'
    '1. Output the exact Sinhala Unicode text visible in the image.\n'
    '2. For multi-column pages, read LEFT column completely first, then RIGHT column.\n'
    '3. Preserve all Sinhala spelling, numbers, punctuation, question numbers, and answer choices.\n'
    '4. Represent mathematical expressions using LaTeX notation (e.g. $E = mc^2$).\n'
    '5. Do NOT translate Sinhala to English or any other language.\n'
    '6. Do NOT output Hindi, Devanagari, or any non-Sinhala script unless it appears in the original.\n'
    '7. Do NOT summarize, paraphrase, solve questions, correct spelling, or invent missing text.\n'
    '8. If text is genuinely illegible, write [අපැහැදිලියි] for that region.\n'
    '9. Ignore scanner watermarks like "Scanned with CamScanner".\n'
    '10. Output ONLY the transcription. No explanations, headers, or commentary.\n'
)


def clean_sinhala_text(text):
    """Post-process extracted text: normalize Unicode, strip artifacts."""
    text = unicodedata.normalize('NFC', text)
    lines = text.split('\n')
    cleaned = []
    loop_pattern = re.compile(r'(\b[\w\s]{2,20}\b)(?:\s*\1){3,}', re.IGNORECASE)
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append('')
            continue
        # Strip scanner watermarks
        if re.search(r'scanned with|camscanner', stripped, re.IGNORECASE):
            continue
        # Strip lines that are purely repetitive English loops
        if loop_pattern.search(stripped) and len(stripped) > 40:
            continue
        # Strip HTML artifacts from OCR output
        stripped = re.sub(r'<br\s*/?>', '\n', stripped)
        stripped = re.sub(r'</?(?:u|b|i|em|strong|math|sup|sub)>', '', stripped)
        cleaned.append(stripped)
    return '\n'.join(cleaned).strip()


class GeminiBackend:
    """OCR backend using Gemini API for high-quality Sinhala text extraction."""

    def __init__(self, api_key, model_name='gemini-3.8-flash', max_generation_seconds=120):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name or 'gemini-3.8-flash')
        self.model_name = model_name or 'gemini-3.8-flash'
        self.max_generation_seconds = max_generation_seconds
        self.identity = {
            'backend': 'gemini_api',
            'model': self.model_name,
            'max_generation_seconds': max_generation_seconds,
            'prompt': SINHALA_PROMPT[:100] + '...',
        }

    def recognize(self, image):
        """Send page image to Gemini API and return extracted Sinhala text."""
        from PIL import Image as PILImage
        import google.generativeai as genai

        start = time.monotonic()

        with PILImage.open(image) as img:
            pil_image = img.convert('RGB')

        try:
            response = self.model.generate_content(
                [SINHALA_PROMPT, pil_image],
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0,
                    max_output_tokens=8192,
                ),
                request_options={'timeout': self.max_generation_seconds},
            )

            if not response.text:
                return {
                    'text': '',
                    'outcome': 'empty',
                    'completion_status': 'no_response',
                    'seconds': round(time.monotonic() - start, 3),
                }

            text = clean_sinhala_text(response.text)

            return {
                'text': text,
                'generated_tokens': response.usage_metadata.candidates_token_count if response.usage_metadata else None,
                'completion_status': 'complete',
                'outcome': 'predicted',
            }

        except Exception as exc:
            return {
                'text': '',
                'outcome': 'failed',
                'completion_status': 'error',
                'error': f'{type(exc).__name__}: {exc}',
            }

