import sys
import os
import wave
import struct
import math
from pathlib import Path

# Setup Path
sys.path.insert(0, str(Path.cwd() / "score_reading"))

# Generate Dummy Wav
def create_dummy_wav(filename, duration=3.0):
    with wave.open(filename, 'w') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        n_frames = int(duration * 16000)
        # Silence
        data = struct.pack('<' + ('h'*n_frames), *[0]*n_frames)
        f.writeframes(data)
    return Path(filename)

def test_engine():
    wav_path = create_dummy_wav("test_silence.wav")
    print(f"Generated test file: {wav_path}")
    
    try:
        from src.pipeline.engines.wav2vec2 import Wav2Vec2Engine
        engine = Wav2Vec2Engine()
        
        script = "THIS IS A LONG SENTENCE THAT SHOULD FAIL VITERBI BECAUSE AUDIO IS SILENCE"
        print(f"Running Alignment on: '{script}'")
        
        alignment, raw = engine.run(wav_path, script)
        
        words = alignment.words
        print(f"detected words count: {len(words)}")
        print(f"input words count: {len(script.split())}")
        
        if len(words) == len(script.split()):
            print("SUCCESS: Linear Fallback triggered! All words preserved.")
            for w in words:
                print(f" - {w.word}: {w.start:.2f}-{w.end:.2f} (Score: {w.score})")
        else:
            print("FAILURE: Words missing. Fallback logic NOT working.")
            print(f"Words found: {[w.word for w in words]}")

    except Exception as e:
        print(f"CRASHED: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists("test_silence.wav"):
            os.remove("test_silence.wav")

if __name__ == "__main__":
    test_engine()
