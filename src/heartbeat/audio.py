"""음원 재생 + 마스터 클럭.

`pygame.mixer + perf_counter()`를 쓰지 않는 이유: play() 호출과 실제 소리가 나오는
시점 사이의 지연을 알 수 없다. 여기서는 PortAudio가 콜백마다 알려주는
`outputBufferDacTime`(그 버퍼가 스피커로 나가는 시각)을 기준으로 삼아,
"지금 귀에 들리고 있는 음원 위치"를 추정한다.

    t = 버퍼_시작_샘플 / sr + (stream.time - 버퍼_DAC_시각) + AUDIO_OFFSET
"""
import threading

import numpy as np
import soundfile as sf


class AudioClock:
    """음원을 재생하면서 '현재 들리는 음원 시각'을 알려준다."""

    def __init__(self, path, offset: float = 0.0, stop_at: float | None = None,
                 fade: float = 0.5):
        import sounddevice as _sd         # PortAudio 및 오디오 백엔드 라이브러리 가용 여부 사전 검증
        self.data, self.sr = sf.read(str(path), dtype="float32", always_2d=True)
        self.offset = offset              # AUDIO_OFFSET: 측정으로 보정하는 상수(s)
        self.fade = fade                  # 끝에서 페이드아웃할 길이(s)
        self.stop_at = stop_at            # 이 시각(음원 기준)에서 재생을 멈춘다
        self._n = len(self.data)
        if stop_at is not None:
            self._n = min(self._n, int((stop_at + fade) * self.sr))
        self._played = 0
        self._lock = threading.Lock()
        self._mark = None                 # (버퍼 시작 샘플, 그 버퍼의 DAC 시각)
        self._stream = None
        self.finished = threading.Event()

    # ------------------------------------------------------------------ 재생
    def _callback(self, outdata, frames, time_info, status):
        import sounddevice as sd

        start = self._played
        chunk = self.data[start:start + frames]
        n = len(chunk)
        if n:
            outdata[:n] = chunk
            if self.stop_at is not None and self.fade > 0:
                # 마지막 fade초를 선형으로 줄여 뚝 끊기는 소리를 막는다
                idx = (np.arange(start, start + n) / self.sr)
                g = np.clip((self.stop_at + self.fade - idx) / self.fade, 0.0, 1.0)
                outdata[:n] *= g[:, None]
        outdata[n:] = 0
        self._played = start + n
        with self._lock:
            self._mark = (start, time_info.outputBufferDacTime)
        if n < frames:
            self.finished.set()
            raise sd.CallbackStop

    def start(self) -> "AudioClock":
        import sounddevice as sd

        self._stream = sd.OutputStream(
            samplerate=self.sr, channels=self.data.shape[1], dtype="float32",
            callback=self._callback, finished_callback=self.finished.set,
            latency="low",
        )
        self._stream.start()
        return self

    # ------------------------------------------------------------------ 클럭
    @property
    def t(self) -> float:
        """지금 들리고 있는 음원 시각(s). 재생 전/직후에는 0 근처의 음수일 수 있다."""
        with self._lock:
            mark = self._mark
        if mark is None or self._stream is None:
            return self.offset
        start, dac = mark
        return start / self.sr + (self._stream.time - dac) + self.offset

    @property
    def duration(self) -> float:
        return self._n / self.sr

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


class SilentClock:
    """음원 없이 실시간 속도로만 흐르는 클럭 (오디오 장치가 없을 때의 대체)."""

    def __init__(self, offset: float = 0.0, stop_at: float | None = None, **_):
        import time
        self._now = time.perf_counter
        self.offset = offset
        self.stop_at = stop_at
        self._t0 = None
        self.finished = threading.Event()

    def start(self):
        self._t0 = self._now()
        return self

    @property
    def t(self) -> float:
        if self._t0 is None:
            return self.offset
        t = self._now() - self._t0 + self.offset
        if self.stop_at is not None and t >= self.stop_at:
            self.finished.set()
        return t

    @property
    def duration(self) -> float:
        return float("inf") if self.stop_at is None else self.stop_at

    def stop(self) -> None:
        pass

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
