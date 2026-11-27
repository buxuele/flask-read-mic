import logging
import time

log = logging.getLogger("mic")
RATE = 16000


def common_prefix(first, second):
    limit = min(len(first), len(second))
    index = 0
    while index < limit and first[index] == second[index]:
        index += 1
    return first[:index]


class Streamer:
    def __init__(
        self,
        read_audio,
        asr,
        deliver,
        step=0.5,
        window=6.0,
        min_audio=1.0,
        holdback=4,
    ):
        self.read_audio = read_audio
        self.asr = asr
        self.deliver = deliver
        self.step = step
        self.window = window
        self.min_audio = min_audio
        self.holdback = holdback
        self.anchor = 0.0
        self.tail = ""
        self.prev = ""
        self.context = ""
        self.running = False

    def tick(self, final=False):
        audio, total = self.read_audio(self.anchor)
        span = total - self.anchor
        if span <= 0:
            return ""
        if span < self.min_audio and not final:
            return ""
        if span > self.window and not final:
            audio = audio[-int(self.window * RATE):]
            span = self.window

        started = time.monotonic()
        try:
            text = self.asr(audio, self.context + self.tail).strip()
        except Exception as error:
            log.info("流式请求失败：%s", error)
            return ""
        if not text:
            return ""

        delta = self.decide(text, span, final)
        if delta:
            self.deliver(delta, time.monotonic() - started)
            log.info("流式提交 %.1f 秒音频：%s", span, delta)
        self.prev = text
        return delta

    def decide(self, text, span, final):
        if final:
            same = text if text.startswith(self.tail) else common_prefix(self.tail, text)
        else:
            same = common_prefix(self.prev, text) if self.prev else ""
        if not same.startswith(self.tail):
            same = self.tail
        delta = same[len(self.tail):]
        if not final:
            delta = delta[:-self.holdback] if len(delta) > self.holdback else ""
        if not delta:
            return ""

        self.tail += delta
        ratio = len(self.tail) / max(len(text), 1)
        advance = ratio * span
        self.anchor = min(self.anchor + advance, self.anchor + span - 0.2)
        return delta

    def finalize(self):
        delta = self.tick(final=True)
        self.context = (self.context + self.tail)[-400:]
        self.anchor = self.read_audio(self.anchor)[1]
        self.tail = ""
        self.prev = ""
        return delta
