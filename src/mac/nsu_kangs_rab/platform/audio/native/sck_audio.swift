// K-18 시스템 사운드 수집 보조 프로세스 (ScreenCaptureKit 오디오). 결정 0064 6항, 첫 확인은 experiments/media/k18_sck_audio_probe.swift.
//
// 출력(stdout): 헤더 없는 원시 float32 little-endian, 인터리브 2채널, 48000 Hz. 오디오 외의 것은 쓰지 않는다.
// 오류(stderr): 한 줄 JSON {"error": "<분류>", "detail": "..."} 후 종료. 종료 코드:
//   0 정상(stdin 닫힘 · SIGTERM), 1 시작 실패(분류 "start_failed"), 2 화면 없음("no_display"), 3 화면 기록 권한 없음("no_permission"),
//   4 스트림 오류로 중단("stream_error")
// 표준 입력이 닫히면(부모가 종료하거나 부모가 닫으면) 스스로 끝난다. 이름으로 프로세스를 종료하지 않는다(부모가 PID 로 끝낸다).
// 빌드: swiftc -O sck_audio.swift -o <출력 경로>
import Foundation
import ScreenCaptureKit
import CoreMedia
import AVFoundation

setvbuf(stdout, nil, _IOFBF, 1 << 16)

func fail(_ code: Int32, _ kind: String, _ detail: String) -> Never {
    let d = detail.replacingOccurrences(of: "\"", with: "'").replacingOccurrences(of: "\n", with: " ")
    FileHandle.standardError.write(("{\"error\":\"\(kind)\",\"detail\":\"\(d)\"}\n").data(using: .utf8)!)
    exit(code)
}

final class Out: NSObject, SCStreamOutput, SCStreamDelegate {
    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sb.isValid, let fd = CMSampleBufferGetFormatDescription(sb),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fd)?.pointee else { return }
        var size = 0
        CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sb, bufferListSizeNeededOut: &size, bufferListOut: nil, bufferListSize: 0,
            blockBufferAllocator: nil, blockBufferMemoryAllocator: nil, flags: 0, blockBufferOut: nil)
        let raw = UnsafeMutableRawPointer.allocate(byteCount: size, alignment: 16)
        defer { raw.deallocate() }
        let abl = raw.bindMemory(to: AudioBufferList.self, capacity: 1)
        var block: CMBlockBuffer?
        let st = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sb, bufferListSizeNeededOut: nil, bufferListOut: abl, bufferListSize: size,
            blockBufferAllocator: nil, blockBufferMemoryAllocator: nil,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment, blockBufferOut: &block)
        guard st == noErr else { return }
        let bufs = UnsafeMutableAudioBufferListPointer(abl)
        let ch = Int(asbd.mChannelsPerFrame)
        let planar = (asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0
        if planar {
            guard bufs.count >= 1, bufs.count >= ch else { return }
            let n = Int(bufs[0].mDataByteSize) / MemoryLayout<Float>.size
            var out = [Float](repeating: 0, count: n * 2)
            for c in 0..<2 {
                let src = c < bufs.count ? bufs[c].mData?.assumingMemoryBound(to: Float.self) : bufs[0].mData?.assumingMemoryBound(to: Float.self)
                guard let p = src else { return }
                for i in 0..<n { out[i * 2 + c] = p[i] }
            }
            out.withUnsafeBytes { _ = fwrite($0.baseAddress, 1, $0.count, stdout) }
        } else if let b = bufs.first, let p = b.mData?.assumingMemoryBound(to: Float.self) {
            let n = Int(b.mDataByteSize) / MemoryLayout<Float>.size
            if ch == 2 {
                _ = fwrite(p, MemoryLayout<Float>.size, n, stdout)
            } else {                                         // 모노 → 2채널
                var out = [Float](repeating: 0, count: n * 2)
                for i in 0..<n { out[i * 2] = p[i]; out[i * 2 + 1] = p[i] }
                out.withUnsafeBytes { _ = fwrite($0.baseAddress, 1, $0.count, stdout) }
            }
        }
        fflush(stdout)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fail(4, "stream_error", "\(error)")
    }
}

let out = Out()
var keepAlive: SCStream? = nil                              // 스트림을 해제하지 않는다(해제되면 첫 버퍼 뒤 수집이 멈춘다)
signal(SIGTERM) { _ in exit(0) }
signal(SIGPIPE) { _ in exit(0) }                             // 부모가 읽기를 끝냄

DispatchQueue.global().async {                               // 표준 입력의 닫힘 감시
    while FileHandle.standardInput.availableData.count > 0 {}
    exit(0)
}

Task {
    let content: SCShareableContent
    do {
        content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
    } catch {
        let s = "\(error)"
        fail(3, "no_permission", s)
    }
    guard let display = content.displays.first else { fail(2, "no_display", "") }
    let cfg = SCStreamConfiguration()
    cfg.capturesAudio = true
    cfg.excludesCurrentProcessAudio = true
    cfg.sampleRate = 48000
    cfg.channelCount = 2
    cfg.width = 2; cfg.height = 2                            // 화면은 쓰지 않는다
    cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
    do {
        let stream = SCStream(filter: SCContentFilter(display: display, excludingWindows: []), configuration: cfg, delegate: out)
        keepAlive = stream
        try stream.addStreamOutput(out, type: .audio, sampleHandlerQueue: DispatchQueue(label: "k18.audio"))
        try await stream.startCapture()
    } catch {
        fail(1, "start_failed", "\(error)")
    }
}
dispatchMain()
