import sys
import time
from faster-whisper import WhisperModel

# Path to your audio file
audio_file = sys.argv[1] if len(sys.argv) > 1 else "sample.mp3"

# 1. Initialize model
# Options: "small.en" (fastest balance), "small" (multilingual), "large-v3-turbo" (highest accuracy)
model_size = "large-v3-turbo"

print(f"Loading {model_size} on CPU (int8)...")
model = WhisperModel(
    model_size,
    device="cpu",
    compute_type="int8",      # Crucial for Intel CPU speed
    cpu_threads=6             # Matches the 6 physical cores of the i7-8850H
)

# 2. Transcribe
start_time = time.time()
print(f"Transcribing '{audio_file}'...")

segments, info = model.transcribe(
    audio_file,
    beam_size=5,
    vad_filter=True           # Skips silent parts to speed up processing
)

print(f"Detected language: '{info.language}' (probability: {info.language_probability:.2f})")
print(f"Audio duration: {info.duration:.1f}s\n---")

# 3. Stream output to terminal
full_text = []
for segment in segments:
    print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
    full_text.append(segment.text)

elapsed = time.time() - start_time
print(f"---\nDone in {elapsed:.1f}s ({info.duration / elapsed:.2f}x real-time speed)")

# Save transcript
output_filename = f"{audio_file}.txt"
with open(output_filename, "w", encoding="utf-8") as f:
    f.write(" ".join(full_text))
print(f"Saved transcript to {output_filename}")
