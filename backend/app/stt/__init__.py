"""STT (音声認識) プロバイダ抽象化層。"""

from app.stt.base import Segment, SttError, SttProvider

__all__ = ["Segment", "SttError", "SttProvider"]
