import io
import threading
import wave

import numpy as np
import sounddevice as sd


class Segmenter:
    def __init__(self, rate=16000, min_chunk=1.5, max_chunk=12.0, silence_gap=0.8, pad=0.25, threshold=500):
        self.rate = rate
        self.min_chunk = min_chunk
        self.max_chunk = max_chunk
        self.silence_gap = silence_gap
        self.pad = pad
        self.threshold = threshold
        self.blocks = []
        self.silence = 0.0
        self.speech = False

    def reset(self):
        self.blocks = []
        self.silence = 0.0
        self.speech = False

    def feed(self, block):
        block = block.reshape(-1, 1) if block.ndim == 1 else block
        if len(block) == 0:
            return []
        out = []
        duration = len(block) / self.rate
        peak = int(np.abs(block).max())

        if peak >= self.threshold:
            self.speech = True
            self.silence = 0.0
            self.blocks.append(block)
        elif self.speech:
            self.blocks.append(block)
            self.silence += duration
            if self.silence >= self.silence_gap and self.length() >= self.min_chunk:
                out.append(self.cut())

        if self.speech and self.length() >= self.max_chunk:
            out.append(self.cut())
        return out

    def length(self):
        return sum(len(block) for block in self.blocks) / self.rate

    def cut(self):
        blocks = list(self.blocks)
        drop_target = max(0.0, self.silence - self.pad)
        dropped = 0.0
        while blocks and drop_target > dropped and self.is_quiet(blocks[-1]):
            dropped += len(blocks[-1]) / self.rate
            blocks.pop()
        chunk = np.concatenate(blocks) if blocks else None
        self.reset()
        return chunk

    def flush(self):
        if not self.speech or not self.blocks:
            self.reset()
            return None
        return self.cut()

    def is_quiet(self, block):
        return int(np.abs(block).max()) < self.threshold


class Recorder:
    def __init__(self, rate=16000, device=None, threshold=500, silence_gap=0.8, on_chunk=None):
        self.rate = rate
        self.device = device
        self.threshold = threshold
        self.on_chunk = on_chunk
        self.segmenter = Segmenter(rate=rate, threshold=threshold, silence_gap=silence_gap)
        self.stream = None
        self.lock = threading.Lock()
        self.ready = []
        self.frames = 0
        self.sum_sq = 0.0

    def resolve_device(self):
        if self.device is None or isinstance(self.device, int):
            return self.device
        for index, info in enumerate(sd.query_devices()):
            if self.device.lower() in info["name"].lower() and info["max_input_channels"] > 0:
                return index
        raise RuntimeError(f"找不到麦克风：{self.device}")

    def start(self):
        device = self.resolve_device()
        with self.lock:
            self.ready = []
            self.frames = 0
            self.sum_sq = 0.0
            self.segmenter.reset()

        def callback(indata, frames, time_info, status):
            block = indata.copy()
            with self.lock:
                self.frames += len(block)
                samples = block.astype("float32")
                self.sum_sq += float(np.sum(samples * samples))
                finished = self.segmenter.feed(block)
            if self.on_chunk is None:
                with self.lock:
                    self.ready.extend(finished)
                return
            for chunk in finished:
                self.on_chunk(self.pack(chunk))

        self.stream = sd.InputStream(
            samplerate=self.rate,
            channels=1,
            dtype="int16",
            device=device,
            blocksize=1024,
            callback=callback,
        )
        self.stream.start()

    def take_chunks(self):
        with self.lock:
            chunks, self.ready = self.ready, []
        return [self.pack(chunk) for chunk in chunks if chunk is not None]

    def stop(self):
        with self.lock:
            stream, self.stream = self.stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self.lock:
            chunks, self.ready = self.ready, []
            final = self.segmenter.flush()
            frames, sum_sq = self.frames, self.sum_sq
        if final is not None:
            chunks.append(final)
        seconds = frames / self.rate
        rms = float(np.sqrt(sum_sq / frames)) if frames else 0.0
        return [self.pack(chunk) for chunk in chunks], seconds, rms

    def drop(self):
        with self.lock:
            stream, self.stream = self.stream, None
            self.ready = []
            self.segmenter.reset()
        if stream is not None:
            stream.stop()
            stream.close()

    def pack(self, chunk):
        seconds = len(chunk) / self.rate
        rms = float(np.sqrt(np.mean(chunk.astype("float32") ** 2))) if len(chunk) else 0.0
        return to_wav(chunk, self.rate), seconds, rms


def to_wav(data, rate):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data.tobytes())
    return buffer.getvalue()


def trim_wav(wav_bytes, threshold=300, pad=0.25):
    with wave.open(io.BytesIO(wav_bytes)) as handle:
        rate = handle.getframerate()
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype="int16").reshape(-1, 1)

    if len(data) == 0:
        return wav_bytes

    loud = np.where(np.abs(data[:, 0]) > threshold)[0]
    if len(loud) == 0:
        return wav_bytes

    padding = int(pad * rate)
    start = max(0, int(loud[0]) - padding)
    end = min(len(data), int(loud[-1]) + padding)
    if start == 0 and end == len(data):
        return wav_bytes
    return to_wav(data[start:end], rate)


def list_input_devices():
    devices = []
    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0:
            devices.append((index, info["name"]))
    return devices
