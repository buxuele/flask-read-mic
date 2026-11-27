import queue
import threading
import time


class Controller:
    WORKERS = 3

    def __init__(
        self,
        recorder,
        run_asr,
        on_state,
        on_text,
        on_error,
        min_seconds=0.3,
        max_seconds=280,
        audio_limit=295,
        min_rms=40,
        prepare=None,
    ):
        self.recorder = recorder
        self.run_asr = run_asr
        self.on_state = on_state
        self.on_text = on_text
        self.on_error = on_error
        self.min_seconds = min_seconds
        self.max_seconds = max_seconds
        self.audio_limit = audio_limit
        self.min_rms = min_rms
        self.prepare = prepare or (lambda wav: wav)
        self.state = "idle"
        self.combo = False
        self.blocked = False
        self.started_at = 0.0
        self.lock = threading.Lock()
        self.queue = queue.Queue()
        self.pending = 0
        self.epoch = 0
        self.seq = 0
        self.done_seq = 0
        self.results = {}
        self.deliver_lock = threading.Lock()
        self.context = ""
        self.last_text = ""
        self.last_elapsed = 0.0
        self.recorder.on_chunk = self._submit
        for _ in range(self.WORKERS):
            threading.Thread(target=self._work, daemon=True).start()

    def _set_state(self, state):
        with self.lock:
            if self.state == state:
                return
            self.state = state
        self.on_state(state)

    def elapsed(self):
        if self.state != "recording":
            return 0.0
        return time.monotonic() - self.started_at

    def press(self, combo=False):
        self.combo = combo
        self.blocked = False
        if combo or self.state == "recording":
            return
        try:
            self.recorder.start()
        except Exception as error:
            self.blocked = True
            self.on_error(f"麦克风不可用：{error}")
            return
        self.started_at = time.monotonic()
        self._set_state("recording")

    def poll(self):
        if self.state != "recording":
            return
        for chunk in self.recorder.take_chunks():
            self._submit(chunk)

    def release(self):
        if self.state != "recording":
            return
        if self.combo or self.blocked:
            self.recorder.drop()
            self._set_state("idle")
            return

        chunks, seconds, rms = self.recorder.stop()

        if seconds < self.min_seconds:
            self._set_state("idle")
            return
        if seconds > self.audio_limit:
            self.on_error("录音超过 295 秒，未上传")
            self._set_state("idle")
            return
        if not chunks and rms < self.min_rms:
            self.on_error("没有检测到声音")
            self._set_state("idle")
            return

        for chunk in chunks:
            self._submit(chunk)

        with self.lock:
            drained = self.pending == 0
        self._set_state("idle" if drained else "busy")

    def cancel(self):
        if self.state != "recording":
            return
        with self.lock:
            self.epoch += 1
        self.recorder.drop()
        self._set_state("idle")

    def _submit(self, packed):
        wav, seconds, rms = packed
        if seconds < 0.2 or rms < self.min_rms:
            return
        with self.lock:
            self.seq += 1
            seq = self.seq
            epoch = self.epoch
            self.pending += 1
        self.queue.put((epoch, seq, wav))

    def _work(self):
        while True:
            epoch, seq, wav = self.queue.get()
            if epoch != self.epoch:
                self._finish(seq, None)
                continue
            started = time.monotonic()
            try:
                with self.lock:
                    context = self.context[-400:]
                text = self.run_asr(self.prepare(wav), context).strip()
            except Exception as error:
                self.on_error(str(error))
                self._finish(seq, None)
                continue
            if epoch != self.epoch or not text:
                self._finish(seq, None)
                continue
            self._finish(seq, (text, time.monotonic() - started))

    def _finish(self, seq, result):
        with self.lock:
            self.results[seq] = result
            self.pending -= 1
            ready = []
            while self.done_seq + 1 in self.results:
                self.done_seq += 1
                item = self.results.pop(self.done_seq)
                if item is not None:
                    ready.append(item)
            drained = self.pending == 0 and self.state == "busy"

        if ready:
            with self.deliver_lock:
                for text, elapsed in ready:
                    with self.lock:
                        self.context = (self.context + text)[-400:]
                    self.last_text = text
                    self.last_elapsed = elapsed
                    self.on_text(text, elapsed)

        if drained:
            with self.lock:
                drained = self.pending == 0 and self.state == "busy"
            if drained:
                self._set_state("idle")
