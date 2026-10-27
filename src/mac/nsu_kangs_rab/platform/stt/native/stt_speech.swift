// 단계 10 음성 인식 보조 프로세스 (SpeechAnalyzer + SpeechTranscriber, macOS 26). 기술 계획 2-8절, 결정 0162 · 0166 ~ 0168.
//
// 사용: stt_speech --locale <로캘> [--start-n <정수>]   세션용. stdin 으로 프레임을 받고 stdout 으로 JSON 줄을 낸다.
//       stt_speech --list-locales                       지원 로캘의 `locales` 줄 하나를 내고 종료한다(모델 준비 없음).
// stdin 프레임: 1바이트 종류 + 4바이트 길이(little-endian) + 본문.
//   'A' float64 t_mono(블록 첫 표본의 단조 시각) + float32 표본(16 kHz 단일 채널)   'C' 끊기   'Q' 끝(stdin 닫힘과 같다)
// stdout 줄(type): locales{list} · asset{state,fraction?,installed?} · ready · partial{text,start_mono,end_mono}
//   · final{n,text,start_mono,end_mono} · error{kind,detail,full?}
// 종료 코드: 0 정상, 1 unsupported_locale, 2 asset_failed, 3 analyzer_error, 4 os_too_old. 치명 오류는 error 줄 뒤에 종료한다.
// error.kind == segment_failed 는 결과 스트림의 오류이며 분석기를 새로 만들고 계속한다(연속 3회 실패하면 analyzer_error 로 끝낸다, 임의로 정함).
// 이름으로 프로세스를 종료하지 않는다(부모가 PID 로 끝낸다). 마이크를 열지 않는다.
// 빌드: swiftc -O -parse-as-library stt_speech.swift -o <출력 경로>
import Foundation
import Speech
import AVFoundation
import CoreMedia

let outLock = NSLock()

func emit(_ d: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: d, options: [.sortedKeys]),
          let s = String(data: data, encoding: .utf8) else { return }
    outLock.lock(); print(s); fflush(stdout); outLock.unlock()
}

func shortDetail(_ e: Error) -> String {
    let ns = e as NSError
    return "\(type(of: e)): \(ns.domain) \(ns.code)"
}

func die(_ code: Int32, _ kind: String, _ e: Error?, _ detail: String? = nil) -> Never {
    var d: [String: Any] = ["type": "error", "kind": kind,
                            "detail": detail ?? (e.map(shortDetail) ?? kind)]
    if let e = e { d["full"] = "\(e)" }
    emit(d)
    exit(code)
}

final class Flag {
    private let l = NSLock(); private var v = false
    func set() { l.lock(); v = true; l.unlock() }
    var isSet: Bool { l.lock(); defer { l.unlock() }; return v }
}
let stdinClosed = Flag()
let readyReached = Flag()  // ready 줄을 낸 뒤에는 감시를 끈다(Q 뒤의 정상 정리를 끊지 않기 위해)

enum Frame { case audio(Double, [Float]); case cut; case quit }

func readExactly(_ n: Int) -> Data? {
    var buf = Data(count: n)
    var got = 0
    while got < n {
        let r = buf.withUnsafeMutableBytes { p in fread(p.baseAddress! + got, 1, n - got, stdin) }
        if r <= 0 { return nil }
        got += r
    }
    return buf
}

@available(macOS 26.0, *)
final class Engine {
    let locale: Locale
    var nextN: Int
    private let lock = NSLock()
    private var failedFlag = false
    private var consecutiveFailures = 0
    private var transcriber: SpeechTranscriber!
    private var analyzer: SpeechAnalyzer!
    private var cont: AsyncStream<AnalyzerInput>.Continuation!
    private var resultsTask: Task<Void, Never>?
    private var fmt: AVAudioFormat!
    private var conv: AVAudioConverter!
    private let inFmt = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false)!
    // 시각 표: 이 분석기 인스턴스에서 먹인 블록 (분석기 시간의 시작 초, t_mono, 길이 초)
    private var table: [(start: Double, mono: Double, dur: Double)] = []
    private var fedSamples = 0
    private var finishing = false

    init(locale: Locale, startN: Int) { self.locale = locale; self.nextN = startN }

    private func withLock<T>(_ f: () -> T) -> T { lock.lock(); defer { lock.unlock() }; return f() }

    var needsRestart: Bool { lock.lock(); defer { lock.unlock() }; return failedFlag }

    func build() async throws {
        let t = SpeechTranscriber(locale: locale, transcriptionOptions: [],
                                  reportingOptions: [.volatileResults, .fastResults], attributeOptions: [.audioTimeRange])
        let a = SpeechAnalyzer(modules: [t])
        guard let f = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [t]),
              let c = AVAudioConverter(from: inFmt, to: f) else {
            throw NSError(domain: "stt_speech", code: 1, userInfo: [NSLocalizedDescriptionKey: "no audio format"])
        }
        let (seq, cont) = AsyncStream.makeStream(of: AnalyzerInput.self)
        transcriber = t; analyzer = a; fmt = f; conv = c; self.cont = cont
        table = []; fedSamples = 0
        withLock { failedFlag = false }
        resultsTask = Task { [weak self] in
            do {
                for try await r in t.results {
                    guard let self = self else { return }
                    self.deliver(r)
                }
            } catch {
                guard let self = self else { return }
                self.resultsFailed(error)
            }
        }
        try await a.start(inputSequence: seq)
    }

    private func mono(_ audioSec: Double) -> Double {
        lock.lock(); let tb = table; lock.unlock()
        if tb.isEmpty { return audioSec }
        for b in tb.reversed() where audioSec >= b.start { return b.mono + min(audioSec - b.start, b.dur) }
        return tb[0].mono
    }

    private func deliver(_ r: SpeechTranscriber.Result) {
        let text = String(r.text.characters).replacingOccurrences(of: "\n", with: " ")
        let s = mono(r.range.start.seconds), e = mono(r.range.end.seconds)
        lock.lock(); consecutiveFailures = 0; lock.unlock()
        if r.isFinal {
            if text.trimmingCharacters(in: .whitespaces).isEmpty { return }
            lock.lock(); let n = nextN; nextN += 1; lock.unlock()
            emit(["type": "final", "n": n, "text": text, "start_mono": s, "end_mono": e])
        } else {
            emit(["type": "partial", "text": text, "start_mono": s, "end_mono": e])
        }
    }

    private func resultsFailed(_ error: Error) {
        lock.lock()
        let fin = finishing
        consecutiveFailures += 1
        let n = consecutiveFailures
        failedFlag = true
        lock.unlock()
        if fin { return }
        if n >= 3 { die(3, "analyzer_error", error) }
        emit(["type": "error", "kind": "segment_failed", "detail": shortDetail(error), "full": "\(error)"])
    }

    func feed(mono t: Double, samples: [Float]) throws {
        guard !samples.isEmpty else { return }
        let n = AVAudioFrameCount(samples.count)
        let buf = AVAudioPCMBuffer(pcmFormat: inFmt, frameCapacity: n)!
        buf.frameLength = n
        samples.withUnsafeBufferPointer { buf.floatChannelData![0].update(from: $0.baseAddress!, count: samples.count) }
        let out = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: AVAudioFrameCount(Double(n) * fmt.sampleRate / 16000.0) + 64)!
        var given = false
        var err: NSError?
        conv.convert(to: out, error: &err) { _, st in
            if given { st.pointee = .noDataNow; return nil }
            given = true; st.pointee = .haveData; return buf
        }
        if let err = err { throw err }
        lock.lock()
        table.append((start: Double(fedSamples) / 16000.0, mono: t, dur: Double(samples.count) / 16000.0))
        fedSamples += samples.count
        lock.unlock()
        cont.yield(AnalyzerInput(buffer: out))
    }

    /// 'C': 진행 중 구간을 확정시킨다. `finalize(through:)` 는 그 시각 뒤의 음성이 한 조각이라도 들어와야 끝난다(S10-1 측정:
    /// 뒤따르는 음성 없이 기다리면 입력이 끝날 때까지 돌아오지 않는다). 그래서 끊기를 별도 작업으로 시작하고 100 ms 의 무음을 먹인다
    /// (패딩 길이 100 ms 는 임의로 정함. 30 ms 에서도 끝났다). 끊기를 기다리느라 프레임 읽기를 막지 않는다.
    func cut() {
        let fed = withLock { Double(fedSamples) / 16000.0 }
        if fed <= 0 { return }
        let an = analyzer!
        Task { [weak self] in
            do { try await an.finalize(through: CMTime(seconds: fed, preferredTimescale: 16000)) }
            catch { self?.cutFailed(error) }
        }
        let lastMono = withLock { table.last.map { $0.mono + $0.dur } ?? 0 }
        try? feed(mono: lastMono, samples: [Float](repeating: 0, count: 1600))
    }

    private func cutFailed(_ error: Error) {
        if withLock({ finishing }) || error is CancellationError { return }
        resultsFailed(error)
    }

    /// 입력이 끝났을 때의 정리. 음성을 한 조각도 먹이지 않았으면 `finalizeAndFinishThroughEndOfInput()` 이 돌아오지 않으므로
    /// (D-183 재현: 먹임 없이 stdin 을 닫으면 25초 넘게 남음) 확정할 것이 없다고 보고 건너뛴다.
    /// 먹였더라도 5초 안에 끝나지 않으면 포기하고 반환한다(5초는 임의로 정함. 먹인 뒤의 정상 종료는 0.13초).
    func finish() async {
        let fed = withLock { finishing = true; return fedSamples }
        cont.finish()
        if fed <= 0 { return }
        let an = analyzer!
        let done = Task { try? await an.finalizeAndFinishThroughEndOfInput(); await resultsTask?.value }
        let guardT = Task { try? await Task.sleep(nanoseconds: 5_000_000_000); done.cancel() }
        await withTaskGroup(of: Void.self) { g in
            g.addTask { await done.value }
            g.addTask { try? await Task.sleep(nanoseconds: 5_000_000_000) }
            _ = await g.next()
            g.cancelAll()
        }
        guardT.cancel()
    }
}

@available(macOS 26.0, *)
func run() async {
    let args = CommandLine.arguments
    func arg(_ name: String) -> String? { if let i = args.firstIndex(of: name), i + 1 < args.count { return args[i + 1] }; return nil }
    let supported = await SpeechTranscriber.supportedLocales.map { $0.identifier }.sorted()
    emit(["type": "locales", "list": supported])
    if args.contains("--list-locales") { exit(0) }
    guard let loc = arg("--locale") else { die(1, "unsupported_locale", nil, "no --locale") }
    let startN = Int(arg("--start-n") ?? "1") ?? 1
    guard supported.contains(loc) else { die(1, "unsupported_locale", nil, loc) }
    let locale = Locale(identifier: loc)
    // 표준 입력은 자원 내려받기 · 준비 단계부터 읽는다. 그 단계에서 stdin 이 닫히면(부모 종료) 바로 끝난다(D-183).
    let (frames, fc) = AsyncStream.makeStream(of: Frame.self)
    Thread.detachNewThread {
        while true {
            guard let h = readExactly(5) else { break }
            let kind = h[0]
            let len = Int(h[1]) | Int(h[2]) << 8 | Int(h[3]) << 16 | Int(h[4]) << 24
            var body = Data()
            if len > 0 { guard let b = readExactly(len) else { break }; body = b }
            switch kind {
            case 0x41:
                guard len >= 8 else { continue }
                let t = body.withUnsafeBytes { $0.loadUnaligned(as: Double.self) }
                let cnt = (len - 8) / 4
                var s = [Float](repeating: 0, count: cnt)
                body.withUnsafeBytes { p in
                    for i in 0..<cnt { s[i] = p.loadUnaligned(fromByteOffset: 8 + i * 4, as: Float.self) }
                }
                fc.yield(.audio(t, s))
            case 0x43: fc.yield(.cut)
            case 0x51: fc.yield(.quit)
            default: break
            }
            if kind == 0x51 { break }
        }
        stdinClosed.set()
        fc.yield(.quit)
        fc.finish()
    }
    // 준비 단계 감시: stdin 이 닫혔거나 부모가 사라졌으면(부모 PID 1) 스스로 끝난다.
    Thread.detachNewThread {
        while true {
            if readyReached.isSet { break }
            if stdinClosed.isSet || getppid() == 1 { exit(0) }
            Thread.sleep(forTimeInterval: 0.25)
        }
    }
    let probe = SpeechTranscriber(locale: locale, transcriptionOptions: [], reportingOptions: [.volatileResults, .fastResults], attributeOptions: [.audioTimeRange])
    let installedBefore = await SpeechTranscriber.installedLocales.contains { $0.identifier == loc }
    emit(["type": "asset", "state": "checking", "installed": installedBefore])
    do {
        var reserved = false
        do { reserved = try await AssetInventory.reserve(locale: locale) } catch { reserved = false }
        if await AssetInventory.status(forModules: [probe]) != .installed {
            if let req = try await AssetInventory.assetInstallationRequest(supporting: [probe]) {
                emit(["type": "asset", "state": "downloading"])
                let poll = Task {
                    while !Task.isCancelled {
                        // D-182: 진행률이 0 에 머무는 원인을 가리기 위해 단위 수(completed · total)와 불확정 여부도 함께 낸다.
                        // 실제 내려받기에서 값이 오르는지는 아직 실측하지 못했다(새 언어 내려받기에 사용자의 승인이 필요).
                        let pr = req.progress
                        // de_DE 실측(8초): completed 0 · total 1 · indeterminate false 가 끝까지 변하지 않고 곧바로 installed 가 되었다.
                        // 진행률이 보고되지 않는 동안(fractionCompleted 0)에는 fraction 을 내지 않는다. 앱은 fraction 이 없으면
                        // 불확정 문구("내려받는 중")를 표시한다. 값이 오르는 환경이면 0 보다 큰 값부터 그대로 낸다.
                        var d: [String: Any] = ["type": "asset", "state": "downloading",
                                                "completed": pr.completedUnitCount, "total": pr.totalUnitCount,
                                                "indeterminate": pr.isIndeterminate]
                        if pr.fractionCompleted > 0 { d["fraction"] = pr.fractionCompleted }
                        emit(d)
                        try? await Task.sleep(nanoseconds: 500_000_000)
                    }
                }
                defer { poll.cancel() }
                try await req.downloadAndInstall()
            }
            if !reserved { _ = try? await AssetInventory.reserve(locale: locale) }
            if await AssetInventory.status(forModules: [probe]) != .installed {
                die(2, "asset_failed", nil, "not installed after download")
            }
        }
    } catch { die(2, "asset_failed", error) }
    emit(["type": "asset", "state": "installed"])

    let engine = Engine(locale: locale, startN: startN)
    do { try await engine.build() } catch { die(3, "analyzer_error", error) }
    readyReached.set()
    emit(["type": "ready"])

    for await f in frames {
        if engine.needsRestart {
            do { try await engine.build() } catch { die(3, "analyzer_error", error) }
        }
        switch f {
        case .audio(let t, let s):
            do { try engine.feed(mono: t, samples: s) } catch { die(3, "analyzer_error", error) }
        case .cut:
            engine.cut()
        case .quit:
            await engine.finish()
            _ = await AssetInventory.release(reservedLocale: locale)
            exit(0)
        }
    }
    await engine.finish()
    _ = await AssetInventory.release(reservedLocale: locale)
    exit(0)
}

@main struct Main {
    static func main() async {
        setvbuf(stdout, nil, _IOLBF, 0)
        if #available(macOS 26.0, *) { await run() }
        else { die(4, "os_too_old", nil, "macOS 26 required") }
    }
}
