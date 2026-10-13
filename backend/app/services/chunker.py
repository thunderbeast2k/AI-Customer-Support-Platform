"""
Document Text Chunking Module.
Splits continuous text into overlapping semantic passages for vector embeddings.
"""
from typing import List, Dict, Any


def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
) -> List[Dict[str, Any]]:
    """
    Splits text into chunks of roughly `chunk_size` characters with `chunk_overlap` overlap.
    Attempts to respect paragraph and sentence boundaries.
    """
    if not text or not text.strip():
        return []

    if len(text) <= chunk_size:
        return [
            {
                "chunk_index": 0,
                "content": text.strip(),
                "char_length": len(text.strip()),
                "token_estimate": max(1, len(text.strip()) // 4),
            }
        ]

    chunks = []
    start = 0
    chunk_index = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)

        # If not at the very end of text, attempt to break at a newline or period
        if end < text_length:
            # Look for double newline first (paragraph break)
            para_break = text.rfind("\n\n", start, end)
            if para_break != -1 and para_break > start + (chunk_size // 2):
                end = para_break + 2
            else:
                # Look for sentence boundary
                sentence_break = text.rfind(". ", start, end)
                if sentence_break != -1 and sentence_break > start + (chunk_size // 2):
                    end = sentence_break + 2
                else:
                    # Look for space
                    space_break = text.rfind(" ", start, end)
                    if space_break != -1 and space_break > start + (chunk_size // 2):
                        end = space_break + 1

        chunk_str = text[start:end].strip()
        if chunk_str:
            chunks.append(
                {
                    "chunk_index": chunk_index,
                    "content": chunk_str,
                    "char_length": len(chunk_str),
                    "token_estimate": max(1, len(chunk_str) // 4),
                }
            )
            chunk_index += 1

        if end >= text_length:
            break

        # Advance by chunk_size - chunk_overlap
        step = max(1, (end - start) - chunk_overlap)
        start += step

    return chunks
