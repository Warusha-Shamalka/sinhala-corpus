"""Group exact text and long near-duplicates without language-specific lookup data."""
import hashlib


def group(records, threshold=0.9, minimum_words=30, width=5):
    parents = list(range(len(records)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]; i = parents[i]
        return i
    def union(a, b):
        a, b = root(a), root(b)
        if a != b: parents[max(a, b)] = min(a, b)
    exact, index, shingles = {}, {}, []
    for number, record in enumerate(records):
        words = record['text'].split()
        normalized = ' '.join(words)
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        if digest in exact: union(number, exact[digest])
        exact[digest] = number
        tokens = {tuple(words[i:i + width]) for i in range(len(words) - width + 1)} if len(words) >= minimum_words else set()
        candidates = set()
        for token in tokens: candidates.update(index.get(token, ()))
        for prior in candidates:
            other = shingles[prior]
            if len(tokens & other) / len(tokens | other) >= threshold:
                union(number, prior)
        for token in tokens: index.setdefault(token, []).append(number)
        shingles.append(tokens)
    groups = {}
    for number in range(len(records)):
        groups.setdefault(root(number), []).append(number)
    for members in groups.values():
        if len({records[i]['split'] for i in members}) != 1:
            raise ValueError('Exact or near-duplicate text crosses splits')
    return list(groups.values())
