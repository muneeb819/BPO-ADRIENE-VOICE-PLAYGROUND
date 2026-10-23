/* Convert browser microphone frames to mono signed PCM16 at 16 kHz. */
class PCM16Processor extends AudioWorkletProcessor {
  process(inputs, outputs) {
    const input = inputs[0]?.[0];
    const output = outputs[0]?.[0];
    if (output) output.fill(0); // Never play microphone audio back to the operator.
    if (!input || !input.length) return true;

    const ratio = sampleRate / 16000;
    const length = Math.max(1, Math.floor(input.length / ratio));
    const pcm = new ArrayBuffer(length * 2);
    const view = new DataView(pcm);
    for (let index = 0; index < length; index += 1) {
      const start = Math.floor(index * ratio);
      const end = Math.min(input.length, Math.max(start + 1, Math.floor((index + 1) * ratio)));
      let sum = 0;
      for (let frame = start; frame < end; frame += 1) sum += input[frame] || 0;
      const sample = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
      view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    }
    this.port.postMessage(pcm, [pcm]);
    return true;
  }
}

registerProcessor('pcm16-processor', PCM16Processor);
