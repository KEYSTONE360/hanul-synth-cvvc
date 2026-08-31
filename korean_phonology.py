CHOSEONG = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]
JUNGSEONG = [
    "ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ", "ㅙ",
    "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ", "ㅢ", "ㅣ",
]
JONGSEONG = [
    "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ",
    "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ",
    "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]

COMPLEX_CODA = {
    "ㄳ": ("ㄱ", "ㅅ"), "ㄵ": ("ㄴ", "ㅈ"), "ㄶ": ("ㄴ", "ㅎ"),
    "ㄺ": ("ㄹ", "ㄱ"), "ㄻ": ("ㄹ", "ㅁ"), "ㄼ": ("ㄹ", "ㅂ"),
    "ㄽ": ("ㄹ", "ㅅ"), "ㄾ": ("ㄹ", "ㅌ"), "ㄿ": ("ㄹ", "ㅍ"),
    "ㅀ": ("ㄹ", "ㅎ"), "ㅄ": ("ㅂ", "ㅅ"),
}
CODA_NEUTRAL = {
    "ㄲ": "ㄱ", "ㄳ": "ㄱ", "ㅋ": "ㄱ",
    "ㅅ": "ㄷ", "ㅆ": "ㄷ", "ㅈ": "ㄷ", "ㅊ": "ㄷ", "ㅌ": "ㄷ", "ㅎ": "ㄷ",
    "ㅍ": "ㅂ", "ㅄ": "ㅂ",
}


def decompose(char: str):
    if len(char) != 1 or not 0xAC00 <= ord(char) <= 0xD7A3:
        return None
    index = ord(char) - 0xAC00
    return [
        CHOSEONG[index // 588],
        JUNGSEONG[(index % 588) // 28],
        JONGSEONG[index % 28],
    ]


def compose(onset: str, vowel: str, coda: str = "") -> str:
    try:
        index = CHOSEONG.index(onset) * 588
        index += JUNGSEONG.index(vowel) * 28
        index += JONGSEONG.index(coda)
        return chr(0xAC00 + index)
    except ValueError:
        return ""


def apply_initial_rule(parts, word_initial: bool):
    """노래 입력에서 흔한 단어 첫머리 두음법칙을 보수적으로 적용한다."""
    if not word_initial or parts is None:
        return parts
    onset, vowel, coda = parts
    if onset == "ㄴ" and vowel in {"ㅕ", "ㅛ", "ㅠ", "ㅣ"}:
        onset = "ㅇ"
    elif onset == "ㄹ":
        if vowel in {"ㅑ", "ㅕ", "ㅖ", "ㅛ", "ㅠ", "ㅣ"}:
            onset = "ㅇ"
        elif vowel in {"ㅏ", "ㅐ", "ㅗ", "ㅚ", "ㅜ", "ㅡ"}:
            onset = "ㄴ"
    return [onset, vowel, coda]


def normalize_lyrics(lyrics, enable_rules=True, enable_initial=True):
    """음표별 한글 한 글자를 발음용 초성·중성·종성으로 변환한다."""
    result = []
    word_initial = True
    for lyric in lyrics:
        text = (lyric or "아").strip()
        original = lyric or "아"
        char = next((c for c in text if decompose(c)), "아")
        parts = decompose(char)
        marked_initial = original.startswith((" ", "'", "/"))
        parts = apply_initial_rule(parts, (word_initial or marked_initial) and enable_initial)
        result.append(parts)
        word_initial = original.endswith((" ", "/", "-"))

    if not enable_rules:
        return result

    for i in range(len(result) - 1):
        current = result[i]
        following = result[i + 1]
        if not current or not following:
            continue
        onset, vowel, coda = current
        next_onset, next_vowel, next_coda = following
        if not coda:
            continue

        # 연음: 받침 뒤에 모음(초성 ㅇ)이 오면 다음 음절의 초성으로 이동한다.
        if next_onset == "ㅇ":
            if coda in COMPLEX_CODA:
                remain, move = COMPLEX_CODA[coda]
                current[2] = remain
                following[0] = move
            else:
                current[2] = ""
                following[0] = CODA_NEUTRAL.get(coda, coda)
            # ㄷ/ㅌ + 이 계열의 구개음화
            if following[1] in {"ㅣ", "ㅕ", "ㅖ", "ㅑ"}:
                if following[0] == "ㄷ":
                    following[0] = "ㅈ"
                elif following[0] == "ㅌ":
                    following[0] = "ㅊ"
            continue

        neutral = CODA_NEUTRAL.get(coda, coda)

        # 비음화
        if next_onset in {"ㄴ", "ㅁ"}:
            if neutral == "ㄱ":
                current[2] = "ㅇ"
            elif neutral == "ㄷ":
                current[2] = "ㄴ"
            elif neutral == "ㅂ":
                current[2] = "ㅁ"

        # 유음화
        if (current[2], next_onset) in {("ㄴ", "ㄹ"), ("ㄹ", "ㄴ")}:
            current[2] = "ㄹ"
            following[0] = "ㄹ"

        # 대표적인 된소리되기
        if neutral in {"ㄱ", "ㄷ", "ㅂ"}:
            tense = {"ㄱ": "ㄲ", "ㄷ": "ㄸ", "ㅂ": "ㅃ", "ㅅ": "ㅆ", "ㅈ": "ㅉ"}
            if next_onset in tense:
                following[0] = tense[next_onset]

    return result


def phonemes_for(parts):
    if not parts:
        return ["ㅇ", "ㅏ"]
    onset, vowel, coda = parts
    phonemes = []
    if onset != "ㅇ":
        phonemes.append(onset)
    phonemes.append(vowel)
    if coda:
        phonemes.append(CODA_NEUTRAL.get(coda, coda))
    return phonemes
