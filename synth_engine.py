from array import array
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random
import wave

from korean_phonology import normalize_lyrics, phonemes_for


SAMPLE_RATE = 44100
BASE_MIDI = 69


@dataclass
class Note:
    start: float = 0.0
    length: float = 1.0
    midi: int = 60
    lyric: str = "아"
    velocity: int = 100
    noise: float = 1.0


def midi_hz(midi):
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def note_name(midi):
    names = [
        "도", "도♯", "레", "레♯", "미", "파",
        "파♯", "솔", "솔♯", "라", "라♯", "시",
    ]
    return f"{names[midi % 12]}{midi // 12 - 1}"


def read_wav(path):
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if width != 2:
        raise ValueError(f"16-bit PCM WAV만 지원합니다: {path.name}")
    pcm = array("h")
    pcm.frombytes(frames)
    if channels > 1:
        mono = []
        for index in range(0, len(pcm), channels):
            frame = pcm[index:index + channels]
            mono.append(sum(frame) / max(1, len(frame)))
        data = [sample / 32768.0 for sample in mono]
    else:
        data = [sample / 32768.0 for sample in pcm]
    if rate != SAMPLE_RATE:
        data = resample_ratio(data, rate / SAMPLE_RATE)
    return data


def resample_ratio(samples, ratio):
    """ratio>1이면 피치가 올라가며 출력 샘플 수가 줄어든다."""
    if not samples or ratio <= 0:
        return []
    count = max(1, int(len(samples) / ratio))
    output = [0.0] * count
    last = len(samples) - 1
    for i in range(count):
        position = min(last, i * ratio)
        left = int(position)
        right = min(last, left + 1)
        fraction = position - left
        output[i] = samples[left] * (1.0 - fraction) + samples[right] * fraction
    return output


def fade(samples, fade_in=0.008, fade_out=0.018):
    result = list(samples)
    a = min(len(result) // 2, int(SAMPLE_RATE * fade_in))
    r = min(len(result) // 2, int(SAMPLE_RATE * fade_out))
    for i in range(a):
        result[i] *= i / max(1, a)
    for i in range(r):
        result[-1 - i] *= i / max(1, r)
    return result


def fit_duration(samples, target_count):
    """자음은 자르고, 모음은 중앙부를 반복해 목표 길이에 맞춘다."""
    if target_count <= 0:
        return []
    if not samples:
        return [0.0] * target_count
    if len(samples) >= target_count:
        return fade(samples[:target_count])

    prefix_end = max(1, int(len(samples) * 0.28))
    loop_end = max(prefix_end + 1, int(len(samples) * 0.72))
    prefix = samples[:prefix_end]
    loop = samples[prefix_end:loop_end] or samples
    suffix = samples[loop_end:]
    output = list(prefix)
    cross = min(int(SAMPLE_RATE * 0.006), len(loop) // 4)

    while len(output) + len(suffix) < target_count:
        remaining = target_count - len(output) - len(suffix)
        block = loop[:remaining]
        if output and cross and len(block) > cross:
            for i in range(cross):
                blend = (i + 1) / (cross + 1)
                output[-cross + i] = output[-cross + i] * (1 - blend) + block[i] * blend
            output.extend(block[cross:])
        else:
            output.extend(block)
        if not block:
            break
    output.extend(suffix[:max(0, target_count - len(output))])
    if len(output) < target_count:
        output.extend([0.0] * (target_count - len(output)))
    return fade(output[:target_count])


def crossfade_concat(parts, milliseconds=8):
    output = []
    cross = int(SAMPLE_RATE * milliseconds / 1000)
    for part in parts:
        if not part:
            continue
        overlap = min(cross, len(output), len(part))
        if overlap:
            for i in range(overlap):
                blend = (i + 1) / (overlap + 1)
                output[-overlap + i] = output[-overlap + i] * (1 - blend) + part[i] * blend
            output.extend(part[overlap:])
        else:
            output.extend(part)
    return output


def periodic_sustain(samples, target_count, period_samples):
    if target_count <= 0:
        return []
    if not samples:
        return [0.0] * target_count
    period_samples = max(8, int(period_samples))
    cycles = max(4, min(14, len(samples) // period_samples))
    loop_length = max(period_samples, cycles * period_samples)
    start = max(0, (len(samples) - loop_length) // 2)
    loop = list(samples[start:start + loop_length])
    if not loop:
        loop = list(samples)
    output = []
    overlap = min(period_samples, len(loop) // 4)
    while len(output) < target_count:
        block = loop[:target_count - len(output)]
        if output and overlap and len(block) > overlap:
            for i in range(overlap):
                blend = (i + 1) / (overlap + 1)
                output[-overlap + i] = output[-overlap + i] * (1 - blend) + block[i] * blend
            output.extend(block[overlap:])
        else:
            output.extend(block)
        if not block:
            break
    if len(output) < target_count:
        output.extend([0.0] * (target_count - len(output)))
    return fade(output[:target_count], 0.006, 0.015)


def interharmonic_noise(count, f0, amount, seed):
    """배음 자체는 피하고 배음 사이에만 제한적으로 위치하는 잡음 성분."""
    if amount <= 0 or count <= 0:
        return [0.0] * max(0, count)
    rng = random.Random(seed)
    t_step = 1.0 / SAMPLE_RATE
    output = [0.0] * count
    max_harmonic = min(24, int((SAMPLE_RATE * 0.45) / max(40.0, f0)))
    components = []
    for harmonic in range(1, max_harmonic + 1):
        # 0.38~0.62: 인접한 두 배음의 중간 영역. 배음 근처에는 놓지 않는다.
        position = rng.uniform(0.38, 0.62)
        frequency = (harmonic + position) * f0
        amplitude = amount * rng.uniform(0.68, 1.0) / (harmonic ** 0.72)
        phase = rng.uniform(0, math.tau)
        components.append((frequency, amplitude, phase))
    normalizer = max(1.0, sum(abs(item[1]) for item in components))
    for i in range(count):
        time = i * t_step
        value = 0.0
        for frequency, amplitude, phase in components:
            value += amplitude * math.sin(math.tau * frequency * time + phase)
        edge = min(1.0, i / 300.0, (count - i - 1) / 500.0)
        output[i] = value / normalizer * max(0.0, edge)
    return output


def mechanicalize(samples, f0, amount):
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0:
        return list(samples)
    output = [0.0] * len(samples)
    bit_depth = 13.0 - amount * 4.0
    quantization = 2.0 ** bit_depth
    for i, sample in enumerate(samples):
        time = i / SAMPLE_RATE
        edge = min(1.0, i / 260.0, (len(samples) - i - 1) / 420.0)
        modulator = 1.0 - 0.10 * amount
        modulator += 0.10 * amount * math.sin(math.tau * 31.0 * time)
        servo = 0.020 * amount * math.sin(math.tau * (f0 * 1.5) * time)
        servo += 0.009 * amount * math.sin(math.tau * (f0 * 2.5) * time + 0.7)
        value = sample * modulator + servo * max(0.0, edge)
        output[i] = round(value * quantization) / quantization
    return output


def humanize_voice(samples, amount=0.62):
    amount = max(0.0, min(1.0, float(amount)))
    if amount <= 0 or len(samples) < 3:
        return list(samples)
    output = [0.0] * len(samples)
    depth = SAMPLE_RATE * 0.00008 * amount
    last = len(samples) - 1
    for i in range(len(samples)):
        time = i / SAMPLE_RATE
        position = i + depth * math.sin(math.tau * 5.25 * time + 0.35)
        position = max(0.0, min(last, position))
        left = int(position)
        right = min(last, left + 1)
        fraction = position - left
        value = samples[left] * (1.0 - fraction) + samples[right] * fraction
        amplitude = 1.0 + 0.012 * amount * math.sin(math.tau * 4.65 * time + 1.1)
        output[i] = value * amplitude
    return output


def instrument_tone(name, midi, count, velocity):
    if name == "없음" or count <= 0:
        return [0.0] * max(0, count)
    f0 = midi_hz(midi)
    rng = random.Random(midi * 971 + count)
    phase = 0.0
    output = [0.0] * count
    for i in range(count):
        time = i / SAMPLE_RATE
        phase = (phase + f0 / SAMPLE_RATE) % 1.0
        sine = math.sin(math.tau * phase)
        if name == "사인":
            value = sine
        elif name == "톱니":
            value = 2.0 * phase - 1.0
        elif name == "사각":
            value = 1.0 if phase < 0.5 else -1.0
        elif name == "벨":
            value = (
                math.sin(math.tau * f0 * time)
                + 0.45 * math.sin(math.tau * f0 * 2.71 * time)
                + 0.22 * math.sin(math.tau * f0 * 4.08 * time)
            ) * math.exp(-3.6 * time)
        else:  # 소프트 패드
            value = 0.56 * sine + 0.27 * math.sin(math.tau * f0 * 2 * time)
            value += 0.12 * math.sin(math.tau * (f0 * 0.997 + rng.random() * 0.03) * time)
        attack = min(1.0, i / max(1, int(SAMPLE_RATE * 0.025)))
        release = min(1.0, (count - i - 1) / max(1, int(SAMPLE_RATE * 0.08)))
        output[i] = value * attack * release * (velocity / 127.0)
    return output


class Voicebank:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.cache = {}
        manifest_path = self.directory / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"CVVC 음원 목록이 없습니다: {manifest_path}")
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        variant_path = self.directory.parent / "detailed_voicebank" / "manifest.json"
        self.variants = {}
        if variant_path.exists():
            self.variants = json.loads(
                variant_path.read_text(encoding="utf-8")
            ).get("variants", {})

    def load(self, alias, voice_style="clean"):
        style_key = "soft" if voice_style in {"soft", "부드러운 여성"} else "clean"
        cache_key = (alias, style_key)
        if cache_key not in self.cache:
            variant_file = self.variants.get(style_key, {}).get(alias)
            if variant_file:
                path = self.directory.parent / variant_file
            else:
                unit = self.manifest.get("units", {}).get(alias)
                if not unit:
                    raise KeyError(f"CVVC 음원이 없습니다: {alias}")
                path = self.directory / unit["file"]
            if not path.exists():
                raise FileNotFoundError(f"음원 파일이 없습니다: {path}")
            self.cache[cache_key] = read_wav(path)
        return self.cache[cache_key]


class Renderer:
    def __init__(self, voicebank):
        self.voicebank = voicebank

    def render(self, notes, bpm=120, noise_level=0.12, instrument="없음",
               instrument_volume=0.18, phonology=True, initial_rule=True,
               machine_level=0.03, voice_style="clean"):
        if not notes:
            return [0.0] * SAMPLE_RATE
        notes = sorted(notes, key=lambda note: (note.start, note.midi))
        seconds_per_beat = 60.0 / max(20.0, float(bpm))
        total_seconds = max(note.start + note.length for note in notes) * seconds_per_beat + 0.35
        mix = [0.0] * int(total_seconds * SAMPLE_RATE)
        pronunciations = normalize_lyrics(
            [note.lyric for note in notes],
            enable_rules=phonology,
            enable_initial=initial_rule,
        )

        previous_note = None
        previous_parts = None
        for index, (note, parts) in enumerate(zip(notes, pronunciations)):
            start = int(note.start * seconds_per_beat * SAMPLE_RATE)
            total_count = max(600, int(note.length * seconds_per_beat * SAMPLE_RATE))
            ratio = 2.0 ** ((note.midi - BASE_MIDI) / 12.0)
            onset, vowel, coda = parts

            connected = (
                previous_note is not None
                and note.start <= previous_note.start + previous_note.length + 0.06
            )
            prefix = []
            if connected and previous_parts is not None:
                vc_alias = f"{previous_parts[1]}-{onset}"
                try:
                    transition = resample_ratio(
                        self.voicebank.load(vc_alias, voice_style), ratio,
                    )
                    prefix_count = min(int(SAMPLE_RATE * 0.085), int(total_count * 0.22))
                    prefix = transition[-prefix_count:]
                except (KeyError, FileNotFoundError):
                    pass

            cv_alias = f"{onset}{vowel}"
            cv = resample_ratio(self.voicebank.load(cv_alias, voice_style), ratio)
            if not prefix:
                prefix_count = min(int(SAMPLE_RATE * 0.105), int(total_count * 0.25))
                prefix = cv[:prefix_count]
            vowel_start = int(len(cv) * 0.55)
            vowel_end = max(vowel_start + 1, int(len(cv) * 0.90))
            vowel_source = cv[vowel_start:vowel_end]

            coda_audio = []
            if coda:
                coda_symbol = phonemes_for(parts)[-1]
                coda_alias = f"{vowel}{coda_symbol}"
                try:
                    full_coda = resample_ratio(
                        self.voicebank.load(coda_alias, voice_style), ratio,
                    )
                    coda_count = min(int(SAMPLE_RATE * 0.105), int(total_count * 0.23))
                    coda_audio = full_coda[-coda_count:]
                except (KeyError, FileNotFoundError):
                    pass

            overlap_budget = int(SAMPLE_RATE * 0.012) * (1 + (1 if coda_audio else 0))
            sustain_count = max(
                200,
                total_count - len(prefix) - len(coda_audio) + overlap_budget,
            )
            period = SAMPLE_RATE / midi_hz(note.midi)
            sustain = periodic_sustain(vowel_source, sustain_count, period)
            voice = crossfade_concat([prefix, sustain, coda_audio], 12)
            if len(voice) < total_count:
                voice.extend([0.0] * (total_count - len(voice)))
            voice = fade(voice[:total_count], 0.004, 0.018)
            voice = humanize_voice(voice)
            voice = mechanicalize(voice, midi_hz(note.midi), machine_level)

            # 음높이·세기·노트별 값에 따라 제한된 범위에서 잡음량 결정.
            pitch_factor = min(1.22, max(0.78, midi_hz(note.midi) / midi_hz(64)))
            velocity_factor = 0.72 + 0.28 * note.velocity / 127.0
            bounded_amount = min(
                0.12,
                max(0.0, noise_level * note.noise * pitch_factor * velocity_factor * 0.55),
            )
            noise = interharmonic_noise(total_count, midi_hz(note.midi), bounded_amount, index * 7919 + note.midi)
            gain = 0.72 * note.velocity / 127.0
            backing = instrument_tone(instrument, note.midi, total_count, note.velocity)

            for i in range(total_count):
                position = start + i
                if position >= len(mix):
                    break
                mix[position] += (voice[i] + noise[i]) * gain
                mix[position] += backing[i] * instrument_volume

            previous_note = note
            previous_parts = parts

        peak = max(0.001, max(abs(sample) for sample in mix))
        if peak > 0.94:
            scale = 0.94 / peak
            mix = [sample * scale for sample in mix]
        return mix


def write_wav(path, samples):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = array("h", (int(max(-1.0, min(1.0, sample)) * 32767) for sample in samples))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())


def mix_external_audio(primary, backing, volume=0.35):
    volume = max(0.0, min(1.5, float(volume)))
    count = max(len(primary), len(backing))
    mixed = [0.0] * count
    for i in range(count):
        voice = primary[i] if i < len(primary) else 0.0
        music = backing[i] if i < len(backing) else 0.0
        mixed[i] = voice + music * volume
    peak = max(0.001, max(abs(sample) for sample in mixed))
    if peak > 0.94:
        scale = 0.94 / peak
        mixed = [sample * scale for sample in mixed]
    return mixed


def save_project(path, notes, settings):
    payload = {
        "format": "hanul-synth-project-v1",
        "settings": settings,
        "notes": [asdict(note) for note in notes],
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_project(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Note(**item) for item in payload.get("notes", [])], payload.get("settings", {})
