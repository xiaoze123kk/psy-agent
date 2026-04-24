from __future__ import annotations

import base64
import hashlib
import hmac
import html
import random
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.config import settings


CAPTCHA_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CAPTCHA_TTL_SECONDS = 180


@dataclass
class CaptchaChallenge:
    answer_hash: str
    expires_at: datetime


class CaptchaStore:
    def __init__(self) -> None:
        self._challenges: dict[str, CaptchaChallenge] = {}

    def create(self) -> dict[str, object]:
        self._cleanup()
        challenge_id = str(uuid4())
        answer = "".join(secrets.choice(CAPTCHA_CHARS) for _ in range(5))
        self._challenges[challenge_id] = CaptchaChallenge(
            answer_hash=self._hash_answer(challenge_id, answer),
            expires_at=self._now() + timedelta(seconds=CAPTCHA_TTL_SECONDS),
        )
        return {
            "captcha_id": challenge_id,
            "image_data_url": self._render_svg_data_url(answer),
            "expires_in": CAPTCHA_TTL_SECONDS,
        }

    def verify(self, challenge_id: str, code: str) -> bool:
        self._cleanup()
        challenge = self._challenges.pop(challenge_id, None)
        if challenge is None or challenge.expires_at <= self._now():
            return False
        return hmac.compare_digest(challenge.answer_hash, self._hash_answer(challenge_id, code))

    def _cleanup(self) -> None:
        now = self._now()
        expired_ids = [challenge_id for challenge_id, challenge in self._challenges.items() if challenge.expires_at <= now]
        for challenge_id in expired_ids:
            self._challenges.pop(challenge_id, None)

    def _hash_answer(self, challenge_id: str, answer: str) -> str:
        normalized_answer = "".join(answer.split()).upper()
        payload = f"{challenge_id}:{normalized_answer}".encode("utf-8")
        return hmac.new(settings.secret_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _render_svg_data_url(answer: str) -> str:
        rng = random.SystemRandom()
        width = 150
        height = 52
        text_nodes = []
        for index, char in enumerate(answer):
            x = 24 + index * 22 + rng.randint(-2, 2)
            y = 34 + rng.randint(-4, 4)
            rotation = rng.randint(-14, 14)
            text_nodes.append(
                f'<text x="{x}" y="{y}" transform="rotate({rotation} {x} {y})">{html.escape(char)}</text>'
            )

        noise_lines = []
        for _ in range(7):
            noise_lines.append(
                (
                    f'<path d="M {rng.randint(0, width)} {rng.randint(8, height - 8)} '
                    f'C {rng.randint(20, width - 20)} {rng.randint(0, height)}, '
                    f'{rng.randint(20, width - 20)} {rng.randint(0, height)}, '
                    f'{rng.randint(0, width)} {rng.randint(8, height - 8)}" />'
                )
            )

        dots = []
        for _ in range(28):
            dots.append(
                f'<circle cx="{rng.randint(4, width - 4)}" cy="{rng.randint(4, height - 4)}" r="{rng.choice([1, 1.4, 1.8])}" />'
            )

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" rx="18" fill="#f0fdfa"/>
<g stroke="#99f6e4" stroke-width="1.3" fill="none" opacity="0.75">{''.join(noise_lines)}</g>
<g fill="#5eead4" opacity="0.7">{''.join(dots)}</g>
<g fill="#0f766e" font-family="Georgia, serif" font-size="25" font-weight="700" letter-spacing="2">{''.join(text_nodes)}</g>
</svg>"""
        encoded_svg = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded_svg}"


captcha_store = CaptchaStore()
