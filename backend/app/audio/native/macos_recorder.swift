import AVFoundation
import CoreMedia
import CoreGraphics
import Foundation
import ScreenCaptureKit

let sampleRate = 48_000.0
let masterRecordingFilename = "recording.wav"
/// 画面スリープや外部ディスプレイの切断などでキャプチャが中断されたときの終了コード。
let streamStoppedExitCode: Int32 = 3

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
            writeChunk(index)
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
        guard latestSystemFrame >= 0, latestMicrophoneFrame >= 0 else {
            return
        }

        let completeUntil = min(latestSystemFrame, latestMicrophoneFrame) / framesPerChunk - 1
        for index in chunks.keys.filter({ $0 <= completeUntil }).sorted() {
            writeChunk(index)
            chunks[index] = nil
        }
    }

    private func writeChunk(_ index: Int) {
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
        reportProgress(secondsRecorded: (index + 1) * chunkSeconds)
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
            fputs("録音全体ファイルの書き出しに失敗しました: \(error.localizedDescription)\n", stderr)
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
                fputs("入力音声バッファのフレーム数が容量を超えたため、このサンプルをスキップします。\\n", stderr)
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
    private var stream: SCStream?

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

    func stop() async {
        do {
            try await stream?.stopCapture()
        } catch {
            fputs("録音停止時にエラーが発生しました: \(error.localizedDescription)\n", stderr)
        }
        mixer.finish()
        print("録音を停止しました。")
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of outputType: SCStreamOutputType) {
        guard sampleBuffer.isValid else {
            return
        }
        mixer.append(sampleBuffer, source: outputType)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        // ストリームが死んだまま無音を録り続けないよう、ここで録音を終了する。
        // 画面スリープ・画面ロック・外部ディスプレイの抜き差しで発生する。
        fputs("録音が中断されました: \(error.localizedDescription)\n", stderr)
        mixer.finish()
        exit(streamStoppedExitCode)
    }
}

func run() async throws {
    guard #available(macOS 15.0, *) else {
        throw RecorderError.unavailableMacOS
    }

    let arguments = try RecorderArguments(arguments: Array(CommandLine.arguments.dropFirst()))
    try FileManager.default.createDirectory(at: arguments.outputDirectory, withIntermediateDirectories: true)
    let recorder = Recorder(arguments: arguments)

    signal(SIGINT, SIG_IGN)
    signal(SIGTERM, SIG_IGN)
    let stopSignals = [SIGINT, SIGTERM].map { signalNumber -> DispatchSourceSignal in
        let source = DispatchSource.makeSignalSource(signal: signalNumber, queue: .main)
        source.setEventHandler {
            Task {
                await recorder.stop()
                exit(0)
            }
        }
        source.resume()
        return source
    }

    try await recorder.start()
    _ = stopSignals
    await withUnsafeContinuation { (continuation: UnsafeContinuation<Void, Never>) in
        _ = continuation
    }
}

Task {
    do {
        try await run()
    } catch {
        fputs("録音を開始できませんでした: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

dispatchMain()
