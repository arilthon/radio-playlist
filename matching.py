"""Comparação conservadora de artista, título e versão."""
from difflib import SequenceMatcher
import re
import unicodedata


def normalize(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    return ' '.join(re.sub(r'[^\w\s]', ' ', ''.join(c for c in text if not unicodedata.combining(c))).split())


def artist_name(text):
    # Metadados de rádio frequentemente acrescentam “Grupo” ao nome de catálogo.
    return re.sub(r'^grupo\s+', '', normalize(text))


def artist_parts(text):
    return list(dict.fromkeys(artist_name(part) for part in text.split('/') if artist_name(part)))


def search_artist(text):
    return ' '.join(artist_parts(text))


def artist_similarity(expected, names):
    # Preserve literal band names such as AC/DC before interpreting collaborations.
    full = max((SequenceMatcher(None, artist_name(expected), artist_name(name)).ratio()
                for name in names), default=0)
    parts = artist_parts(expected)
    # Every credited radio artist must match; a guest alone is insufficient.
    collaboration = min((max((SequenceMatcher(None, part, artist_name(name)).ratio()
                              for name in names), default=0) for part in parts), default=0)
    return max(full, collaboration)


def song_title(text):
    # Credits in parentheses are not part of the song title; keep version labels.
    return re.sub(r'\s*[([]\s*(?:feat\.?|ft\.?|featuring)\s+[^)\]]+[)\]]',
                  '', text, flags=re.IGNORECASE).strip()


def live_title(text):
    # Remove somente indicações de versão, preservando títulos como “Live Forever”.
    pattern = r'\s*(?:[([]\s*(?:ao vivo|live)\b[^)\]]*[)\]]|[-–—]\s*(?:ao vivo|live)\b.*)$'
    stripped = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
    return normalize(stripped), stripped != text.strip()


def is_live(track):
    attrs = track.get('attributes', {})
    return live_title(attrs.get('title', ''))[1] or bool(
        re.search(r'\b(?:ao vivo|live)\b', normalize(attrs.get('version') or '')))


def score_track(artist, song, track):
    attrs = track.get('attributes', {})
    title, _ = live_title(song_title(attrs.get('title', '')))
    expected, _ = live_title(song_title(song))
    names = track.get('_artists', [])
    artist_score = artist_similarity(artist, names)
    title_score = SequenceMatcher(None, expected, title).ratio()
    version = normalize(attrs.get('version') or '') + ' ' + title
    for word in ('remix', 'karaoke', 'instrumental', 'acoustic', 'acustico'):
        if bool(re.search(r'\b' + re.escape(word) + r'\b', version)) != bool(re.search(r'\b' + re.escape(word) + r'\b', expected)):
            return 0.0
    if artist_score < .80 or title_score < .80:
        return 0.0
    return round(.45 * artist_score + .55 * title_score, 4)


def choose_track(artist, song, candidates):
    ranked = [(score_track(artist, song, t), t) for t in candidates]
    eligible = [(score, t) for score, t in ranked if score >= .88]
    if not eligible:
        return None, max((score for score, _ in ranked), default=0)
    # Preferir estúdio entre candidatos aprovados; se a rádio informa ao vivo,
    # priorizar essa versão. A pontuação continua representando a semelhança.
    expected_live = live_title(song)[1]
    eligible.sort(key=lambda item: (is_live(item[1]) == expected_live, item[0]), reverse=True)
    score, selected = eligible[0]
    return selected, score
