# Dual Local CPU Speech Engines with Optional Cloud Translation

Transcribbler's priorities are ranked **Accuracy → Speed → Low CPU use → Privacy**. Because no single CPU-friendly model gives top-tier English accuracy while also handling Cantonese and Mandarin with automatic language switching, Transcribbler routes `auto` (multilingual) to SenseVoice-Small and `en` (English-only) to NeMo Parakeet-TDT-0.6B-v2 (with Moonshine-Base-EN as a lighter fallback). Speech recognition stays local on the CPU with no GPU required, while translation can optionally use cloud providers (Azure or Google) alongside an offline option so users can trade privacy for higher Cantonese/Mandarin translation accuracy and lower CPU load.

## Consequences

- The Desktop App keeps language selection simple (`auto` and `en` only) rather than exposing every engine option.
- Users must download the relevant local speech models once before first use.
