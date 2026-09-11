"""STT (音声認識) プロバイダ抽象化層。"""

from app.stt.base import Segment, SttError, SttProvider
from app.stt.incremental import IncrementalChunkTranscriber

__all__ = ["IncrementalChunkTranscriber", "Segment", "SttError", "SttProvider"]
