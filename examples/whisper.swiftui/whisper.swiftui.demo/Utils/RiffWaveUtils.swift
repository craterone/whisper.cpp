import Foundation
import AVFoundation

// MARK: - 音频转换错误

enum AudioConversionError: LocalizedError {
    case failedToCreateAsset
    case failedToCreateReader(Error)
    case noAudioTrack
    case failedToReadSamples
    case readerFailed(String)

    var errorDescription: String? {
        switch self {
        case .failedToCreateAsset:
            return "Failed to create AVAsset from URL"
        case .failedToCreateReader(let error):
            return "Failed to create AVAssetReader: \(error.localizedDescription)"
        case .noAudioTrack:
            return "No audio track found in the file"
        case .failedToReadSamples:
            return "Failed to read audio sample buffer"
        case .readerFailed(let status):
            return "AVAssetReader failed with status: \(status)"
        }
    }
}

// MARK: - WAV 文件解码（原有逻辑）

func decodeWaveFile(_ url: URL) throws -> [Float] {
    let data = try Data(contentsOf: url)
    let floats = stride(from: 44, to: data.count, by: 2).map {
        return data[$0..<$0 + 2].withUnsafeBytes {
            let short = Int16(littleEndian: $0.load(as: Int16.self))
            return max(-1.0, min(Float(short) / 32767.0, 1.0))
        }
    }
    return floats
}

// MARK: - 通用音频提取与转换（支持 mp4、m4a、wav 等任意 AVFoundation 支持的格式）

/// 从任意音频/视频文件中提取音频，并转换为 whisper 所需的格式：
/// - 采样率: 16000 Hz
/// - 声道数: 1 (mono)
/// - 格式: PCM Float32
///
/// 返回归一化到 [-1.0, 1.0] 的 Float 数组
func convertAudioFileToWhisperSamples(_ url: URL) async throws -> [Float] {
    let asset = AVURLAsset(url: url)

    // 获取音频轨道
    let audioTracks = try await asset.loadTracks(withMediaType: .audio)
    guard let audioTrack = audioTracks.first else {
        throw AudioConversionError.noAudioTrack
    }

    // 配置输出格式：16kHz, mono, PCM Float32
    let outputSettings: [String: Any] = [
        AVFormatIDKey: kAudioFormatLinearPCM,
        AVSampleRateKey: 16000.0,
        AVNumberOfChannelsKey: 1,
        AVLinearPCMBitDepthKey: 16,
        AVLinearPCMIsFloatKey: false,
        AVLinearPCMIsBigEndianKey: false,
        AVLinearPCMIsNonInterleaved: false
    ]

    let reader: AVAssetReader
    do {
        reader = try AVAssetReader(asset: asset)
    } catch {
        throw AudioConversionError.failedToCreateReader(error)
    }

    let trackOutput = AVAssetReaderTrackOutput(track: audioTrack, outputSettings: outputSettings)
    trackOutput.alwaysCopiesSampleData = false
    reader.add(trackOutput)
    reader.startReading()

    var samples = [Float]()

    while reader.status == .reading {
        guard let sampleBuffer = trackOutput.copyNextSampleBuffer(),
              let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else {
            continue
        }

        let length = CMBlockBufferGetDataLength(blockBuffer)
        var data = Data(count: length)
        data.withUnsafeMutableBytes { rawBuffer in
            if let baseAddress = rawBuffer.baseAddress {
                CMBlockBufferCopyDataBytes(blockBuffer, atOffset: 0, dataLength: length, destination: baseAddress)
            }
        }

        // 将 Int16 PCM 转换为 Float [-1.0, 1.0]
        let int16Count = length / MemoryLayout<Int16>.size
        data.withUnsafeBytes { rawBuffer in
            let int16Buffer = rawBuffer.bindMemory(to: Int16.self)
            for i in 0..<int16Count {
                let sample = Float(int16Buffer[i]) / 32767.0
                samples.append(max(-1.0, min(sample, 1.0)))
            }
        }
    }

    guard reader.status == .completed else {
        throw AudioConversionError.readerFailed(reader.status.rawValue.description)
    }

    return samples
}
