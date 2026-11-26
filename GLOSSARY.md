# Transcribbler

A Windows desktop application for live multilingual speech-to-text and optional translation during meetings, calls, podcasts, and videos, built for personal use and everyday users.

## Language

### Audio & Capture

**Session**:
A single continuous listening run from starting capture to stopping capture, tied to one automatic **Transcript File**.
_Avoid_: Recording, run, meeting

**Channel**:
One of the two audio inputs listened to during a **Session**: **ME** (the user's microphone) or **OTHERS** (system speaker or headset audio).
_Avoid_: Track, stream, audio source

**Channel Toggle**:
The per-**Channel** control (`Disable` / `Enable`) that pauses or resumes listening and transcription for that **Channel**.
_Avoid_: Mute filter, view toggle

**View Filter**:
The display selector (`All Sources`, `Mic Only`, `Speaker Only`) that controls which **Channels** are visible on screen without affecting background capture or exports.
_Avoid_: Channel toggle, source mute

### Transcription & Output

**Live Preview**:
Temporary, work-in-progress text shown in the Desktop App while a speaker is still mid-sentence, replaced as more speech arrives.
_Avoid_: Draft, partial, interim

**Final Entry**:
A completed block of speech locked in after a speaker pauses or reaches a time limit, permanently recorded in the **Transcript File**.
_Avoid_: Committed line, utterance

**Transcript File**:
The automatic text file created for a **Session** as a permanent record of every **Final Entry**.
_Avoid_: Export file, log

**Clear Screen**:
Removing visible text from the app window without erasing or splitting the automatic **Transcript File** for the active **Session**.
_Avoid_: Clear Session, delete transcript

### Language & Engines

**Speech Engine**:
The local speech-to-text model used during a **Session**—multilingual (`auto`) for English, Cantonese, and Mandarin, or dedicated English (`en`) for higher conversational English accuracy.
_Avoid_: Backend, recognizer

**Romanization**:
Pronunciation text written in Latin letters with tones for Chinese speech—Pinyin for Mandarin and Jyutping for Cantonese.
_Avoid_: Transliteration, phonetics
