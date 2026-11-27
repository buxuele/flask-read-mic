from ApplicationServices import (
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    kAXTrustedCheckOptionPrompt,
)
from AVFoundation import AVCaptureDevice

MIC_MEDIA = "soun"

MIC_TEXT = {
    0: "未授权",
    1: "受限",
    2: "已拒绝",
    3: "已授权",
}


def mic_status():
    return AVCaptureDevice.authorizationStatusForMediaType_(MIC_MEDIA)


def mic_text():
    return MIC_TEXT.get(mic_status(), "未知")


def request_mic(callback=None):
    handler = callback if callback else (lambda granted: None)
    AVCaptureDevice.requestAccessForMediaType_completionHandler_(MIC_MEDIA, handler)


def ax_trusted(prompt=False):
    if prompt:
        return AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    return AXIsProcessTrusted()
