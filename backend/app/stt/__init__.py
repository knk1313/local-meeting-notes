"""STT (音声認識) プロバイダ抽象化層。"""

from app.stt.base import ProgressCallback, Segment, SttError, SttProvider

__all__ = ["ProgressCallback", "Segment", "SttError", "SttProvider"]
