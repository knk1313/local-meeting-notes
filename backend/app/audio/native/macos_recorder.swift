import AVFoundation
import CoreMedia
import CoreGraphics
import Foundation
import ScreenCaptureKit

let sampleRate = 48_000.0
let masterRecordingFilename = "recording.wav"
/// 画面スリープや外部ディスプレイの切断などでキャプチャが中断されたときの終了コード。
let streamStoppedExitCode: Int32 = 3

/// 片方の音声がこの秒数届かなければ、無音として扱い書き出しを進める。
let staleSourceSeconds = 30.0

enum RecorderError: LocalizedError {
    case invalidArguments(String)
    case unavailableMacOS
    case noDisplay
    case microphonePermissionDenied
    case screenRecordingPermissionDenied

    var errorDescription: String? {
        switch self {
        case .invalidArguments(let message):
            return message
        case .unavailableMacOS:
            return "この録音機能にはmacOS 15以降が必要です。"
        case .noDisplay:
            return "録音対象のディスプレイを取得できません。"
        case .microphonePermissionDenied:
            return "マイクへのアクセスが許可されていません。システム設定 > プライバシーとセキュリティ > マイクで、使用中のターミナルを許可してから再実行してください。"
        case .screenRecordingPermissionDenied:
            return "画面収録へのアクセスが許可されていません。システム設定 > プライバシーとセキュリティ > 画面収録とシステムオーディオ録音で、使用中のターミナルを許可してから再実行してください。"
        }
    }
}

struct RecorderArguments {
    let outputDirectory: URL
    let chunkSeconds: Int

    init(arguments: [String]) throws {
        var outputDirectory: URL?
        var chunkSeconds: Int?
        var index = 0

        while index < arguments.count {
            let argument = arguments[index]
            guard index + 1 < arguments.count else {
                throw RecorderError.invalidArguments("引数の値がありません: \(argument)")
            }

            switch argument {
            case "--output-dir":
                outputDirectory = URL(fileURLWithPath: arguments[index + 1])
            case "--chunk-seconds":
                chunkSeconds = Int(arguments[index + 1])
            default:
                throw RecorderError.invalidArguments("未対応の引数です: \(argument)")
            }
            index += 2
        }

        guard let outputDirectory, let chunkSeconds else {
            throw RecorderError.invalidArguments("--output-dir と --chunk-seconds を指定してください。")
        }
        self.outputDirectory = outputDirectory
        self.chunkSeconds = chunkSeconds
    }
}

final class ChunkMixer {
    private let lock = NSLock()
    private let outputDirectory: URL
    private let chunkSeconds: Int
    private let framesPerChunk: Int
    private var masterAudioFile: AVAudioFile?
    private var sessionStartTime: Double?
    private var chunks: [Int: Chunk] = [:]
    private var latestSystemFrame = -1
    private var latestMicrophoneFrame = -1
    private var warnedStaleSystem = false
    private var warnedStaleMicrophone = false

    private struct Chunk {
        var system: [Float]
        var microphone: [Float]
    }

    init(outputDirectory: URL, chunkSeconds: Int) {
        self.outputDirectory = outputDirectory
        self.chunkSeconds = chunkSeconds
        self.framesPerChunk = Int(sampleRate) * chunkSeconds
    }

    func append(_ sampleBuffer: CMSampleBuffer, source: SCStreamOutputType) {
        guard let pcmBuffer = convertToMonoBuffer(sampleBuffer) else {
            return
        }

        let presentationTime = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sampleBuffer))
        guard presentationTime.isFinite else {
            return
        }

        lock.lock()
        defer { lock.unlock() }

        if sessionStartTime == nil {
            sessionStartTime = presentationTime
        }
        guard let sessionStartTime else {
            return
        }

        let firstFrame = max(0, Int((presentationTime - sessionStartTime) * sampleRate))
        append(pcmBuffer, firstFrame: firstFrame, source: source)
        flushCompletedChunks()
    }

    func finish() {
        lock.lock()
        defer { lock.unlock() }

        for index in chunks.keys.sorted() {
            writeChunk(index, reportingProgress: false)
        }
        chunks.removeAll()

        // AVAudioFileはここで解放しないとWAVヘッダのサイズが0のままになる。
        masterAudioFile = nil
    }

    private func append(_ buffer: AVAudioPCMBuffer, firstFrame: Int, source: SCStreamOutputType) {
        guard let samples = buffer.floatChannelData?.pointee else {
            return
        }

        let frameCount = Int(buffer.frameLength)
        for offset in 0..<frameCount {
            let absoluteFrame = firstFrame + offset
            let chunkIndex = absoluteFrame / framesPerChunk
            let frameIndex = absoluteFrame % framesPerChunk
            if chunks[chunkIndex] == nil {
                chunks[chunkIndex] = Chunk(
                    system: Array(repeating: 0, count: framesPerChunk),
                    microphone: Array(repeating: 0, count: framesPerChunk)
                )
            }

            switch source {
            case .audio:
                chunks[chunkIndex]?.system[frameIndex] += samples[offset]
                latestSystemFrame = max(latestSystemFrame, absoluteFrame)
            case .microphone:
                chunks[chunkIndex]?.microphone[frameIndex] += samples[offset]
                latestMicrophoneFrame = max(latestMicrophoneFrame, absoluteFrame)
            default:
                break
            }
        }
    }

    private func flushCompletedChunks() {
        let leading = max(latestSystemFrame, latestMicrophoneFrame)
        guard leading >= 0 else {
            return
        }

        // 片方の音声が途切れても書き出しを止めない。止めるとメモリに溜め込み続け、
        // 異常終了したときに録音全体を失うため。
        let staleFrames = Int(staleSourceSeconds * sampleRate)
        let system = usableFrame(latestSystemFrame, leading: leading, staleFrames: staleFrames)
        let microphone = usableFrame(latestMicrophoneFrame, leading: leading, staleFrames: staleFrames)
        guard system >= 0, microphone >= 0 else {
            return
        }
        if system != latestSystemFrame {
            warnStaleSource(&warnedStaleSystem, missing: "システム音声", remaining: "マイク音声")
        }
        if microphone != latestMicrophoneFrame {
            warnStaleSource(&warnedStaleMicrophone, missing: "マイク音声", remaining: "システム音声")
        }

        let completeUntil = min(system, microphone) / framesPerChunk - 1
        for index in chunks.keys.filter({ $0 <= completeUntil }).sorted() {
            writeChunk(index, reportingProgress: true)
            chunks[index] = nil
        }
    }

    /// 書き出しの判断に使えるフレーム位置を返す。届いていないソースは無音として扱う。
    private func usableFrame(_ frame: Int, leading: Int, staleFrames: Int) -> Int {
        if frame < 0 {
            // 一度も届いていないソースは、しばらく待ってから無音とみなす。
            return leading >= staleFrames ? leading : -1
        }
        return leading - frame <= staleFrames ? frame : leading
    }

    private func warnStaleSource(_ warned: inout Bool, missing: String, remaining: String) {
        guard !warned else {
            return
        }
        warned = true
        fputs(
            "警告: \(missing)が\(Int(staleSourceSeconds))秒以上届いていません。"
                + "\(remaining)のみで録音を続けます。\n",
            stderr
        )
    }

    private func writeChunk(_ index: Int, reportingProgress: Bool) {
        guard let chunk = chunks[index] else {
            return
        }

        let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: 1,
            interleaved: false
        )!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(framesPerChunk))!
        buffer.frameLength = AVAudioFrameCount(framesPerChunk)

        guard let destination = buffer.floatChannelData?.pointee else {
            return
        }
        for frame in 0..<framesPerChunk {
            destination[frame] = max(-1, min(1, (chunk.system[frame] + chunk.microphone[frame]) * 0.5))
        }

        writeMasterRecording(buffer, format: format)
        if reportingProgress {
            reportProgress(secondsRecorded: (index + 1) * chunkSeconds)
        }
    }

    private func reportProgress(secondsRecorded: Int) {
        let hours = secondsRecorded / 3600
        let minutes = (secondsRecorded % 3600) / 60
        let seconds = secondsRecorded % 60
        print(String(format: "録音中: %02d:%02d:%02d", hours, minutes, seconds))
    }

    private func writeMasterRecording(_ buffer: AVAudioPCMBuffer, format: AVAudioFormat) {
        do {
            if masterAudioFile == nil {
                let outputURL = outputDirectory.appendingPathComponent(masterRecordingFilename)
                masterAudioFile = try AVAudioFile(
                    forWriting: outputURL,
                    settings: format.settings,
                    commonFormat: .pcmFormatFloat32,
                    interleaved: false
                )
            }
            try masterAudioFile?.write(from: buffer)
        } catch {
            fputs(
                "録音ファイルへの書き出しに失敗しました（この区間の音声は失われます）: "
                    + "\(error.localizedDescription)\n",
                stderr
            )
        }
    }

    private func convertToMonoBuffer(_ sampleBuffer: CMSampleBuffer) -> AVAudioPCMBuffer? {
        guard let formatDescription = sampleBuffer.formatDescription,
              let streamDescription = formatDescription.audioStreamBasicDescription else {
            return nil
        }
        var sourceStreamDescription = streamDescription
        guard let sourceFormat = AVAudioFormat(streamDescription: &sourceStreamDescription) else {
            return nil
        }

        let sourceFrameCount = AVAudioFrameCount(CMSampleBufferGetNumSamples(sampleBuffer))
        guard sourceFrameCount > 0 else {
            return nil
        }

        return try? sampleBuffer.withAudioBufferList { audioBufferList, _ in
            guard let sourceBuffer = AVAudioPCMBuffer(
                pcmFormat: sourceFormat,
                bufferListNoCopy: audioBufferList.unsafePointer
            ) else {
                return nil
            }
            guard sourceFrameCount <= sourceBuffer.frameCapacity else {
                fputs("警告: 入力音声バッファの容量を超えたため、このサンプルを取りこぼしました。\n", stderr)
                return nil
            }
            sourceBuffer.frameLength = sourceFrameCount

            let targetFormat = AVAudioFormat(
                commonFormat: .pcmFormatFloat32,
                sampleRate: sampleRate,
                channels: 1,
                interleaved: false
            )!
            guard let converter = AVAudioConverter(from: sourceFormat, to: targetFormat) else {
                return nil
            }
            let capacity = AVAudioFrameCount(
                Double(sourceFrameCount) * sampleRate / sourceFormat.sampleRate + 1
            )
            guard let targetBuffer = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else {
                return nil
            }

            var consumed = false
            var conversionError: NSError?
            let status = converter.convert(to: targetBuffer, error: &conversionError) { _, inputStatus in
                if consumed {
                    inputStatus.pointee = .noDataNow
                    return nil
                }
                consumed = true
                inputStatus.pointee = .haveData
                return sourceBuffer
            }
            guard status != .error, conversionError == nil else {
                return nil
            }
            return targetBuffer
        }
    }
}

@available(macOS 15.0, *)
final class Recorder: NSObject, SCStreamOutput, SCStreamDelegate {
    private let arguments: RecorderArguments
    private let mixer: ChunkMixer
    private let sampleQueue = DispatchQueue(label: "localMeetingNotes.audioSamples")
    private let stopLock = NSLock()
    private var stream: SCStream?
    private var isStopping = false

    init(arguments: RecorderArguments) {
        self.arguments = arguments
        self.mixer = ChunkMixer(outputDirectory: arguments.outputDirectory, chunkSeconds: arguments.chunkSeconds)
    }

    func start() async throws {
        try await ensureMicrophonePermission()
        try ensureScreenRecordingPermission()

        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else {
            throw RecorderError.noDisplay
        }

        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        let configuration = SCStreamConfiguration()
        configuration.capturesAudio = true
        configuration.sampleRate = Int(sampleRate)
        configuration.channelCount = 1
        configuration.captureMicrophone = true

        let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: sampleQueue)
        try stream.addStreamOutput(self, type: .microphone, sampleHandlerQueue: sampleQueue)
        self.stream = stream
        try await stream.startCapture()
        print("録音を開始しました。Ctrl+Cで停止します。")
    }

    private func ensureMicrophonePermission() async throws {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return
        case .notDetermined:
            guard await AVCaptureDevice.requestAccess(for: .audio) else {
                throw RecorderError.microphonePermissionDenied
            }
        case .denied, .restricted:
            throw RecorderError.microphonePermissionDenied
        @unknown default:
            throw RecorderError.microphonePermissionDenied
        }
    }

    private func ensureScreenRecordingPermission() throws {
        guard CGPreflightScreenCaptureAccess() else {
            CGRequestScreenCaptureAccess()
            throw RecorderError.screenRecordingPermissionDenied
        }
    }

    /// 停止処理を一度だけ実行させる。まだ停止していなければ true を返す。
    ///
    /// ターミナルのCtrl+Cはプロセスグループ全体へ届くため、アプリ側からの停止要求と
    /// 重なって停止処理が二重に走る。二度目は「停止済みのストリームを止めた」という
    /// 無害な失敗になるので、ここで弾く。
    private func beginStop() -> Bool {
        stopLock.lock()
        defer { stopLock.unlock() }
        if isStopping {
            return false
        }
        isStopping = true
        return true
    }

    /// 停止処理を実行した場合だけ true を返す。既に停止処理中なら false。
    @discardableResult
    func stop() async -> Bool {
        guard beginStop() else {
            return false
        }
        do {
            try await stream?.stopCapture()
        } catch {
            // 停止できなくても、ここまでの音声はファイルへ書き出し済み。
            fputs(
                "警告: 録音の停止処理に失敗しました（録音データは保存済みです）: "
                    + "\(error.localizedDescription)\n",
                stderr
            )
        }
        mixer.finish()
        print("録音を停止しました。")
        return true
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of outputType: SCStreamOutputType) {
        guard sampleBuffer.isValid else {
            return
        }
        mixer.append(sampleBuffer, source: outputType)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        // 停止操作の後始末で呼ばれた場合は、通常の停止として扱う。
        guard beginStop() else {
            return
        }
        // ストリームが死んだまま無音を録り続けないよう、ここで録音を終了する。
        fputs(
            "録音が中断されました: \(error.localizedDescription)。"
                + "画面スリープ・画面ロック・ディスプレイの抜き差しで起こります。\n",
            stderr
        )
        mixer.finish()
        exit(streamStoppedExitCode)
    }
}

/// 停止シグナルの対象。準備が整う前にシグナルが届くため、あとから差し込む。
final class ActiveRecorder {
    private let lock = NSLock()
    private var recorder: Recorder?

    func set(_ recorder: Recorder) {
        lock.lock()
        defer { lock.unlock() }
        self.recorder = recorder
    }

    func current() -> Recorder? {
        lock.lock()
        defer { lock.unlock() }
        return recorder
    }
}

let activeRecorder = ActiveRecorder()

func run() async throws {
    guard #available(macOS 15.0, *) else {
        throw RecorderError.unavailableMacOS
    }

    let arguments = try RecorderArguments(arguments: Array(CommandLine.arguments.dropFirst()))
    try FileManager.default.createDirectory(at: arguments.outputDirectory, withIntermediateDirectories: true)
    let recorder = Recorder(arguments: arguments)
    activeRecorder.set(recorder)

    try await recorder.start()
    await withUnsafeContinuation { (continuation: UnsafeContinuation<Void, Never>) in
        _ = continuation
    }
}

// シグナルの扱いは、起動直後に同期で決める。準備をTask内で行うと、
// それより前に届いた停止シグナルが既定動作でプロセスを終わらせてしまう。
signal(SIGINT, SIG_IGN)
signal(SIGTERM, SIG_IGN)
let stopSignals = [SIGINT, SIGTERM].map { signalNumber -> DispatchSourceSignal in
    let source = DispatchSource.makeSignalSource(signal: signalNumber, queue: .main)
    source.setEventHandler {
        Task {
            guard let recorder = activeRecorder.current() else {
                // まだ録音が始まっていない。書き出すものが無いので、そのまま終わる。
                exit(0)
            }
            // 停止を実行した側だけが終了する。重複した停止要求で、
            // 書き出しの途中にプロセスを終わらせないため。
            if await recorder.stop() {
                exit(0)
            }
        }
    }
    source.resume()
    return source
}

Task {
    do {
        try await run()
    } catch {
        fputs("録音を開始できませんでした: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

_ = stopSignals
dispatchMain()
