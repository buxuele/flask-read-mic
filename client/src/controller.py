import difflib
import logging
import queue
import re
import threading
import time

log = logging.getLogger("mic")


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
        store=None,
        verify_min_seconds=4.0,
        verify_max_seconds=20.0,
        on_verify=None,
        stream_mode="pause",
        stream_step=0.5,
        stream_window=6.0,
        stream_holdback=4,
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
        self.store = store
        self.verify_min_seconds = verify_min_seconds
        self.verify_max_seconds = verify_max_seconds
        self.stream_mode = stream_mode
        self.stream_step = stream_step
        self.stream_window = stream_window
        self.stream_holdback = stream_holdback
        self.streamer = None
        self.stream_thread = None
        if stream_mode == "agreement":
            recorder.emit_chunks = False
        self.on_verify = on_verify
        self.session_chunks = []
        self.session_base = None
        self.session_texts = {}
        self.last_verify = ""
        self.last_verify_match = True
        self.verify_queue = queue.Queue()
        threading.Thread(target=self._verify_work, daemon=True).start()
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
        self.session_chunks = []
        self.session_base = None
        self.session_texts = {}
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
        if self.stream_mode == "agreement":
            self._start_stream()

    def _start_stream(self):
        from stream import Streamer

        self.streamer = Streamer(
            read_audio=self.recorder.read_since,
            asr=lambda wav, ctx: self.run_asr(self.prepare(wav), ctx),
            deliver=self._deliver_stream,
            step=self.stream_step,
            window=self.stream_window,
            holdback=self.stream_holdback,
        )
        self.streamer.context = self.context
        self.stream_running = True
        self.stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self.stream_thread.start()

    def _stream_loop(self):
        while self.stream_running:
            time.sleep(self.streamer.step)
            if not self.stream_running:
                break
            if self.recorder.silence_seconds >= 0.5:
                self.streamer.finalize()
            else:
                self.streamer.tick()

    def _deliver_stream(self, text, elapsed):
        with self.deliver_lock:
            self.context = (self.context + text)[-400:]
            self.last_text = text
            self.last_elapsed = elapsed
            self.on_text(text, elapsed)

    def _stop_stream(self, final):
        if self.streamer is None:
            return
        self.stream_running = False
        thread = self.stream_thread
        if thread is not None:
            thread.join(timeout=2)
        if final:
            self.streamer.finalize()
        self.streamer = None
        self.stream_thread = None

    def poll(self):
        if self.state != "recording":
            return
        for chunk in self.recorder.take_chunks():
            self._submit(chunk)

    def release(self):
        if self.state != "recording":
            return
        if self.stream_mode == "agreement":
            self._stop_stream(final=True)
            recorder = self.recorder
            chunks, seconds, rms, full = recorder.stop()
            self._save(full, seconds, rms, [], [])
            self._set_state("idle")
            return
        if self.combo or self.blocked:
            self.recorder.drop()
            self._set_state("idle")
            return

        chunks, seconds, rms, full = self.recorder.stop()

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

        metas = [{"seconds": chunk[1], "rms": chunk[2]} for chunk in chunks]
        self._save(full, seconds, rms, chunks, metas)

        for chunk, meta in zip(chunks, metas):
            self._submit(chunk, meta)

        if full is not None and self.verify_min_seconds <= seconds <= self.verify_max_seconds and self.seq > 0:
            self.verify_queue.put((self.epoch, self.seq, full, seconds))

        with self.lock:
            drained = self.pending == 0
        self._set_state("idle" if drained else "busy")

    def cancel(self):
        if self.state != "recording":
            return
        if self.stream_mode == "agreement":
            self._stop_stream(final=False)
            self.recorder.drop()
            self._set_state("idle")
            return
        with self.lock:
            self.epoch += 1
        self.recorder.drop()
        self._set_state("idle")

    def _save(self, full, seconds, rms, chunks, metas):
        if self.store is None or full is None or seconds < self.min_seconds:
            return
        try:
            self.session_chunks.extend(metas)
            self.session_base = self.store.start(full, seconds, rms, self.session_chunks)
            log.info("已保存录音 %s", self.session_base)
        except OSError as error:
            log.error("保存录音失败：%s", error)

    def _submit(self, packed, meta=None):
        wav, seconds, rms = packed
        if seconds < 0.2:
            log.info("丢弃片段：过短 %.2fs", seconds)
            return None
        log.info("切出片段 %.1fs 音量 %.0f", seconds, rms)
        with self.lock:
            self.seq += 1
            seq = self.seq
            epoch = self.epoch
            self.pending += 1
        if meta is None:
            meta = {"seconds": round(seconds, 2), "rms": round(rms, 1)}
            self.session_chunks.append(meta)
        meta["seq"] = seq
        meta["seconds"] = round(seconds, 2)
        meta["rms"] = round(rms, 1)
        self.queue.put((epoch, seq, wav))
        return seq

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
            if epoch != self.epoch:
                self._finish(seq, None)
                continue
            if not text:
                log.info("片段无文本，重试一次")
                try:
                    text = self.run_asr(self.prepare(wav), context).strip()
                except Exception as error:
                    self.on_error(str(error))
                    self._finish(seq, None)
                    continue
                if not text:
                    log.info("片段仍然无文本")
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
                    ready.append((self.done_seq, item[0], item[1]))
            drained = self.pending == 0 and self.state == "busy"

        if ready:
            with self.deliver_lock:
                for seq, text, elapsed in ready:
                    with self.lock:
                        self.context = (self.context + text)[-400:]
                    self.last_text = text
                    self.last_elapsed = elapsed
                    self.session_texts[seq] = text
                    if self.store is not None and self.session_base is not None:
                        for index, item in enumerate(self.session_chunks):
                            if item.get("seq") == seq:
                                self.store.set_text(self.session_base, index, text, elapsed)
                                break
                    self.on_text(text, elapsed)

        if drained:
            with self.lock:
                drained = self.pending == 0 and self.state == "busy"
            if drained:
                self._set_state("idle")


    def _verify_work(self):
        while True:
            epoch, target, wav, seconds = self.verify_queue.get()
            if epoch != self.epoch:
                continue
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                with self.lock:
                    done = self.done_seq
                if done >= target:
                    break
                time.sleep(0.05)
            else:
                continue
            with self.lock:
                busy = self.state != "idle" or self.pending > 0
            if busy:
                log.info("跳过复核：话筒还在用")
                continue
            with self.lock:
                keys = sorted(self.session_texts)
            spoken = "".join(self.session_texts[key] for key in keys)
            started = time.monotonic()
            try:
                text = self.run_asr(self.prepare(wav), "").strip()
            except Exception as error:
                log.error("复核失败：%s", error)
                continue
            if epoch != self.epoch or not text:
                continue
            elapsed = time.monotonic() - started
            matched = self.same_text(spoken, text)
            log.info(
                "复核%s：整段 %.1fs 片段拼接 %d 字 整段结果 %d 字",
                "一致" if matched else "有差异",
                elapsed,
                len(spoken),
                len(text),
            )
            self.last_verify = text
            self.last_verify_match = matched
            if self.store is not None and self.session_base is not None:
                try:
                    self.store.set_verify(self.session_base, text, elapsed, matched)
                except OSError as error:
                    log.error("保存复核结果失败：%s", error)
            if self.on_verify is not None:
                self.on_verify(text, matched)

    @staticmethod
    def same_text(first, second):
        clean = lambda value: re.sub(r"[\s，。！？、；：,.!?;:]", "", value)
        a, b = clean(first), clean(second)
        if not a or not b:
            return False
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.9
