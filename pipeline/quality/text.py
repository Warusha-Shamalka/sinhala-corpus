"""Visible text warning signals; no heuristic grants training approval."""
import re
import unicodedata


def flags(text):
    warnings = []
    foreign = sum(any(unicodedata.name(c, '').startswith(name) for name in
                      ('DEVANAGARI', 'THAI', 'CYRILLIC', 'CJK')) for c in text if c.isalpha())
    if foreign >= 3:
        warnings.append('unexpected_script_needs_source_check')
    words = re.findall(r'\S+', text.replace('<br>', '\n'))
    repeated = False
    for width in range(1, min(25, len(words) // 4 + 1)):
        for i in range(len(words) - width * 4 + 1):
            block = words[i:i + width]
            if width * 4 >= 16 and words[i:i + width * 4] == block * 4:
                repeated = True; break
        if repeated: break
    if repeated:
        warnings.append('repeated_text_needs_source_check')
    return warnings
