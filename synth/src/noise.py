"""Deterministic, intent-preserving Vietnamese question noise.

Question noise is always separate from private debug metadata; no model calls.
"""
from __future__ import annotations
import random
import re
import unicodedata


def undiacritic(text: str) -> str:
    text = text.replace('đ', 'd').replace('Đ', 'D')
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


def inject(question: str, dictionary: dict, rng: random.Random) -> tuple[str, list[str]]:
    output = question
    tags = []
    modes = ['teencode', 'remove_diacritics', 'telex_vni_typo', 'repeat_letter', 'spacing', 'case', 'punctuation']
    rng.shuffle(modes)
    # One or two changes, avoiding brittle destruction of short product references.
    for mode in modes[:rng.randint(1, 2)]:
        old = output
        if mode == 'teencode':
            matches = []
            for phrase in sorted(dictionary, key=len, reverse=True):
                if re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', output, flags=re.I):
                    matches.append(phrase)
            if matches:
                phrase = rng.choice(matches[:20])
                output = re.sub(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', rng.choice(dictionary[phrase]), output, count=1, flags=re.I)
        elif mode == 'remove_diacritics':
            if rng.random() < .33:
                output = undiacritic(output)
            else:
                tokens = output.split(' ')
                places = [i for i, token in enumerate(tokens) if undiacritic(token) != token]
                if places:
                    for ix in rng.sample(places, min(len(places), rng.randint(1, 3))):
                        tokens[ix] = undiacritic(tokens[ix])
                    output = ' '.join(tokens)
        elif mode == 'telex_vni_typo':
            # Text-only typo, leaving critical numbers and product codes alone.
            tokens = re.findall(r'[a-zA-ZÀ-ỹĐđ]{6,}', output)
            generic = [x for x in tokens if x.lower() not in ('iphone', 'samsung')]
            if generic:
                token = rng.choice(generic)
                if token.lower() == 'tháng':
                    error = 'thnags'
                else:
                    k = rng.randrange(1, len(token)-2)
                    error = token[:k] + token[k+1] + token[k] + token[k+2:]
                output = output.replace(token, error, 1)
        elif mode == 'repeat_letter':
            tokens = re.findall(r'[a-zA-ZÀ-ỹĐđ]{5,}', output)
            if tokens:
                token = rng.choice(tokens)
                output = output.replace(token, token + token[-1] * rng.randint(1, 2), 1)
        elif mode == 'spacing':
            if ' ' in output:
                output = output.replace(' ', '  ', 1) if rng.random() < .5 else output.replace(' ', '', 1)
        elif mode == 'case':
            tokens = output.split(' ')
            ix = rng.randrange(len(tokens))
            tokens[ix] = tokens[ix].upper() if rng.random() < .7 else tokens[ix].lower()
            output = ' '.join(tokens)
        elif mode == 'punctuation':
            output = output.rstrip('?!. ') if output.endswith('?') else output + '?'
        if output != old:
            tags.append(mode)
    if not tags:
        output = output[:-1] if output.endswith('?') else output + '  '
        tags = ['punctuation']
    return output, tags
