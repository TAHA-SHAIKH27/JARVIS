// voice-processor.js
// AudioWorkletProcessor for continuous 16kHz mono audio capture
// Outputs to: wake-word detector (via port) and ring buffer (for STT)

class VoiceProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super(options);
    
    // Configuration
    this.sampleRate = 16000;
    this.channels = 1;
    this.blockSize = 512; // 32ms at 16kHz
    
    // Ring buffer for STT context (5 seconds = 80,000 samples)
    this.ringBufferSize = 5 * this.sampleRate;
    this.ringBuffer = new Float32Array(this.ringBufferSize);
    this.writePosition = 0;
    this.totalSamplesWritten = 0;
    
    // State
    this.porcupineActive = false;
    this.sttActive = false;
    this.isProcessing = true;
    
    // Volume tracking
    this.volumeSum = 0;
    this.volumeCount = 0;
    
    // Handle messages from main thread
    this.port.onmessage = (event) => {
      const { type, data } = event.data;
      
      switch (type) {
        case 'PORCUPINE_START':
          this.porcupineActive = true;
          break;
        case 'PORCUPINE_STOP':
          this.porcupineActive = false;
          break;
        case 'STT_START':
          this.sttActive = true;
          break;
        case 'STT_STOP':
          this.sttActive = false;
          break;
        case 'GET_BUFFER':
          this.sendRingBuffer();
          break;
        case 'CLEAR_BUFFER':
          this.clearRingBuffer();
          break;
        case 'PAUSE':
          this.isProcessing = false;
          break;
        case 'RESUME':
          this.isProcessing = true;
          break;
      }
    };
  }
  
  process(inputs, outputs) {
    if (!this.isProcessing) {
      return true;
    }
    
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) {
      return true;
    }
    
    const channelData = input[0]; // Float32Array[blockSize]
    
    // Write to ring buffer (circular)
    for (let i = 0; i < channelData.length; i++) {
      this.ringBuffer[this.writePosition] = channelData[i];
      this.writePosition = (this.writePosition + 1) % this.ringBufferSize;
      this.totalSamplesWritten++;
    }
    
    // Calculate volume for VAD
    let sum = 0;
    for (let i = 0; i < channelData.length; i++) {
      sum += channelData[i] * channelData[i];
    }
    this.volumeSum += sum;
    this.volumeCount += channelData.length;
    
    // Send to Porcupine wake-word detector (if active)
    if (this.porcupineActive) {
      // Transfer ownership of the buffer to avoid copying
      this.port.postMessage(
        { type: 'AUDIO', buffer: channelData },
        [channelData.buffer]
      );
    }
    
    // Send volume data periodically (every ~500ms = 16 blocks)
    if (this.totalSamplesWritten % (this.blockSize * 16) === 0) {
      const rms = Math.sqrt(this.volumeSum / this.volumeCount);
      this.port.postMessage({
        type: 'VOLUME',
        rms: rms,
        timestamp: currentTime * 1000
      });
      this.volumeSum = 0;
      this.volumeCount = 0;
    }
    
    return true;
  }
  
  sendRingBuffer() {
    // Send a copy of the ring buffer in chronological order
    const buffer = new Float32Array(this.ringBufferSize);
    if (this.totalSamplesWritten >= this.ringBufferSize) {
      // Buffer is full, copy from write position to end, then start to write position
      buffer.set(this.ringBuffer.subarray(this.writePosition));
      buffer.set(this.ringBuffer.subarray(0, this.writePosition), this.ringBufferSize - this.writePosition);
    } else {
      // Buffer not full yet, copy from start
      buffer.set(this.ringBuffer.subarray(0, this.totalSamplesWritten));
    }
    
    this.port.postMessage(
      { 
        type: 'RING_BUFFER', 
        buffer: buffer,
        validSamples: Math.min(this.totalSamplesWritten, this.ringBufferSize),
        writePosition: this.writePosition,
        timestamp: currentTime * 1000
      },
      [buffer.buffer]
    );
  }
  
  clearRingBuffer() {
    this.ringBuffer.fill(0);
    this.writePosition = 0;
    this.totalSamplesWritten = 0;
  }
}

registerProcessor('voice-processor', VoiceProcessor);